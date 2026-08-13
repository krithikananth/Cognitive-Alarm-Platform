"""
Concurrent user handling capacity — measured, not assumed.

``perf/loadtest/locustfile.py`` drives a live server at a *fixed* number of
users, which answers "does 20 users work?" but never "how many users can this
serve?". Capacity is the highest concurrency that still meets a latency target
with zero failures, and finding it requires a ramp.

This harness ramps concurrency through a configured ladder, replaying a real
dashboard page load per simulated user, and reports for each level:

- throughput (requests/second)
- p50 / p95 / p99 latency
- failure count
- whether the level met the SLA

The highest level that meets the SLA is the **measured capacity**. Levels are
run in ascending order and the ramp stops once a level fails, so a saturated
system is not hammered pointlessly.

Two transport modes:

``in-process`` (default)
    Requests go through the ASGI app via ``TestClient``, so the numbers isolate
    application + ORM + SQL cost and measure neither a network nor a worker
    count. That makes the ceiling a property of the code and the database —
    the thing this repo can actually change.

``live-http`` (``--base-url``)
    Requests go over a real socket to a running uvicorn, through the real
    middleware stack, real JSON serialization and real authentication. This is
    the mode that produces a deployment-relevant number, because it includes
    the worker count and the event-loop/threadpool behaviour that
    ``TestClient`` short-circuits.

Run it against PostgreSQL for a number that means anything about production —
SQLite serializes at the database level and its ceiling is the rig's, not the
app's.

Usage::

    python -m perf.capacity --profile medium --label capacity-sqlite
    # PostgreSQL, in-process
    python -m perf.capacity --database-url postgresql+psycopg2://... \\
        --profile medium --label capacity-pg
    # PostgreSQL, live uvicorn (the number that counts)
    python -m perf.capacity --database-url postgresql+psycopg2://... \\
        --base-url http://127.0.0.1:8000 --skip-seed --label capacity-pg-live
    python -m perf.capacity --levels 1 5 10 25 50 100 --sla-p95-ms 1000
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DEFAULT_DB_PATH = BACKEND_ROOT / "perf" / ".perfdata" / "capacity.db"
DEFAULT_RESULTS_DIR = BACKEND_ROOT / "perf" / "results"

#: Concurrency ladder. Ascending; the ramp stops at the first failing level.
DEFAULT_LEVELS = (1, 5, 10, 20, 40, 80)

#: A level passes when p95 is at or under this and nothing failed. 400ms is the
#: project's single-request target from perf/benchmark.py; a page load under
#: concurrency is allowed more, but not unboundedly more.
DEFAULT_SLA_P95_MS = 1500.0

#: Page loads each simulated user performs per level.
DEFAULT_ROUNDS = 3

#: One user dashboard page load, as UserDashboard.jsx actually fans out.
PAGE_LOAD: Tuple[Tuple[str, Dict[str, Any]], ...] = (
    ("/api/v1/dashboard/summary", {"period": "weekly"}),
    ("/api/v1/dashboard/wake-stats", {"days": 30}),
    ("/api/v1/dashboard/challenge-performance", {"days": 30}),
    ("/api/v1/dashboard/alarm-history", {"page": 1, "per_page": 20, "days": 30}),
    ("/api/v1/users/profile/stats", {}),
    ("/api/v1/analytics/behavioral/habits", {"days": 30}),
)


@dataclass
class LevelResult:
    """What one concurrency level measured."""

    concurrency: int
    rounds: int
    requests: int
    failures: int
    failure_detail: List[str]
    elapsed_s: float
    throughput_rps: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    max_ms: float
    mean_ms: float
    sla_p95_ms: float
    met_sla: bool
    detail: Dict[str, Any] = field(default_factory=dict)


def percentile(values: List[float], pct: float) -> float:
    """Nearest-rank percentile — identical to benchmark.py and request_metrics."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(pct / 100.0 * len(ordered)))))
    return ordered[rank - 1]


def build_client(engine, *, pool_note: str = ""):
    """TestClient bound to the capacity database, one session per request."""
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
    if pool_note:
        print(pool_note)
    return TestClient(app, raise_server_exceptions=False)


def make_token(user_id: int) -> str:
    from app.core.security import create_access_token
    from app.models.user import UserRole

    return create_access_token(
        {"sub": str(user_id), "role": UserRole.USER.value}, timedelta(hours=12)
    )


