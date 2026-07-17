"""
Attempt-log write path, normalization, audit, and repair.

Week 2 logging must stay clean and queryable for adaptive difficulty,
habit scoring, and recommendations. Challenge attempts go through
``record_attempt``; snoozes go through ``record_snooze``.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models.alarm import Alarm, AlarmChallengeLog, ChallengeType
from app.models.alarm_snooze_event import AlarmSnoozeEvent
from app.models.alarm_wake_event import AlarmWakeEvent
from app.models.user import User
from app.services.analytics_ingestion_service import AnalyticsIngestionService
from app.services.challenge_service import DIFFICULTY_LEVELS, _clamp_difficulty

# Canonical types stored in alarm_challenge_logs.challenge_type
VALID_CHALLENGE_TYPES = frozenset(
    {
        ChallengeType.MATH.value,
        ChallengeType.LOGIC.value,
        ChallengeType.MEMORY.value,
        ChallengeType.WORD_GAME.value,
        ChallengeType.PATTERN.value,
        ChallengeType.RIDDLE.value,
        ChallengeType.QUIZ.value,
        ChallengeType.RANDOM.value,
    }
)

# Frontend / legacy aliases → canonical value
_CHALLENGE_TYPE_ALIASES = {
    "word": ChallengeType.WORD_GAME.value,
    ChallengeType.WORD.value: ChallengeType.WORD_GAME.value,
}

# Near-identical challenge attempts within this window are flagged as duplicates
DUPLICATE_WINDOW_SECONDS = 2


class AttemptLogService:
    """Single source of truth for challenge attempt + snooze logging/audit."""

    # ── Normalization ──────────────────────────────────────────────

    @staticmethod
    def normalize_challenge_type(raw: Optional[str]) -> str:
        """Return a canonical lowercase challenge type."""
        value = (raw or "").strip().lower()
        if not value:
            return ChallengeType.MATH.value
        value = _CHALLENGE_TYPE_ALIASES.get(value, value)
        if value in VALID_CHALLENGE_TYPES:
            return value
        try:
            return AttemptLogService.normalize_challenge_type(
                ChallengeType[value.upper()].value
            )
        except KeyError:
            return ChallengeType.MATH.value

    @staticmethod
    def normalize_difficulty(raw: Optional[str]) -> str:
        """Return a valid difficulty level (defaults to medium)."""
        return _clamp_difficulty(raw)

    @staticmethod
    def normalize_non_negative(value: Optional[int], default: int = 0) -> int:
        """Clamp integers used in logs to >= 0."""
        try:
            return max(0, int(value if value is not None else default))
        except (TypeError, ValueError):
            return default

    # ── Write paths ────────────────────────────────────────────────

    @staticmethod
    def record_attempt(
        db: Session,
        *,
        alarm_id: int,
        user_id: int,
        challenge_type: str,
        difficulty: str,
        challenge_prompt: Optional[str],
        is_correct: bool,
        time_taken_seconds: int = 0,
        failed_attempts: int = 0,
        points_earned: int = 0,
        commit: bool = True,
    ) -> AlarmChallengeLog:
        """Persist one attempt with normalized, analytics-safe fields."""
        log = AlarmChallengeLog(
            alarm_id=alarm_id,
            user_id=user_id,
            challenge_type=AttemptLogService.normalize_challenge_type(
                challenge_type
            ),
            difficulty=AttemptLogService.normalize_difficulty(difficulty),
            challenge_prompt=(challenge_prompt or "").strip(),
            is_correct=bool(is_correct),
            time_taken_seconds=AttemptLogService.normalize_non_negative(
                time_taken_seconds
            ),
            failed_attempts=AttemptLogService.normalize_non_negative(
                failed_attempts
            ),
            points_earned=AttemptLogService.normalize_non_negative(points_earned),
            created_at=datetime.now(timezone.utc),
        )
        db.add(log)
        db.flush()
        # Additive analytics fan-out — domain attempt log remains SSOT.
        AnalyticsIngestionService.emit_challenge_attempted(
            db,
            user_id=user_id,
            alarm_id=alarm_id,
            challenge_log_id=log.id,
            challenge_type=log.challenge_type,
            difficulty=log.difficulty,
            is_correct=log.is_correct,
            time_taken_seconds=log.time_taken_seconds,
            points_earned=log.points_earned,
            commit=False,
        )
        if commit:
            db.commit()
            db.refresh(log)
        from app.services.recommendation_cache import RecommendationCache

        RecommendationCache.invalidate_user(user_id)
        return log

    @staticmethod
    def record_snooze(
        db: Session,
        *,
        alarm_id: int,
        user_id: int,
        snooze_number: int,
        snooze_limit_at_event: int,
        next_trigger_at: Optional[datetime] = None,
        commit: bool = True,
    ) -> AlarmSnoozeEvent:
        """Persist one snooze action for analytics / audit."""
        event = AlarmSnoozeEvent(
            alarm_id=alarm_id,
            user_id=user_id,
            snooze_number=AttemptLogService.normalize_non_negative(
                snooze_number, default=1
            )
            or 1,
            snooze_limit_at_event=AttemptLogService.normalize_non_negative(
                snooze_limit_at_event
            ),
            next_trigger_at=next_trigger_at,
            created_at=datetime.now(timezone.utc),
        )
        db.add(event)
        db.flush()
        # Additive analytics fan-out — snooze audit table remains SSOT.
        AnalyticsIngestionService.emit_alarm_snoozed(
            db,
            user_id=user_id,
            alarm_id=alarm_id,
            snooze_event_id=event.id,
            snooze_number=event.snooze_number,
            snooze_limit=event.snooze_limit_at_event,
            next_trigger_at=event.next_trigger_at,
            commit=False,
        )
        if commit:
            db.commit()
            db.refresh(event)
        from app.services.recommendation_cache import RecommendationCache

        RecommendationCache.invalidate_user(user_id)
        return event

    # ── Audit helpers ──────────────────────────────────────────────

    @staticmethod
    def _add_issue(
        issue_counts: Dict[str, int],
        issue_rows: List[Dict[str, Any]],
        sample_limit: int,
        issue: Dict[str, Any],
    ) -> None:
        code = issue["code"]
        issue_counts[code] = issue_counts.get(code, 0) + 1
        if len(issue_rows) < sample_limit:
            issue_rows.append(issue)

    @staticmethod
    def _aware(dt: Optional[datetime]) -> Optional[datetime]:
        if dt is None:
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _row_issues(log: AlarmChallengeLog) -> List[Dict[str, Any]]:
        """Return issue descriptors for a single challenge-log row."""
        issues: List[Dict[str, Any]] = []
        base = {"table": "alarm_challenge_logs", "log_id": log.id,
                "alarm_id": log.alarm_id, "user_id": log.user_id}

        if not log.challenge_type or not str(log.challenge_type).strip():
            issues.append({**base, "code": "missing_challenge_type"})
        else:
            normalized = AttemptLogService.normalize_challenge_type(
                log.challenge_type
            )
            raw = str(log.challenge_type).strip().lower()
            if raw == "word" or raw not in VALID_CHALLENGE_TYPES:
                issues.append(
                    {
                        **base,
                        "code": "invalid_challenge_type",
                        "value": log.challenge_type,
                        "suggested": normalized,
                    }
                )

        if not log.difficulty or not str(log.difficulty).strip():
            issues.append({**base, "code": "missing_difficulty"})
        elif str(log.difficulty).strip().lower() not in DIFFICULTY_LEVELS:
            issues.append(
                {
                    **base,
                    "code": "invalid_difficulty",
                    "value": log.difficulty,
                    "suggested": AttemptLogService.normalize_difficulty(
                        log.difficulty
                    ),
                }
            )

        if log.challenge_prompt is None:
            issues.append({**base, "code": "null_challenge_prompt"})

        if log.is_correct is None:
            issues.append({**base, "code": "null_is_correct"})

        if log.time_taken_seconds is None or log.time_taken_seconds < 0:
            issues.append(
                {
                    **base,
                    "code": "invalid_time_taken",
                    "value": log.time_taken_seconds,
                }
            )

        if log.failed_attempts is None or log.failed_attempts < 0:
            issues.append(
                {
                    **base,
                    "code": "invalid_failed_attempts",
                    "value": log.failed_attempts,
                }
            )

        if log.points_earned is None or log.points_earned < 0:
            issues.append(
                {
                    **base,
                    "code": "invalid_points_earned",
                    "value": log.points_earned,
                }
            )

        if log.created_at is None:
            issues.append({**base, "code": "missing_created_at"})

        return issues

    @staticmethod
    def _detect_duplicate_attempts(
        logs: Sequence[AlarmChallengeLog],
    ) -> List[Dict[str, Any]]:
        """Flag near-identical attempt rows within DUPLICATE_WINDOW_SECONDS."""
        by_key: Dict[Tuple[Any, ...], List[AlarmChallengeLog]] = defaultdict(list)
        for log in logs:
            key = (
                log.user_id,
                log.alarm_id,
                (log.challenge_type or "").lower(),
                log.challenge_prompt or "",
                bool(log.is_correct),
                int(log.time_taken_seconds or 0),
            )
            by_key[key].append(log)

        issues: List[Dict[str, Any]] = []
        window = timedelta(seconds=DUPLICATE_WINDOW_SECONDS)
        for group in by_key.values():
            if len(group) < 2:
                continue
            ordered = sorted(
                group,
                key=lambda row: AttemptLogService._aware(row.created_at)
                or datetime.min.replace(tzinfo=timezone.utc),
            )
            for i in range(1, len(ordered)):
                prev = AttemptLogService._aware(ordered[i - 1].created_at)
                curr = AttemptLogService._aware(ordered[i].created_at)
                if prev is None or curr is None:
                    continue
                if abs((curr - prev).total_seconds()) <= window.total_seconds():
                    issues.append(
                        {
                            "table": "alarm_challenge_logs",
                            "code": "duplicate_attempt",
                            "log_id": ordered[i].id,
                            "duplicate_of": ordered[i - 1].id,
                            "alarm_id": ordered[i].alarm_id,
                            "user_id": ordered[i].user_id,
                        }
                    )
        return issues

    @staticmethod
    def _detect_duplicate_snoozes(
        events: Sequence[AlarmSnoozeEvent],
    ) -> List[Dict[str, Any]]:
        """Flag repeated snooze rows for the same alarm within a short window."""
        by_alarm: Dict[Tuple[int, int], List[AlarmSnoozeEvent]] = defaultdict(list)
        for event in events:
            by_alarm[(event.user_id, event.alarm_id)].append(event)

        issues: List[Dict[str, Any]] = []
        window = timedelta(seconds=DUPLICATE_WINDOW_SECONDS)
        for group in by_alarm.values():
            if len(group) < 2:
                continue
            ordered = sorted(
                group,
                key=lambda row: AttemptLogService._aware(row.created_at)
                or datetime.min.replace(tzinfo=timezone.utc),
            )
            for i in range(1, len(ordered)):
                prev = AttemptLogService._aware(ordered[i - 1].created_at)
                curr = AttemptLogService._aware(ordered[i].created_at)
                if prev is None or curr is None:
                    continue
                same_number = ordered[i].snooze_number == ordered[i - 1].snooze_number
                if (
                    same_number
                    and abs((curr - prev).total_seconds()) <= window.total_seconds()
                ):
                    issues.append(
                        {
                            "table": "alarm_snooze_events",
                            "code": "duplicate_snooze",
                            "log_id": ordered[i].id,
                            "duplicate_of": ordered[i - 1].id,
                            "alarm_id": ordered[i].alarm_id,
                            "user_id": ordered[i].user_id,
                        }
                    )
        return issues

    @staticmethod
    def audit_logs(
        db: Session,
        *,
        user_id: Optional[int] = None,
        sample_limit: int = 25,
    ) -> Dict[str, Any]:
        """
        Verify attempt / snooze / wake log cleanliness and queryability.

        Checks:
            - Required fields present and valid
            - Types/difficulties in allowed sets
            - Non-negative numeric fields
            - Orphan rows (missing alarm or user)
            - User/alarm ownership mismatches
            - Near-duplicate attempts and snoozes
            - Wake-event consistency
            - Query paths used by analytics
        """
        attempt_q = db.query(AlarmChallengeLog)
        snooze_q = db.query(AlarmSnoozeEvent)
        wake_q = db.query(AlarmWakeEvent)
        if user_id is not None:
            attempt_q = attempt_q.filter(AlarmChallengeLog.user_id == user_id)
            snooze_q = snooze_q.filter(AlarmSnoozeEvent.user_id == user_id)
            wake_q = wake_q.filter(AlarmWakeEvent.user_id == user_id)

        logs: Sequence[AlarmChallengeLog] = (
            attempt_q.order_by(AlarmChallengeLog.created_at.desc()).all()
        )
        snoozes: Sequence[AlarmSnoozeEvent] = (
            snooze_q.order_by(AlarmSnoozeEvent.created_at.desc()).all()
        )
        wakes: Sequence[AlarmWakeEvent] = (
            wake_q.order_by(AlarmWakeEvent.dismissed_at.desc()).all()
        )

        issue_rows: List[Dict[str, Any]] = []
        issue_counts: Dict[str, int] = {}

        for log in logs:
            for issue in AttemptLogService._row_issues(log):
                AttemptLogService._add_issue(
                    issue_counts, issue_rows, sample_limit, issue
                )

        # Load parent maps for orphan / ownership checks
        alarm_ids = (
            {log.alarm_id for log in logs}
            | {s.alarm_id for s in snoozes}
            | {w.alarm_id for w in wakes}
        )
        user_ids = (
            {log.user_id for log in logs}
            | {s.user_id for s in snoozes}
            | {w.user_id for w in wakes}
        )
        alarms_by_id: Dict[int, Alarm] = {}
        if alarm_ids:
            alarms_by_id = {
                a.id: a
                for a in db.query(Alarm).filter(Alarm.id.in_(alarm_ids)).all()
            }
        existing_user_ids = set()
        if user_ids:
            existing_user_ids = {
                row[0]
                for row in db.query(User.id).filter(User.id.in_(user_ids)).all()
            }

        for log in logs:
            if log.alarm_id not in alarms_by_id:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {
                        "table": "alarm_challenge_logs",
                        "code": "orphan_alarm_id",
                        "log_id": log.id,
                        "alarm_id": log.alarm_id,
                    },
                )
            elif alarms_by_id[log.alarm_id].user_id != log.user_id:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {
                        "table": "alarm_challenge_logs",
                        "code": "inconsistent_user_alarm_owner",
                        "log_id": log.id,
                        "alarm_id": log.alarm_id,
                        "user_id": log.user_id,
                        "alarm_owner_id": alarms_by_id[log.alarm_id].user_id,
                    },
                )
            if log.user_id not in existing_user_ids:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {
                        "table": "alarm_challenge_logs",
                        "code": "orphan_user_id",
                        "log_id": log.id,
                        "user_id": log.user_id,
                    },
                )

        for event in snoozes:
            base = {
                "table": "alarm_snooze_events",
                "log_id": event.id,
                "alarm_id": event.alarm_id,
                "user_id": event.user_id,
            }
            if event.snooze_number is None or event.snooze_number < 1:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {**base, "code": "invalid_snooze_number",
                     "value": event.snooze_number},
                )
            if event.snooze_limit_at_event is None or event.snooze_limit_at_event < 0:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {**base, "code": "invalid_snooze_limit",
                     "value": event.snooze_limit_at_event},
                )
            if event.created_at is None:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {**base, "code": "missing_created_at"},
                )
            if event.alarm_id not in alarms_by_id:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {**base, "code": "orphan_alarm_id"},
                )
            elif alarms_by_id[event.alarm_id].user_id != event.user_id:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {
                        **base,
                        "code": "inconsistent_user_alarm_owner",
                        "alarm_owner_id": alarms_by_id[event.alarm_id].user_id,
                    },
                )
            if event.user_id not in existing_user_ids:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {**base, "code": "orphan_user_id"},
                )

        for wake in wakes:
            base = {
                "table": "alarm_wake_events",
                "log_id": wake.id,
                "alarm_id": wake.alarm_id,
                "user_id": wake.user_id,
            }
            if wake.snooze_count_at_dismiss is None or wake.snooze_count_at_dismiss < 0:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {**base, "code": "invalid_snooze_count_at_dismiss",
                     "value": wake.snooze_count_at_dismiss},
                )
            if wake.verified and wake.dismissed_at is None:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {**base, "code": "inconsistent_verified_without_dismiss"},
                )
            if wake.alarm_id not in alarms_by_id:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {**base, "code": "orphan_alarm_id"},
                )
            elif alarms_by_id[wake.alarm_id].user_id != wake.user_id:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {
                        **base,
                        "code": "inconsistent_user_alarm_owner",
                        "alarm_owner_id": alarms_by_id[wake.alarm_id].user_id,
                    },
                )
            if wake.user_id not in existing_user_ids:
                AttemptLogService._add_issue(
                    issue_counts,
                    issue_rows,
                    sample_limit,
                    {**base, "code": "orphan_user_id"},
                )

        for issue in AttemptLogService._detect_duplicate_attempts(logs):
            AttemptLogService._add_issue(
                issue_counts, issue_rows, sample_limit, issue
            )
        for issue in AttemptLogService._detect_duplicate_snoozes(snoozes):
            AttemptLogService._add_issue(
                issue_counts, issue_rows, sample_limit, issue
            )

        # Queryability smoke checks
        queryable = True
        query_error = None
        try:
            smoke = db.query(AlarmChallengeLog)
            if user_id is not None:
                smoke = smoke.filter(AlarmChallengeLog.user_id == user_id)
            _ = (
                smoke.order_by(AlarmChallengeLog.created_at.desc())
                .limit(20)
                .all()
            )
            snooze_smoke = db.query(AlarmSnoozeEvent)
            if user_id is not None:
                snooze_smoke = snooze_smoke.filter(
                    AlarmSnoozeEvent.user_id == user_id
                )
            _ = (
                snooze_smoke.order_by(AlarmSnoozeEvent.created_at.desc())
                .limit(20)
                .all()
            )
            if user_id is not None:
                _ = (
                    db.query(AlarmChallengeLog)
                    .filter(AlarmChallengeLog.user_id == user_id)
                    .filter(AlarmChallengeLog.is_correct.is_(True))
                    .count()
                )
        except Exception as exc:  # pragma: no cover - defensive
            queryable = False
            query_error = str(exc)

        correct = sum(1 for log in logs if log.is_correct)
        incorrect = len(logs) - correct
        is_clean = queryable and sum(issue_counts.values()) == 0

        return {
            "is_clean": is_clean,
            "queryable": queryable,
            "query_error": query_error,
            "total_attempts": len(logs),
            "correct_attempts": correct,
            "incorrect_attempts": incorrect,
            "total_snoozes": len(snoozes),
            "total_dismisses": len(wakes),
            "issue_count": sum(issue_counts.values()),
            "issue_counts": issue_counts,
            "sample_issues": issue_rows,
            "valid_challenge_types": sorted(VALID_CHALLENGE_TYPES),
            "valid_difficulties": list(DIFFICULTY_LEVELS),
            "duplicate_window_seconds": DUPLICATE_WINDOW_SECONDS,
        }

    @staticmethod
    def repair_logs(
        db: Session,
        *,
        user_id: Optional[int] = None,
        commit: bool = True,
    ) -> Dict[str, Any]:
        """
        Backfill / normalize dirty attempt-log rows in place.

        Does **not** delete duplicates or any historical rows.
        """
        query = db.query(AlarmChallengeLog)
        if user_id is not None:
            query = query.filter(AlarmChallengeLog.user_id == user_id)

        repaired = 0
        for log in query.all():
            changed = False

            new_type = AttemptLogService.normalize_challenge_type(
                log.challenge_type
            )
            if log.challenge_type != new_type:
                log.challenge_type = new_type
                changed = True

            new_diff = AttemptLogService.normalize_difficulty(log.difficulty)
            if not log.difficulty or log.difficulty != new_diff:
                log.difficulty = new_diff
                changed = True

            if log.challenge_prompt is None:
                log.challenge_prompt = ""
                changed = True

            if log.is_correct is None:
                log.is_correct = False
                changed = True

            for attr in ("time_taken_seconds", "failed_attempts", "points_earned"):
                current = getattr(log, attr)
                fixed = AttemptLogService.normalize_non_negative(current)
                if current != fixed:
                    setattr(log, attr, fixed)
                    changed = True

            if log.created_at is None:
                log.created_at = datetime.now(timezone.utc)
                changed = True

            if changed:
                repaired += 1

        snooze_q = db.query(AlarmSnoozeEvent)
        if user_id is not None:
            snooze_q = snooze_q.filter(AlarmSnoozeEvent.user_id == user_id)
        snooze_repaired = 0
        for event in snooze_q.all():
            changed = False
            fixed_number = AttemptLogService.normalize_non_negative(
                event.snooze_number, default=1
            ) or 1
            if event.snooze_number != fixed_number:
                event.snooze_number = fixed_number
                changed = True
            fixed_limit = AttemptLogService.normalize_non_negative(
                event.snooze_limit_at_event
            )
            if event.snooze_limit_at_event != fixed_limit:
                event.snooze_limit_at_event = fixed_limit
                changed = True
            if event.created_at is None:
                event.created_at = datetime.now(timezone.utc)
                changed = True
            if changed:
                snooze_repaired += 1

        if commit:
            db.commit()

        return {
            "repaired_rows": repaired,
            "repaired_snooze_rows": snooze_repaired,
        }
