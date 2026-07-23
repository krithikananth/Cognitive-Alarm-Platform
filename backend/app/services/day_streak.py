"""
Calendar-day wake streak (Day Streak).

Day Streak counts consecutive local calendar days with at least one
successful wake — i.e. a verified challenge completion that dismissed the
alarm. Rules:

- Update ONLY after the final wake outcome (never on ring or snooze).
- Successful challenge completion may increment at most once per local day.
- Multiple alarms the same day never increase the streak more than once.
- A gap of one or more missed days resets the live streak to 0; the next
  successful day starts at 1.
- Intermediate wrong answers / challenge timeouts are not final day outcomes
  and must not mutate Day Streak.
- All Dashboard, Analytics, Habit Score, and API surfaces must read the
  stored ``UserProfile.streak_days`` (after optional missed-day decay).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Any, Iterable, Literal, Mapping, Optional, Sequence, Union
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.orm import Session

from app.models.profile import UserProfile

WakeOutcome = Literal["success", "failure"]


@dataclass(frozen=True)
class DayStreakState:
    """Immutable snapshot of streak counters after an update."""

    streak_days: int
    best_streak: int
    last_successful_wake_date: Optional[date]
    changed: bool = False
    outcome_applied: Optional[WakeOutcome] = None


def resolve_timezone(tz_name: Optional[str]) -> ZoneInfo:
    """Return a ZoneInfo, falling back to UTC on unknown names."""
    try:
        return ZoneInfo(tz_name or "UTC")
    except ZoneInfoNotFoundError:
        return ZoneInfo("UTC")


def local_calendar_date(
    moment: Optional[datetime],
    tz_name: Optional[str] = "UTC",
) -> Optional[date]:
    """Convert a UTC (or naive-UTC) timestamp to the user's local calendar date."""
    if moment is None:
        return None
    tz = resolve_timezone(tz_name)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(tz).date()


def today_in_timezone(tz_name: Optional[str] = "UTC") -> date:
    """Current calendar date in the given IANA timezone."""
    return datetime.now(timezone.utc).astimezone(resolve_timezone(tz_name)).date()


def apply_successful_wake(
    *,
    streak_days: int,
    best_streak: int,
    last_successful_wake_date: Optional[date],
    wake_date: date,
) -> DayStreakState:
    """Apply one successful wake on ``wake_date`` to streak counters.

    Same-day repeats leave the streak unchanged. Consecutive next-day wakes
    increment. Any gap resets and starts a new streak at 1.
    """
    current = max(0, int(streak_days or 0))
    best = max(0, int(best_streak or 0))

    if last_successful_wake_date is not None and wake_date == last_successful_wake_date:
        return DayStreakState(
            streak_days=current,
            best_streak=best,
            last_successful_wake_date=last_successful_wake_date,
            changed=False,
            outcome_applied=None,
        )

    if (
        last_successful_wake_date is not None
        and wake_date == last_successful_wake_date + timedelta(days=1)
    ):
        new_streak = current + 1
    else:
        # First success ever, or a gap after a missed day.
        new_streak = 1

    new_best = max(best, new_streak)
    return DayStreakState(
        streak_days=new_streak,
        best_streak=new_best,
        last_successful_wake_date=wake_date,
        changed=True,
        outcome_applied="success",
    )


def apply_failed_wake(
    *,
    streak_days: int,
    best_streak: int,
    last_successful_wake_date: Optional[date],
    outcome_date: date,
) -> DayStreakState:
    """Apply a final wake failure for ``outcome_date``.

    If the user already recorded a successful wake today, the failure is a
    no-op (the day already counts). Otherwise the live streak resets to 0.
    ``best_streak`` and ``last_successful_wake_date`` are preserved.
    """
    current = max(0, int(streak_days or 0))
    best = max(0, int(best_streak or 0))

    if last_successful_wake_date is not None and last_successful_wake_date == outcome_date:
        return DayStreakState(
            streak_days=current,
            best_streak=best,
            last_successful_wake_date=last_successful_wake_date,
            changed=False,
            outcome_applied=None,
        )

    if current == 0:
        return DayStreakState(
            streak_days=0,
            best_streak=best,
            last_successful_wake_date=last_successful_wake_date,
            changed=False,
            outcome_applied=None,
        )

    return DayStreakState(
        streak_days=0,
        best_streak=best,
        last_successful_wake_date=last_successful_wake_date,
        changed=True,
        outcome_applied="failure",
    )