class LiveClient:
    """``TestClient``-shaped facade over a real HTTP connection.

    Exposing the same ``get(path, params=, headers=)`` signature keeps the
    measurement loop identical in both transport modes, so an in-process run
    and a live run differ only in what they include — not in what they do.
    """

    def __init__(self, base_url: str, concurrency: int, timeout_s: float):
        import httpx

        self._client = httpx.Client(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
            # Keepalive slots for every simulated user, otherwise the ramp
            # measures connection setup instead of the application.
            limits=httpx.Limits(
                max_connections=concurrency + 10,
                max_keepalive_connections=concurrency + 10,
            ),
        )

    def get(self, path: str, params=None, headers=None):
        return self._client.get(path, params=params, headers=headers)

    def post(self, path: str, json=None):
        return self._client.post(path, json=json)

    def close(self) -> None:
        self._client.close()


def wait_for_server(client: "LiveClient", attempts: int = 60) -> bool:
    """Poll ``/health`` until the target server answers."""
    for _ in range(attempts):
        try:
            if client.get("/health").status_code == 200:
                return True
        except Exception:  # noqa: BLE001 — server not up yet is expected here
            pass
        time.sleep(1.0)
    return False


def login_tokens(client: "LiveClient", emails: List[str], password: str) -> List[str]:
    """Obtain real bearer tokens over HTTP, one per simulated user.

    Live mode must not mint its own tokens: a signing-key mismatch would then
    surface as a wall of 401s halfway through a ramp instead of immediately.
    """
    tokens: List[str] = []
    for email in emails:
        response = client.post(
            "/api/v1/auth/login", json={"email": email, "password": password}
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"login failed for {email}: HTTP {response.status_code} {response.text[:200]}"
            )
        tokens.append(response.json()["access_token"])
    return tokens


def _page_load(client, headers) -> Tuple[List[float], List[str]]:
    """One dashboard page load. Returns (durations_ms, failures)."""
    durations: List[float] = []
    failures: List[str] = []
    for path, params in PAGE_LOAD:
        started = time.perf_counter()
        try:
            response = client.get(path, params=params, headers=headers)
        except Exception as exc:  # noqa: BLE001 — a raised error is a failure
            failures.append(f"{path}: {type(exc).__name__}: {exc}")
            continue
        elapsed_ms = (time.perf_counter() - started) * 1000.0
        if response.status_code != 200:
            failures.append(f"{path}: HTTP {response.status_code}")
            continue
        durations.append(elapsed_ms)
    return durations, failures


def run_level(
    client,
    tokens: List[str],
    concurrency: int,
    rounds: int,
    sla_p95_ms: float,
) -> LevelResult:
    """Drive ``concurrency`` simulated users through ``rounds`` page loads each."""

    def one_user(index: int) -> Tuple[List[float], List[str]]:
        headers = {"Authorization": f"Bearer {tokens[index % len(tokens)]}"}
        durations: List[float] = []
        failures: List[str] = []
        for _ in range(rounds):
            d, f = _page_load(client, headers)
            durations += d
            failures += f
        return durations, failures

    # Warm the caches once, serially, so the first level is not measuring imports.
    one_user(0)

    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        batches = list(pool.map(one_user, range(concurrency)))
    elapsed = time.perf_counter() - started

    durations = [d for batch, _ in batches for d in batch]
    failures = [f for _, batch in batches for f in batch]
    requests = len(durations) + len(failures)
    p95 = percentile(durations, 95)

    return LevelResult(
        concurrency=concurrency,
        rounds=rounds,
        requests=requests,
        failures=len(failures),
        failure_detail=sorted(set(failures))[:10],
        elapsed_s=round(elapsed, 3),
        throughput_rps=round(requests / max(elapsed, 1e-9), 2),
        p50_ms=round(percentile(durations, 50), 2),
        p95_ms=round(p95, 2),
        p99_ms=round(percentile(durations, 99), 2),
        max_ms=round(max(durations), 2) if durations else 0.0,
        mean_ms=round(statistics.fmean(durations), 2) if durations else 0.0,
        sla_p95_ms=sla_p95_ms,
        met_sla=bool(durations) and not failures and p95 <= sla_p95_ms,
        detail={"endpoints_per_page_load": len(PAGE_LOAD)},
    )


