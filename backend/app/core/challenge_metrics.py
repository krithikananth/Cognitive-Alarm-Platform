"""
Runtime measurement of cognitive challenge generation.

``perf/subsystems.py`` already times ``ChallengeService.generate_challenge``
offline against a synthetic dataset, but nothing observed it in a running
process: a regression — a bank that grew past the anti-repeat window, an AI
provider that started blocking — only showed up as slower alarms.

This registry files every generation call into a bounded in-process reservoir
keyed by ``challenge type / difficulty / source``, so the AI path and the
procedural path are never averaged together. Percentiles are computed with the
same helper the request-latency registry uses, which in turn matches
``perf/benchmark.py``, so runtime, benchmark, and load-test numbers are
directly comparable.

Like the request reservoir this is per-process and deliberately not persisted:
it answers "how fast is this worker generating challenges right now".
"""

from __future__ import annotations

import time
from collections import deque
from threading import Lock
from typing import Any, Deque, Dict, List, Optional

from app.core.request_metrics import distribution

#: Reported when a call failed before it could resolve a concrete type.
UNKNOWN = "unknown"


class _GenerationSamples:
    """Recent durations for one generation key, plus counters that never roll off."""

    __slots__ = ("durations", "calls", "failures")

    def __init__(self, sample_size: int) -> None:
        self.durations: Deque[float] = deque(maxlen=sample_size)
        self.calls = 0
        self.failures = 0


class ChallengeGenerationRegistry:
    """Bounded, thread-safe reservoir of generation durations."""

    def __init__(self, sample_size: int = 500) -> None:
        self._sample_size = max(1, int(sample_size))
        self._lock = Lock()
        self._keys: Dict[str, _GenerationSamples] = {}

    @staticmethod
    def key_for(challenge_type: str, difficulty: str, source: str) -> str:
        return f"{challenge_type or UNKNOWN}/{difficulty or UNKNOWN}/{source or UNKNOWN}"

    def record(
        self,
        *,
        challenge_type: str,
        difficulty: str,
        source: str,
        duration_ms: float,
        failed: bool = False,
    ) -> None:
        key = self.key_for(challenge_type, difficulty, source)
        with self._lock:
            entry = self._keys.get(key)
            if entry is None:
                entry = _GenerationSamples(self._sample_size)
                self._keys[key] = entry
            entry.durations.append(float(duration_ms))
            entry.calls += 1
            if failed:
                entry.failures += 1

    def reset(self) -> None:
        with self._lock:
            self._keys.clear()

    def configure(self, sample_size: int) -> None:
        """Resize in place — rebinding would strand modules that imported it."""
        with self._lock:
            self._sample_size = max(1, int(sample_size))
            self._keys.clear()

    def durations_for(
        self, challenge_type: str, difficulty: str, source: str
    ) -> List[float]:
        with self._lock:
            entry = self._keys.get(self.key_for(challenge_type, difficulty, source))
            return list(entry.durations) if entry else []

    def all_durations(self) -> List[float]:
        with self._lock:
            return [d for entry in self._keys.values() for d in entry.durations]

    def snapshot(self, *, top: Optional[int] = None) -> Dict[str, Any]:
        """Per-key generation latency plus a whole-process rollup."""
        with self._lock:
            items = [
                (key, list(e.durations), e.calls, e.failures)
                for key, e in self._keys.items()
            ]

        keys = [
            {
                "key": key,
                "challenge_type": key.split("/")[0],
                "difficulty": key.split("/")[1],
                "source": key.split("/")[2],
                "calls": calls,
                "failures": failures,
                **distribution(durations),
            }
            for key, durations, calls, failures in items
            if durations
        ]
        keys.sort(key=lambda k: k["p95_ms"], reverse=True)

        every_duration = [d for _, durations, _, _ in items for d in durations]
        return {
            "sample_size": self._sample_size,
            "keys_tracked": len(keys),
            "total_generations": sum(k["calls"] for k in keys),
            "total_failures": sum(k["failures"] for k in keys),
            "overall": distribution(every_duration),
            "by_key": keys[:top] if top else keys,
        }


#: Process-wide registry ChallengeService writes to and /system/metrics reads.
challenge_generation = ChallengeGenerationRegistry()


def configure_registry(sample_size: int) -> None:
    """Resize the reservoir at startup, dropping anything already collected."""
    challenge_generation.configure(sample_size)


class measure_generation:
    """Context manager timing one generation call.

    The resolved type, difficulty and source are only known once generation
    finishes, so they are supplied on exit via :meth:`describe`. A call that
    raises is still recorded, flagged as a failure, so a provider that times
    out shows up as latency rather than disappearing.
    """

    __slots__ = ("_enabled", "_started", "challenge_type", "difficulty", "source")

    def __init__(self, *, enabled: bool = True) -> None:
        self._enabled = enabled
        self._started = 0.0
        self.challenge_type = UNKNOWN
        self.difficulty = UNKNOWN
        self.source = UNKNOWN

    def describe(self, challenge_type: Any, difficulty: Any, source: Any) -> None:
        self.challenge_type = str(challenge_type or UNKNOWN).lower()
        self.difficulty = str(difficulty or UNKNOWN).lower()
        self.source = str(source or UNKNOWN).lower()

    def __enter__(self) -> "measure_generation":
        self._started = time.perf_counter()
        return self

    def __exit__(self, exc_type, exc, tb) -> bool:
        if self._enabled:
            challenge_generation.record(
                challenge_type=self.challenge_type,
                difficulty=self.difficulty,
                source=self.source,
                duration_ms=(time.perf_counter() - self._started) * 1000.0,
                failed=exc_type is not None,
            )
        return False
