"""Subsystem latency benchmarks: challenge generation, alarm dispatch, reports.

``perf/benchmark.py`` covers the dashboard read APIs. These are the remaining
spec'd performance areas that never travel through a dashboard request:

- **Challenge generation** — sits in the wake-up critical path, so its latency
  is felt directly by a user standing at a ringing alarm.
- **Alarm dispatch / scheduling** — the server-side sweep must drain a full
  batch of armed alarms well inside its scheduler interval, or rings queue up
  behind each other and arrive late.
- **Report generation and export** — PDF / Excel rendering is synchronous and
  blocks a request thread for its whole duration.

Everything runs in-process against a seeded throwaway SQLite database, so the
numbers isolate application + ORM + SQL cost with no HTTP or network noise.

Usage::

    python -m perf.subsystems --label baseline
    python -m perf.subsystems --only challenge_generation --iterations 300
    python -m perf.subsystems --skip-seed        # reuse the existing dataset
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, time as dtime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

DEFAULT_DB_PATH = BACKEND_ROOT / "perf" / ".perfdata" / "subsystems.db"
DEFAULT_RESULTS_DIR = BACKEND_ROOT / "perf" / "results"

# ── Latency budgets (p95, milliseconds) ──────────────────────────────────
# Challenge generation is interactive: it runs while the alarm is ringing.
CHALLENGE_BUDGET_MS = 50.0
# A dispatch sweep must finish far inside ALARM_DISPATCH_INTERVAL_SECONDS (20s)
# or sweeps overlap and rings are delivered late.
DISPATCH_BUDGET_MS = 5000.0
# Report building is a page load; export additionally renders a document.
REPORT_BUDGET_MS = 1500.0
EXPORT_BUDGET_MS = 2000.0

# Alarms available for the dispatch cases. The largest sweep size must fit.
ALARM_POOL = 1200
DISPATCH_SIZES = (200, 500, 1000)


@dataclass
class CaseResult:
    """Latency distribution for one benchmarked operation."""

    key: str
    group: str
    iterations: int
    p50_ms: float
    p95_ms: float
    p99_ms: float
    min_ms: float
    max_ms: float
    mean_ms: float
    budget_ms: float
    over_budget: bool
    detail: Dict[str, Any] = field(default_factory=dict)


def percentile(values: List[float], pct: float) -> float:
    """Nearest-rank percentile; stable for small sample sizes."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, min(len(ordered), int(round(pct / 100.0 * len(ordered)))))
    return ordered[rank - 1]


def measure(
    key: str,
    group: str,
    budget_ms: float,
    run: Callable[[], Any],
    iterations: int,
    *,
    warmup: int = 2,
    setup: Optional[Callable[[], Any]] = None,
    detail: Optional[Dict[str, Any]] = None,
) -> CaseResult:
    """Time ``run`` ``iterations`` times, excluding any ``setup`` from the clock."""
    for _ in range(warmup):
        if setup is not None:
            setup()
        run()

    samples: List[float] = []
    last: Any = None
    for _ in range(iterations):
        if setup is not None:
            setup()
        started = time.perf_counter()
        last = run()
        samples.append((time.perf_counter() - started) * 1000.0)

    merged = dict(detail or {})
    if isinstance(last, dict):
        merged.update({f"last_{k}": v for k, v in last.items()})

    p95 = percentile(samples, 95)
    return CaseResult(
        key=key,
        group=group,
        iterations=iterations,
        p50_ms=round(percentile(samples, 50), 3),
        p95_ms=round(p95, 3),
        p99_ms=round(percentile(samples, 99), 3),
        min_ms=round(min(samples), 3),
        max_ms=round(max(samples), 3),
        mean_ms=round(statistics.fmean(samples), 3),
        budget_ms=budget_ms,
        over_budget=p95 > budget_ms,
        detail=merged,
    )


# ── Group 1: cognitive challenge generation ──────────────────────────────