def render_markdown(payload: Dict[str, Any]) -> str:
    meta = payload["meta"]
    capacity = payload["capacity"]
    lines = [
        f"### Concurrency capacity: {meta['label']}",
        "",
        f"- Transport: `{meta['mode']}`"
        + (f" · target `{meta['base_url']}`" if meta.get("base_url") else ""),
        f"- Dialect: `{meta['dialect']}` · dataset `{meta['dataset_profile']}` "
        f"· {meta['total_rows']:,} rows",
        f"- SLA: p95 <= {meta['sla_p95_ms']} ms with zero failures",
        f"- Pool: {meta['pool_size']} + {meta['max_overflow']} overflow"
        if meta["pool_size"]
        else "- Pool: sized by the server under test (`DB_POOL_SIZE`/`DB_MAX_OVERFLOW`)",
        "",
        f"**Measured capacity: {capacity['concurrent_users']} concurrent users** "
        f"at {capacity['throughput_rps']} req/s"
        if capacity["concurrent_users"]
        else "**Measured capacity: none of the tested levels met the SLA**",
        "",
        "| Users | Requests | Failures | Throughput r/s | p50 ms | p95 ms | p99 ms | SLA |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in payload["levels"]:
        lines.append(
            f"| {r['concurrency']} | {r['requests']} | {r['failures']} | "
            f"{r['throughput_rps']} | {r['p50_ms']} | {r['p95_ms']} | "
            f"{r['p99_ms']} | {'PASS' if r['met_sla'] else 'FAIL'} |"
        )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure how many concurrent users ICAP can serve inside an SLA."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("PERF_CAPACITY_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}"),
        help="SQLAlchemy URL for the capacity database (never point at production).",
    )
    parser.add_argument("--profile", default="medium", choices=["small", "medium", "large"])
    parser.add_argument(
        "--base-url",
        default=os.getenv("PERF_BASE_URL"),
        help=(
            "Drive a live HTTP server (e.g. http://127.0.0.1:8000) instead of the "
            "in-process ASGI app. The server must already point at --database-url."
        ),
    )
    parser.add_argument(
        "--request-timeout-s",
        type=float,
        default=120.0,
        help="Per-request timeout in live mode; a timeout counts as a failure.",
    )
    parser.add_argument(
        "--levels",
        nargs="*",
        type=int,
        default=list(DEFAULT_LEVELS),
        help="Concurrency ladder, ascending.",
    )
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS)
    parser.add_argument("--sla-p95-ms", type=float, default=DEFAULT_SLA_P95_MS)
    parser.add_argument(
        "--no-stop-on-fail",
        action="store_true",
        help="Keep ramping past the first level that misses the SLA.",
    )
    parser.add_argument("--skip-seed", action="store_true", help="Reuse the existing dataset.")
    parser.add_argument("--label", default="capacity")
    parser.add_argument("--output", default=None)
    parser.add_argument(
        "--require-capacity",
        type=int,
        default=None,
        help=(
            "Exit non-zero if the measured capacity is below this many concurrent "
            "users (CI regression guard)."
        ),
    )
    args = parser.parse_args(argv)

    os.environ.setdefault("SECRET_KEY", "perf-benchmark-secret-key-not-for-production")

    from sqlalchemy.orm import sessionmaker

    from perf import dataset as dataset_module

    if args.database_url.startswith("sqlite:///"):
        DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    levels = sorted({max(1, n) for n in args.levels})
    peak = levels[-1]

    # The pool is the hard ceiling on concurrent users, so it must not be the
    # thing under test: size it above the peak level being measured.
    from sqlalchemy import create_engine
    from sqlalchemy.pool import QueuePool

    connect_args: Dict[str, Any] = {}
    is_sqlite = args.database_url.startswith("sqlite")
    if is_sqlite:
        connect_args = {"check_same_thread": False, "timeout": 30}
    engine = create_engine(
        args.database_url,
        connect_args=connect_args,
        poolclass=QueuePool,
        pool_size=peak + 5,
        max_overflow=peak,
        pool_pre_ping=True,
        future=True,
    )

    profile = dataset_module.PROFILES[args.profile]
    if args.skip_seed:
        from app.models.user import User, UserRole

        probe = sessionmaker(bind=engine)()
        try:
            rows = probe.query(User.id, User.role).order_by(User.id).all()
            if not rows:
                print("No seeded data found — re-run without --skip-seed.", file=sys.stderr)
                return 2
            seed_result = dataset_module.SeedResult(
                profile=profile,
                user_id=next(r.id for r in rows if r.role == UserRole.USER),
                admin_id=next(r.id for r in rows if r.role == UserRole.ADMIN),
                coach_id=next(r.id for r in rows if r.role == UserRole.WELLNESS_COACH),
                row_counts=dataset_module.count_rows(probe),
            )
        finally:
            probe.close()
    else:
        print(
            f"Seeding '{profile.name}' dataset into "
            f"{engine.url.render_as_string(hide_password=True)} ..."
        )
        started = time.perf_counter()
        seed_result = dataset_module.seed(engine, profile)
        print(f"Seeded {seed_result.total_rows():,} rows in {time.perf_counter() - started:.1f}s")

    # Distinct accounts, so no two threads contend on one user's rows.
    from app.models.user import User, UserRole

    probe = sessionmaker(bind=engine)()
    try:
        accounts = [
            (r[0], r[1])
            for r in probe.query(User.id, User.email)
            .filter(User.role == UserRole.USER)
            .order_by(User.id)
            .limit(max(peak, 1))
            .all()
        ]
    finally:
        probe.close()
    if not accounts:
        print("No seeded end users found.", file=sys.stderr)
        return 2

    live_client: Optional[LiveClient] = None
    if args.base_url:
        live_client = LiveClient(args.base_url, peak, args.request_timeout_s)
        print(f"Waiting for {args.base_url} to become healthy ...")
        if not wait_for_server(live_client):
            print(f"Server at {args.base_url} never became healthy.", file=sys.stderr)
            live_client.close()
            return 2
        password = os.getenv("PERF_SEED_PASSWORD", dataset_module.SEED_PASSWORD)
        try:
            tokens = login_tokens(live_client, [email for _, email in accounts], password)
        except RuntimeError as exc:
            print(str(exc), file=sys.stderr)
            live_client.close()
            return 2
        client = live_client
        print(f"Driving {args.base_url} over HTTP with {len(tokens)} logged-in accounts")
    else:
        tokens = [make_token(uid) for uid, _ in accounts]
        client = build_client(
            engine,
            pool_note=(
                f"Pool sized {peak + 5} + {peak} overflow for a peak of {peak} users"
            ),
        )
    if is_sqlite:
        print(
            "NOTE: SQLite serializes at the database level. Treat this run as a "
            "correctness and shape check; run against PostgreSQL for a capacity "
            "number that describes production."
        )

    results: List[LevelResult] = []
    try:
        for level in levels:
            print(f"  ramping to {level} concurrent users ...", flush=True)
            result = run_level(client, tokens, level, args.rounds, args.sla_p95_ms)
            results.append(result)
            print(
                f"    {result.requests} requests · {result.failures} failures · "
                f"{result.throughput_rps} r/s · p95 {result.p95_ms}ms · "
                f"{'PASS' if result.met_sla else 'FAIL'}"
            )
            if not result.met_sla and not args.no_stop_on_fail:
                print("    SLA missed — stopping the ramp.")
                break
    finally:
        if live_client is not None:
            live_client.close()
        else:
            from app.main import app

            app.dependency_overrides.clear()

    passing = [r for r in results if r.met_sla]
    best = passing[-1] if passing else None

    payload = {
        "meta": {
            "label": args.label,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "mode": "live-http" if live_client is not None else "in-process",
            "base_url": args.base_url,
            "dialect": engine.dialect.name,
            "database": engine.url.render_as_string(hide_password=True),
            "dataset_profile": profile.name,
            "row_counts": seed_result.row_counts,
            "total_rows": seed_result.total_rows(),
            "levels_requested": levels,
            "rounds_per_user": args.rounds,
            "sla_p95_ms": args.sla_p95_ms,
            # In live mode the pool that matters belongs to the server process,
            # not to this harness's seeding engine.
            "pool_size": None if live_client is not None else peak + 5,
            "max_overflow": None if live_client is not None else peak,
            "page_load_endpoints": [path for path, _ in PAGE_LOAD],
        },
        "capacity": {
            "concurrent_users": best.concurrency if best else 0,
            "throughput_rps": best.throughput_rps if best else 0.0,
            "p95_ms": best.p95_ms if best else None,
            "limited_by": (
                None
                if best and best.concurrency == levels[-1]
                else "sla_p95" if best else "no_level_met_sla"
            ),
        },
        "levels": [asdict(r) for r in results],
    }

    output_path = Path(args.output) if args.output else DEFAULT_RESULTS_DIR / f"{args.label}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print()
    print(render_markdown(payload))
    print()
    print(f"Results written to {output_path}")

    measured = payload["capacity"]["concurrent_users"]
    if args.require_capacity is not None and measured < args.require_capacity:
        print(
            f"\nCapacity regression: measured {measured} concurrent users, "
            f"required at least {args.require_capacity}.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
