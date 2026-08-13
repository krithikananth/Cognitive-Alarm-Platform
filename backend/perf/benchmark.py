"""Dashboard API benchmark runner.

Drives the real FastAPI application in-process (ASGI transport, no network hop)
against a seeded database, so the measured latency is application + ORM + SQL
time without HTTP/proxy noise. For every scenario it reports latency
percentiles, the number of SQL statements issued per request, and the slowest
statements by total time — plus query plans when ``--explain`` is passed.

Usage::

    python -m perf.benchmark --profile medium --iterations 15
    python -m perf.benchmark --database-url postgresql+psycopg2://... --explain
    python -m perf.benchmark --skip-seed --output perf/results/after.json

Run it twice (before/after a change) and diff the JSON outputs.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DEFAULT_DB_PATH = BACKEND_ROOT / "perf" / ".perfdata" / "perf.db"
DEFAULT_RESULTS_DIR = BACKEND_ROOT / "perf" / "results"

# Latency budgets used to flag regressions. p95, milliseconds.
DEFAULT_P95_BUDGET_MS = 400.0
BUDGETS_MS: Dict[str, float] = {
    "dashboard_wake_stats_365": 800.0,
    "admin_dashboard": 1500.0,
    "admin_statistics": 1500.0,
    "admin_statistics_365": 1500.0,
    "admin_analytics": 1000.0,
    "admin_alarms": 1000.0,
    "admin_reports": 1000.0,
    "coach_overview": 1000.0,
    "coach_clients": 1000.0,
}


@dataclass
class Scenario:
    """One benchmarked HTTP request."""

    key: str
    dashboard: str
    method: str
    path: str
    principal: str  # user | admin | coach
    params: Dict[str, Any] = field(default_factory=dict)


SCENARIOS: List[Scenario] = [
    # ── User dashboard (frontend/src/pages/UserDashboard.jsx) ──
    Scenario("dashboard_summary_weekly", "user", "GET", "/api/v1/dashboard/summary", "user", {"period": "weekly"}),
    Scenario("dashboard_summary_monthly", "user", "GET", "/api/v1/dashboard/summary", "user", {"period": "monthly"}),
    Scenario("dashboard_wake_stats", "user", "GET", "/api/v1/dashboard/wake-stats", "user", {"days": 30}),
    Scenario("dashboard_wake_stats_365", "user", "GET", "/api/v1/dashboard/wake-stats", "user", {"days": 365}),
    Scenario("dashboard_challenge_performance", "user", "GET", "/api/v1/dashboard/challenge-performance", "user", {"days": 30}),
    Scenario("dashboard_productivity", "user", "GET", "/api/v1/dashboard/productivity", "user", {"days": 30}),
    Scenario("dashboard_alarm_history", "user", "GET", "/api/v1/dashboard/alarm-history", "user", {"page": 1, "per_page": 20, "days": 30}),
    Scenario("user_profile_stats", "user", "GET", "/api/v1/users/profile/stats", "user", {}),
    Scenario("analytics_habit_trends", "user", "GET", "/api/v1/analytics/behavioral/habits", "user", {"days": 30}),
    Scenario("analytics_monthly_trends", "user", "GET", "/api/v1/analytics/behavioral/trends/monthly", "user", {"days": 30}),
    # ── Admin dashboard (frontend/src/pages/AdminDashboard.jsx) ──
    Scenario("admin_dashboard", "admin", "GET", "/api/v1/admin/dashboard", "admin", {"days": 30}),
    Scenario("admin_statistics", "admin", "GET", "/api/v1/admin/statistics", "admin", {"days": 30}),
    Scenario("admin_statistics_365", "admin", "GET", "/api/v1/admin/statistics", "admin", {"days": 365}),
    Scenario("admin_alarms", "admin", "GET", "/api/v1/admin/alarms", "admin", {"days": 30}),
    Scenario("admin_analytics", "admin", "GET", "/api/v1/admin/analytics", "admin", {"days": 30}),
    Scenario("admin_recommendations", "admin", "GET", "/api/v1/admin/recommendations", "admin", {"days": 30}),
    Scenario("admin_reports", "admin", "GET", "/api/v1/admin/reports", "admin", {}),
    Scenario("admin_users", "admin", "GET", "/api/v1/admin/users", "admin", {"page": 1, "per_page": 20}),
    # ── Coach dashboard (frontend/src/pages/WellnessCoachDashboard.jsx) ──
    Scenario("coach_overview", "coach", "GET", "/api/v1/coach/overview", "coach", {"days": 30}),
    Scenario("coach_clients", "coach", "GET", "/api/v1/coach/clients", "coach", {"page": 1, "per_page": 20}),
]


@dataclass
class ScenarioResult:
    key: str
    dashboard: str
    path: str
    params: Dict[str, Any]
    status_code: int
    iterations: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    mean_ms: float
    queries_per_request: float
    sql_execute_ms_per_request: float
    app_ms_per_request: float
    response_bytes: int
    budget_ms: float
    over_budget: bool
    top_statements: List[Dict[str, Any]]
    plans: Dict[str, List[str]] = field(default_factory=dict)
    unindexed_scans: List[str] = field(default_factory=list)


def percentile(values: List[float], pct: float) -> float:
    """Nearest-rank percentile; stable for the small sample sizes used here."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(pct / 100.0 * len(ordered)))))
    return ordered[rank - 1]