def apply_missed_day_decay(
    *,
    streak_days: int,
    best_streak: int,
    last_successful_wake_date: Optional[date],
    today: date,
) -> DayStreakState:
    """Reset the live streak when the last success is older than yesterday.

    A streak remains valid through the calendar day after the last success
    (user still has today to continue). If they already missed yesterday's
    chance relative to ``today``, the streak drops to 0. ``best_streak`` and
    ``last_successful_wake_date`` are preserved for history.
    """
    current = max(0, int(streak_days or 0))
    best = max(0, int(best_streak or 0))

    # Without a last-success date we cannot prove a miss (legacy rows).
    if last_successful_wake_date is None or current == 0:
        return DayStreakState(
            streak_days=current,
            best_streak=best,
            last_successful_wake_date=last_successful_wake_date,
            changed=False,
        )

    # Still alive if last success was today or yesterday.
    if last_successful_wake_date >= today - timedelta(days=1):
        return DayStreakState(
            streak_days=current,
            best_streak=best,
            last_successful_wake_date=last_successful_wake_date,
            changed=False,
        )

    return DayStreakState(
        streak_days=0,
        best_streak=best,
        last_successful_wake_date=last_successful_wake_date,
        changed=current != 0,
    )


def compute_day_streak_from_success_dates(
    success_dates: Sequence[date],
    *,
    today: Optional[date] = None,
) -> DayStreakState:
    """Replay ordered unique success dates into a Day Streak state.

    ``success_dates`` should already be sorted ascending. Duplicate dates are
    ignored. When ``today`` is provided, missed-day decay is applied at the end.
    """
    streak = 0
    best = 0
    last: Optional[date] = None

    for wake_date in success_dates:
        state = apply_successful_wake(
            streak_days=streak,
            best_streak=best,
            last_successful_wake_date=last,
            wake_date=wake_date,
        )
        streak = state.streak_days
        best = state.best_streak
        last = state.last_successful_wake_date

    if today is not None:
        return apply_missed_day_decay(
            streak_days=streak,
            best_streak=best,
            last_successful_wake_date=last,
            today=today,
        )

    return DayStreakState(
        streak_days=streak,
        best_streak=best,
        last_successful_wake_date=last,
        changed=False,
    )


def unique_success_dates_from_events(
    events: Iterable[Union[Mapping[str, Any], Any]],
    *,
    timezone_name: Optional[str] = "UTC",
) -> list[date]:
    """Extract sorted unique local success dates from verified wake events."""
    dates: list[date] = []
    seen: set[date] = set()

    for event in events:
        verified = _field(event, "verified", False)
        if not bool(verified):
            continue
        dismissed_at = _field(event, "dismissed_at", None)
        wake_date = local_calendar_date(dismissed_at, timezone_name)
        if wake_date is None:
            continue
        if wake_date in seen:
            continue
        seen.add(wake_date)
        dates.append(wake_date)

    dates.sort()
    return dates