def bench_challenge_generation(iterations: int) -> List[CaseResult]:
    """Measure puzzle generation for every challenge type and difficulty.

    Difficulties rotate across iterations so each type is sampled at every
    level rather than only at its cheapest one.
    """
    from app.models.alarm import ChallengeType
    from app.services.challenge_service import DIFFICULTY_LEVELS, ChallengeService

    results: List[CaseResult] = []
    for challenge_type in ChallengeType:
        state = {"i": 0}

        def run(ct=challenge_type, state=state):
            difficulty = DIFFICULTY_LEVELS[state["i"] % len(DIFFICULTY_LEVELS)]
            state["i"] += 1
            # current_hour is pinned so time-of-day softening cannot make the
            # measurement depend on when the benchmark happens to run.
            return ChallengeService.generate_challenge(
                ct, difficulty=difficulty, current_hour=7
            )

        results.append(
            measure(
                f"challenge_generate_{challenge_type.value}",
                "challenge_generation",
                CHALLENGE_BUDGET_MS,
                run,
                iterations,
                detail={"difficulties": DIFFICULTY_LEVELS},
            )
        )
    return results


# ── Group 2: alarm dispatch and scheduling at scale ──────────────────────


def _alarm_id_at(session, index: int) -> int:
    """Id of the ``index``-th alarm in id order (used as an arming threshold)."""
    from app.models.alarm import Alarm

    row = (
        session.query(Alarm.id)
        .order_by(Alarm.id)
        .offset(max(0, index - 1))
        .limit(1)
        .first()
    )
    if row is None:
        raise RuntimeError("alarm pool is smaller than the requested sweep size")
    return row[0]


def _ensure_alarm_pool(session, user_ids: List[int], target: int) -> None:
    """Top the alarm table up to ``target`` rows spread across seeded users."""
    from sqlalchemy import func

    from app.models.alarm import Alarm, AlarmType, ChallengeType

    existing = session.query(func.count(Alarm.id)).scalar() or 0
    if existing >= target:
        return

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session.bulk_save_objects(
        [
            Alarm(
                user_id=user_ids[i % len(user_ids)],
                title=f"Dispatch alarm {i}",
                alarm_time=dtime(hour=7, minute=i % 60),
                alarm_type=AlarmType.DAILY,
                days_of_week=[0, 1, 2, 3, 4, 5, 6],
                is_active=True,
                challenge_type=ChallengeType.MATH,
                challenge_count=1,
                challenge_difficulty="medium",
                next_trigger_at=now + timedelta(days=1),
            )
            for i in range(target - existing)
        ]
    )
    session.commit()


def _reset_dispatch_state(session, threshold_id: int, offset: timedelta) -> None:
    """Arm alarms up to ``threshold_id`` at ``now - offset``; disarm the rest.

    Ranged updates keep this free of huge ``IN`` lists, and clearing the queued
    rings keeps every iteration starting from the same state.
    """
    from app.models.alarm import Alarm
    from app.models.notification import Notification, NotificationType

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    session.query(Notification).filter(
        Notification.notification_type == NotificationType.ALARM_TRIGGER
    ).delete(synchronize_session=False)

    session.query(Alarm).filter(Alarm.id > threshold_id).update(
        {Alarm.is_active: False, Alarm.next_trigger_at: None},
        synchronize_session=False,
    )
    session.query(Alarm).filter(Alarm.id <= threshold_id).update(
        {
            Alarm.is_active: True,
            Alarm.next_trigger_at: now - offset,
            Alarm.last_notified_trigger_at: None,
        },
        synchronize_session=False,
    )
    session.commit()