def build_app_client(engine):
    """Return a test client bound to the FastAPI app with the perf DB wired in.

    ``TestClient`` is used (not a network client) so the measurement isolates
    application + ORM + SQL time. It is intentionally not entered as a context
    manager: that would fire startup events (scheduler, FCM, table creation)
    which are irrelevant to dashboard read performance.
    """
    from fastapi.testclient import TestClient
    from sqlalchemy.orm import sessionmaker

    from app.db.session import get_db
    from app.main import app

    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def override_get_db():
        db = factory()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db

    return TestClient(app, raise_server_exceptions=False)


def make_tokens(user_id: int, admin_id: int, coach_id: int) -> Dict[str, str]:
    from app.core.security import create_access_token
    from app.models.user import UserRole

    ttl = timedelta(hours=12)
    return {
        "user": create_access_token({"sub": str(user_id), "role": UserRole.USER.value}, ttl),
        "admin": create_access_token({"sub": str(admin_id), "role": UserRole.ADMIN.value}, ttl),
        "coach": create_access_token({"sub": str(coach_id), "role": UserRole.WELLNESS_COACH.value}, ttl),
    }


def run_scenario(
    client,
    recorder,
    engine,
    scenario: Scenario,
    token: str,
    iterations: int,
    warmup: int,
    explain_enabled: bool,
    top_n: int,
) -> ScenarioResult:
    from perf.instrumentation import explain, scans_without_index

    headers = {"Authorization": f"Bearer {token}"}
    latencies: List[float] = []
    status_code = 0
    response_bytes = 0

    for _ in range(warmup):
        client.request(scenario.method, scenario.path, params=scenario.params, headers=headers)

    with recorder.capture():
        for _ in range(iterations):
            started = time.perf_counter()
            response = client.request(
                scenario.method, scenario.path, params=scenario.params, headers=headers
            )
            latencies.append((time.perf_counter() - started) * 1000.0)
            status_code = response.status_code
            response_bytes = len(response.content)

    query_count, sql_ms = recorder.totals()
    slowest = recorder.slowest(top_n)

    plans: Dict[str, List[str]] = {}
    unindexed: List[str] = []
    if explain_enabled:
        for stat in slowest:
            if not stat.raw_sql.lstrip().upper().startswith("SELECT"):
                continue
            plan = explain(engine, stat)
            plans[stat.sql] = plan
            if scans_without_index(plan):
                unindexed.append(stat.sql[:300])

    budget = BUDGETS_MS.get(scenario.key, DEFAULT_P95_BUDGET_MS)
    p95 = percentile(latencies, 95)
    mean_ms = statistics.fmean(latencies) if latencies else 0.0
    sql_per_request = sql_ms / iterations

    return ScenarioResult(
        key=scenario.key,
        dashboard=scenario.dashboard,
        path=scenario.path,
        params=scenario.params,
        status_code=status_code,
        iterations=iterations,
        p50_ms=round(percentile(latencies, 50), 2),
        p95_ms=round(p95, 2),
        p99_ms=round(percentile(latencies, 99), 2),
        min_ms=round(min(latencies), 2) if latencies else 0.0,
        max_ms=round(max(latencies), 2) if latencies else 0.0,
        mean_ms=round(mean_ms, 2),
        queries_per_request=round(query_count / iterations, 2),
        sql_execute_ms_per_request=round(sql_per_request, 2),
        app_ms_per_request=round(max(mean_ms - sql_per_request, 0.0), 2),
        response_bytes=response_bytes,
        budget_ms=budget,
        over_budget=p95 > budget,
        top_statements=[
            {
                "sql": s.sql[:600],
                "calls_per_request": round(s.calls / iterations, 2),
                "execute_ms_per_request": round(s.total_ms / iterations, 2),
                "avg_ms": round(s.avg_ms, 3),
                "max_ms": round(s.max_ms, 3),
            }
            for s in slowest
        ],
        plans=plans,
        unindexed_scans=unindexed,
    )