class DayStreakService:
    """Persist and refresh Day Streak on ``UserProfile``.

    Writes happen only via ``record_wake_outcome`` after a final wake result.
    Reads must use ``read_stored_streak`` so every surface agrees.
    """

    @staticmethod
    def record_wake_outcome(
        profile: UserProfile,
        *,
        outcome: WakeOutcome,
        at: datetime,
        timezone_name: Optional[str] = None,
    ) -> DayStreakState:
        """Update Day Streak exactly once for a final wake outcome.

        Call this only after the wake cycle has a definitive result:
        - ``success`` — verified challenge completion dismissed the alarm
        - ``failure`` — final failure (e.g. abandoned cycle); not mid-cycle
          wrong answers, ring, or snooze

        Same-day repeated successes are no-ops (no second increment).
        """
        tz = timezone_name or getattr(profile, "timezone", None) or "UTC"
        outcome_date = local_calendar_date(at, tz)
        if outcome_date is None:
            return DayStreakState(
                streak_days=int(profile.streak_days or 0),
                best_streak=int(profile.best_streak or 0),
                last_successful_wake_date=getattr(
                    profile, "last_successful_wake_date", None
                ),
                changed=False,
            )

        if outcome == "success":
            state = apply_successful_wake(
                streak_days=int(profile.streak_days or 0),
                best_streak=int(profile.best_streak or 0),
                last_successful_wake_date=getattr(
                    profile, "last_successful_wake_date", None
                ),
                wake_date=outcome_date,
            )
        elif outcome == "failure":
            state = apply_failed_wake(
                streak_days=int(profile.streak_days or 0),
                best_streak=int(profile.best_streak or 0),
                last_successful_wake_date=getattr(
                    profile, "last_successful_wake_date", None
                ),
                outcome_date=outcome_date,
            )
        else:
            raise ValueError(f"Unknown Day Streak outcome: {outcome!r}")

        if state.changed:
            profile.streak_days = state.streak_days
            profile.best_streak = state.best_streak
            if state.last_successful_wake_date is not None:
                profile.last_successful_wake_date = state.last_successful_wake_date
        return state

    @staticmethod
    def record_successful_wake(
        profile: UserProfile,
        *,
        wake_at: datetime,
        timezone_name: Optional[str] = None,
    ) -> DayStreakState:
        """Backward-compatible alias for a final successful wake outcome."""
        return DayStreakService.record_wake_outcome(
            profile,
            outcome="success",
            at=wake_at,
            timezone_name=timezone_name,
        )

    @staticmethod
    def ensure_current(
        profile: UserProfile,
        *,
        today: Optional[date] = None,
        commit: bool = False,
        db: Optional[Session] = None,
    ) -> DayStreakState:
        """Apply missed-day decay so displayed streak matches calendar reality."""
        tz = getattr(profile, "timezone", None) or "UTC"
        as_of = today or today_in_timezone(tz)
        state = apply_missed_day_decay(
            streak_days=int(profile.streak_days or 0),
            best_streak=int(profile.best_streak or 0),
            last_successful_wake_date=getattr(
                profile, "last_successful_wake_date", None
            ),
            today=as_of,
        )
        if state.changed:
            profile.streak_days = state.streak_days
            if commit and db is not None:
                db.commit()
                db.refresh(profile)
            elif db is not None:
                db.flush()
        return state

    @staticmethod
    def read_stored_streak(
        profile: UserProfile,
        *,
        db: Optional[Session] = None,
        commit: bool = False,
        today: Optional[date] = None,
    ) -> int:
        """Return the canonical stored Day Streak after missed-day decay.

        All Dashboard / Analytics / Habit Score / API surfaces must use this
        (or ``profile.streak_days`` after calling ``ensure_current``) so they
        never diverge from the persisted counter.
        """
        DayStreakService.ensure_current(
            profile, today=today, commit=commit, db=db
        )
        return int(profile.streak_days or 0)

    @staticmethod
    def sync_from_events(
        profile: UserProfile,
        events: Sequence[Union[Mapping[str, Any], Any]],
        *,
        today: Optional[date] = None,
    ) -> DayStreakState:
        """Rebuild profile Day Streak from verified wake events (repair tool).

        Not used on hot read paths — prefer ``read_stored_streak`` so the
        value written at final wake outcome remains the display SSOT.
        """
        tz = getattr(profile, "timezone", None) or "UTC"
        as_of = today or today_in_timezone(tz)
        dates = unique_success_dates_from_events(events, timezone_name=tz)
        state = compute_day_streak_from_success_dates(dates, today=as_of)
        profile.streak_days = state.streak_days
        profile.best_streak = max(
            int(profile.best_streak or 0), state.best_streak
        )
        profile.last_successful_wake_date = state.last_successful_wake_date
        return DayStreakState(
            streak_days=profile.streak_days,
            best_streak=profile.best_streak,
            last_successful_wake_date=profile.last_successful_wake_date,
            changed=True,
        )


def _field(obj: Union[Mapping[str, Any], Any], name: str, default: Any) -> Any:
    if isinstance(obj, Mapping):
        return obj.get(name, default)
    return getattr(obj, name, default)