def bench_alarm_dispatch(session, user_ids: List[int], iterations: int) -> List[CaseResult]:
    """Measure ring dispatch and missed-alarm rescheduling at 200+ alarms."""
    from app.core.config import settings
    from app.services.alarm_dispatch_service import AlarmDispatchService

    _ensure_alarm_pool(session, user_ids, ALARM_POOL)

    results: List[CaseResult] = []
    sweep_cap = 200  # AlarmDispatchService._MAX_PER_SWEEP

    for size in DISPATCH_SIZES:
        threshold = _alarm_id_at(session, size)

        # One sweep: what the scheduler actually does every interval.
        results.append(
            measure(
                f"alarm_dispatch_sweep_{size}",
                "alarm_dispatch",
                DISPATCH_BUDGET_MS,
                lambda: AlarmDispatchService.run_once(session),
                iterations,
                setup=lambda t=threshold: _reset_dispatch_state(
                    session, t, timedelta(seconds=30)
                ),
                detail={"armed_alarms": size, "sweep_cap": sweep_cap},
            )
        )

        # Full drain: how long every armed alarm takes to actually be queued,
        # which is the number that decides whether a ring is late.
        def drain(t=threshold):
            sweeps = 0
            dispatched = 0
            while True:
                result = AlarmDispatchService.run_once(session)
                sweeps += 1
                dispatched += result["dispatched"]
                if result["dispatched"] == 0:
                    break
            return {"sweeps": sweeps, "dispatched": dispatched}

        results.append(
            measure(
                f"alarm_dispatch_drain_{size}",
                "alarm_dispatch",
                DISPATCH_BUDGET_MS,
                drain,
                max(3, iterations // 3),
                warmup=1,
                setup=lambda t=threshold: _reset_dispatch_state(
                    session, t, timedelta(seconds=30)
                ),
                detail={"armed_alarms": size, "sweep_cap": sweep_cap},
            )
        )

    # Scheduling path: recomputing next_trigger_at for a batch of alarms that
    # rang unattended. Offset must exceed ALARM_MISSED_ROLLOVER_MINUTES.
    rollover_offset = timedelta(
        minutes=max(5, int(settings.ALARM_MISSED_ROLLOVER_MINUTES or 60)) + 30
    )
    threshold = _alarm_id_at(session, 200)
    results.append(
        measure(
            "alarm_reschedule_missed_200",
            "alarm_dispatch",
            DISPATCH_BUDGET_MS,
            lambda: AlarmDispatchService.run_once(session),
            max(3, iterations // 3),
            warmup=1,
            setup=lambda t=threshold: _reset_dispatch_state(
                session, t, rollover_offset
            ),
            detail={"armed_alarms": 200},
        )
    )
    return results


# ── Group 3: report generation and export ────────────────────────────────


def bench_reports(session, user_id: int, iterations: int) -> List[CaseResult]:
    """Measure user and system report building plus PDF / Excel rendering."""
    from app.services.report_export import export_report
    from app.services.report_service import ReportService, ReportType
    from app.services.system_report_service import (
        SystemReportService,
        SystemReportType,
    )

    results: List[CaseResult] = []

    for report_type in ReportType:
        results.append(
            measure(
                f"report_build_{report_type.value}",
                "reports",
                REPORT_BUDGET_MS,
                lambda rt=report_type: ReportService.build_report(
                    session, user_id, rt, days=30
                ),
                iterations,
            )
        )

    for report_type in SystemReportType:
        results.append(
            measure(
                f"system_report_build_{report_type.value}",
                "reports",
                REPORT_BUDGET_MS,
                lambda rt=report_type: SystemReportService.build_report(
                    session, rt, days=30
                ),
                iterations,
            )
        )

    # Export is measured on a pre-built payload so the timing is rendering
    # only, not rendering plus a rebuild.
    user_payload = ReportService.build_report(
        session, user_id, ReportType.HABIT, days=30
    )
    system_payload = SystemReportService.build_report(
        session, SystemReportType.PLATFORM, days=30
    )

    for fmt in ("pdf", "excel"):
        results.append(
            measure(
                f"report_export_{fmt}",
                "reports",
                EXPORT_BUDGET_MS,
                lambda f=fmt: export_report(user_payload, f),
                iterations,
            )
        )
        results.append(
            measure(
                f"system_report_export_{fmt}",
                "reports",
                EXPORT_BUDGET_MS,
                lambda f=fmt: export_report(system_payload, f),
                iterations,
            )
        )

    return results


# ── Runner ───────────────────────────────────────────────────────────────


def render_markdown(payload: Dict[str, Any]) -> str:
    """Render a human-readable summary of a results payload."""
    meta = payload["meta"]
    lines = [
        f"### Subsystem benchmark: {meta['label']}",
        "",
        f"- Dialect: `{meta['dialect']}` · dataset `{meta['dataset_profile']}` "
        f"· {meta['total_rows']:,} rows",
        "",
        "| Case | Group | Iters | p50 ms | p95 ms | p99 ms | Budget | Over |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in payload["cases"]:
        lines.append(
            f"| `{r['key']}` | {r['group']} | {r['iterations']} | {r['p50_ms']} | "
            f"{r['p95_ms']} | {r['p99_ms']} | {r['budget_ms']} | "
            f"{'YES' if r['over_budget'] else 'no'} |"
        )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="Benchmark ICAP challenge, dispatch and report subsystems."
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("PERF_SUBSYSTEM_DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}"),
        help="SQLAlchemy URL for the benchmark database (never point at production).",
    )
    parser.add_argument("--profile", default="small", choices=["small", "medium", "large"])
    parser.add_argument("--iterations", type=int, default=30)
    parser.add_argument("--skip-seed", action="store_true", help="Reuse the existing dataset.")
    parser.add_argument(
        "--only",
        nargs="*",
        choices=["challenge_generation", "alarm_dispatch", "reports"],
        help="Restrict to specific benchmark groups.",
    )
    parser.add_argument("--label", default="subsystems", help="Label recorded in the results file.")
    parser.add_argument("--output", default=None, help="Path for the JSON results file.")
    args = parser.parse_args(argv)

    os.environ.setdefault("SECRET_KEY", "perf-benchmark-secret-key-not-for-production")

    from sqlalchemy.orm import sessionmaker

    from perf import dataset as dataset_module

    if args.database_url.startswith("sqlite:///"):
        DEFAULT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    engine = dataset_module.make_engine(args.database_url)
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
        print(f"Seeding '{profile.name}' dataset into {engine.url.render_as_string(hide_password=True)} ...")
        started = time.perf_counter()
        seed_result = dataset_module.seed(engine, profile)
        print(f"Seeded {seed_result.total_rows():,} rows in {time.perf_counter() - started:.1f}s")

    session = sessionmaker(bind=engine, autocommit=False, autoflush=False)()
    groups = set(args.only) if args.only else {
        "challenge_generation",
        "alarm_dispatch",
        "reports",
    }

    cases: List[CaseResult] = []
    try:
        if "challenge_generation" in groups:
            print("  benchmarking challenge generation ...")
            cases += bench_challenge_generation(max(args.iterations, 50))
        if "alarm_dispatch" in groups:
            print("  benchmarking alarm dispatch ...")
            from app.models.user import User

            user_ids = [r[0] for r in session.query(User.id).order_by(User.id).all()]
            cases += bench_alarm_dispatch(session, user_ids, args.iterations)
        if "reports" in groups:
            print("  benchmarking report generation ...")
            cases += bench_reports(session, seed_result.user_id, args.iterations)
    finally:
        session.close()

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
        },
        "cases": [asdict(c) for c in cases],
    }

    output_path = Path(args.output) if args.output else DEFAULT_RESULTS_DIR / f"{args.label}.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print()
    print(render_markdown(payload))
    print()
    print(f"Results written to {output_path}")

    over = [c for c in cases if c.over_budget]
    if over:
        print(f"\n{len(over)} case(s) exceeded their p95 budget:", file=sys.stderr)
        for c in over:
            print(f"  {c.key} -> {c.p95_ms}ms (budget {c.budget_ms}ms)", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
