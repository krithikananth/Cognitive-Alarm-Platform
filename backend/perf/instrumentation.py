"""SQLAlchemy statement recording and query-plan capture.

Attaches ``before_cursor_execute`` / ``after_cursor_execute`` listeners to an
engine so every statement issued while serving a request is captured with its
wall-clock execute time. Aggregation is by normalized statement fingerprint,
which is what makes N+1 patterns visible (same fingerprint, high call count).

Timing caveat: these hooks bracket ``cursor.execute`` only. On PostgreSQL that
covers the server-side scan; on SQLite the work happens lazily during fetch, so
it lands in the caller's wall-clock time instead. The benchmark therefore
reports both SQL execute time and the remaining application time.
"""

from __future__ import annotations

import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Tuple

from sqlalchemy import event
from sqlalchemy.engine import Engine

_WHITESPACE = re.compile(r"\s+")


def fingerprint(statement: str) -> str:
    """Normalize whitespace so structurally identical queries group together."""
    return _WHITESPACE.sub(" ", statement).strip()


@dataclass
class StatementStat:
    """Aggregated timing for one statement fingerprint."""

    sql: str
    calls: int = 0
    total_ms: float = 0.0
    max_ms: float = 0.0
    raw_sql: str = ""
    raw_params: Any = None

    @property
    def avg_ms(self) -> float:
        return self.total_ms / self.calls if self.calls else 0.0


@dataclass
class QueryRecorder:
    """Collects statement statistics for an engine between start/stop calls."""

    engine: Engine
    enabled: bool = False
    stats: Dict[str, StatementStat] = field(default_factory=dict)
    _stack: List[float] = field(default_factory=list)
    _installed: bool = False

    def install(self) -> None:
        if self._installed:
            return
        event.listen(self.engine, "before_cursor_execute", self._before)
        event.listen(self.engine, "after_cursor_execute", self._after)
        self._installed = True

    def remove(self) -> None:
        if not self._installed:
            return
        event.remove(self.engine, "before_cursor_execute", self._before)
        event.remove(self.engine, "after_cursor_execute", self._after)
        self._installed = False

    def reset(self) -> None:
        self.stats = {}
        self._stack = []

    def _before(self, conn, cursor, statement, parameters, context, executemany):
        if self.enabled:
            self._stack.append(time.perf_counter())

    def _after(self, conn, cursor, statement, parameters, context, executemany):
        if not self.enabled or not self._stack:
            return
        elapsed_ms = (time.perf_counter() - self._stack.pop()) * 1000.0
        key = fingerprint(statement)
        stat = self.stats.get(key)
        if stat is None:
            stat = StatementStat(
                sql=key,
                raw_sql=statement,
                raw_params=None if executemany else parameters,
            )
            self.stats[key] = stat
        stat.calls += 1
        stat.total_ms += elapsed_ms
        stat.max_ms = max(stat.max_ms, elapsed_ms)

    @contextmanager
    def capture(self) -> Iterator["QueryRecorder"]:
        """Record statements issued inside the block, isolated from prior runs."""
        self.install()
        self.reset()
        self.enabled = True
        try:
            yield self
        finally:
            self.enabled = False

    def totals(self) -> Tuple[int, float]:
        """Return ``(query_count, total_sql_execute_ms)`` across all fingerprints."""
        calls = sum(s.calls for s in self.stats.values())
        total = sum(s.total_ms for s in self.stats.values())
        return calls, total

    def slowest(self, limit: int = 10) -> List[StatementStat]:
        """Statements ranked by total time contributed, then by call count."""
        return sorted(
            self.stats.values(),
            key=lambda s: (s.total_ms, s.calls),
            reverse=True,
        )[:limit]


def explain(engine: Engine, stat: StatementStat) -> List[str]:
    """Return the query plan for a recorded statement.

    PostgreSQL uses ``EXPLAIN (ANALYZE, BUFFERS)``; SQLite uses
    ``EXPLAIN QUERY PLAN``. The statement is replayed through the raw DBAPI
    with its originally recorded parameters, so no bind values are invented.
    """
    dialect = engine.dialect.name
    if dialect == "postgresql":
        prefix = "EXPLAIN (ANALYZE, BUFFERS, COSTS, TIMING) "
    elif dialect == "sqlite":
        prefix = "EXPLAIN QUERY PLAN "
    else:
        return [f"EXPLAIN unsupported for dialect '{dialect}'"]

    if stat.raw_params is None:
        return ["EXPLAIN skipped: parameters were not recorded (executemany)"]

    try:
        with engine.connect() as conn:
            rows = conn.exec_driver_sql(
                prefix + stat.raw_sql, stat.raw_params
            ).fetchall()
        return [" | ".join(str(v) for v in row) for row in rows]
    except Exception as exc:  # noqa: BLE001 - plan capture is best-effort
        return [f"EXPLAIN failed: {type(exc).__name__}: {exc}"]


def scans_without_index(plan_lines: List[str]) -> Optional[bool]:
    """Best-effort detection of a full-table scan in a captured plan.

    Returns ``None`` when the plan could not be captured.
    """
    joined = " ".join(plan_lines).upper()
    if "EXPLAIN FAILED" in joined or "EXPLAIN SKIPPED" in joined:
        return None
    if "SEQ SCAN" in joined:
        return True
    if "SCAN " in joined:
        return "USING INDEX" not in joined and "USING COVERING INDEX" not in joined
    return False