def render_markdown(payload: Dict[str, Any]) -> str:
    """Render a human-readable summary of a results payload."""
    lines: List[str] = []
    meta = payload["meta"]
    lines.append(f"### Benchmark: {meta['label']}")
    lines.append("")
    lines.append(
        f"- Dialect: `{meta['dialect']}` · dataset `{meta['dataset_profile']}` "
        f"· {meta['total_rows']:,} rows · {meta['iterations']} iterations/scenario"
    )
    lines.append("")
    lines.append("| Scenario | Dashboard | Status | p50 ms | p95 ms | p99 ms | Queries/req | SQL exec ms | App ms | Budget | Over |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|---|")
    for r in payload["scenarios"]:
        lines.append(
            f"| `{r['key']}` | {r['dashboard']} | {r['status_code']} | {r['p50_ms']} | "
            f"{r['p95_ms']} | {r['p99_ms']} | {r['queries_per_request']} | "
            f"{r['sql_execute_ms_per_request']} | {r['app_ms_per_request']} | {r['budget_ms']} | "
            f"{'YES' if r['over_budget'] else 'no'} |"
        )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark ICAP dashboard APIs.")
    parser.add_argument(
        "--database-url",
        default=os.getenv("PERF_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}"),
        help="SQLAlchemy URL for the benchmark database (never point this at production).",
    )
    parser.add_argument("--profile", default="medium", choices=["small", "medium", "large"])
    parser.add_argument("--iterations", type=int, default=15)
    parser.add_argument("--warmup", type=int, default=2)
    parser.add_argument("--top-statements", type=int, default=6)
    parser.add_argument("--skip-seed", action="store_true", help="Reuse the existing dataset.")
    parser.add_argument("--explain", action="store_true", help="Capture query plans for slow statements.")
    parser.add_argument("--only", nargs="*", help="Restrict to specific scenario keys.")
    parser.add_argument("--label", default="baseline", help="Label recorded in the results file.")
    parser.add_argument("--output", default=None, help="Path for the JSON results file.")
    parser.add_argument(
        "--fail-on-budget",
        action="store_true",
        help="Exit non-zero when any scenario's p95 exceeds its budget (CI guard).",
    )
    args = parser.parse_args(argv)

    os.environ.setdefault("SECRET_KEY", "perf-benchmark-secret-key-not-for-production")

    from perf import dataset as dataset_module
    from perf.instrumentation import QueryRecorder

    database_url = args.database_url
    if database_url.startswith("sqlite:///"):
        DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    engine = dataset_module.make_engine(database_url)
    profile = dataset_module.PROFILES[args.profile]

    if args.skip_seed:
        from sqlalchemy.orm import sessionmaker

        from app.models.user import User, UserRole

        session = sessionmaker(bind=engine)()
        try:
            rows = session.query(User.id, User.role).order_by(User.id).all()
            if not rows:
                print("No seeded data found — re-run without --skip-seed.", file=sys.stderr)
                return 2
            seed_result = dataset_module.SeedResult(
                profile=profile,
                user_id=next(r.id for r in rows if r.role == UserRole.USER),
                admin_id=next(r.id for r in rows if r.role == UserRole.ADMIN),
                coach_id=next(r.id for r in rows if r.role == UserRole.WELLNESS_COACH),
                row_counts=dataset_module.count_rows(session),
            )
        finally:
            session.close()
    else:
        print(f"Seeding '{profile.name}' dataset into {engine.url.render_as_string(hide_password=True)} ...")
        seed_started = time.perf_counter()
        seed_result = dataset_module.seed(engine, profile)
        print(f"Seeded {seed_result.total_rows():,} rows in {time.perf_counter() - seed_started:.1f}s")
        for table, count in seed_result.row_counts.items():
            print(f"  {table:24s} {count:,}")

    client = build_app_client(engine)
    tokens = make_tokens(seed_result.user_id, seed_result.admin_id, seed_result.coach_id)
    recorder = QueryRecorder(engine=engine)

    selected = SCENARIOS
    if args.only:
        wanted = set(args.only)
        selected = [s for s in SCENARIOS if s.key in wanted]

    results: List[ScenarioResult] = []
    try:
        for scenario in selected:
            print(f"  benchmarking {scenario.key} ...", end="", flush=True)
            result = run_scenario(
                client,
                recorder,
                engine,
                scenario,
                tokens[scenario.principal],
                args.iterations,
                args.warmup,
                args.explain,
                args.top_statements,
            )
            results.append(result)
            print(f" p95={result.p95_ms}ms queries={result.queries_per_request} status={result.status_code}")
    finally:
        recorder.remove()

    payload = {
        "meta": {
            "label": args.label,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "dialect": engine.dialect.name,
            "database": engine.url.render_as_string(hide_password=True),
            "dataset_profile": profile.name,
            "row_counts": seed_result.row_counts,
            "total_rows": seed_result.total_rows(),
            "iterations": args.iterations,
            "warmup": args.warmup,
        },
        "scenarios": [asdict(r) for r in results],
    }

    output_path = Path(args.output) if args.output else DEFAULT_RESULTS_DIR / f"{args.label}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print()
    print(render_markdown(payload))
    print()
    print(f"Results written to {output_path}")

    failures = [r for r in results if r.status_code >= 400]
    if failures:
        print(f"\n{len(failures)} scenario(s) returned an error status:", file=sys.stderr)
        for r in failures:
            print(f"  {r.key} -> {r.status_code}", file=sys.stderr)
        return 1

    if args.fail_on_budget:
        over = [r for r in results if r.over_budget]
        if over:
            print(f"\n{len(over)} scenario(s) over budget:", file=sys.stderr)
            for r in over:
                print(f"  {r.key}: p95 {r.p95_ms}ms > {r.budget_ms}ms", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
