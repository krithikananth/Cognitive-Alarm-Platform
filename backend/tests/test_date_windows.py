"""Regression guards for the shared lookback-window semantics.

``days=N`` means "N calendar days ending today, inclusive". Both window
helpers previously subtracted a full N days from today, so every window was
one day too wide and a ``days=N`` request never lined up with the equivalent
explicit ``start_date``/``end_date`` range.

The dashboards and the reports must agree, otherwise the same period renders
different totals depending on which screen the user opens.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.dashboard_aggregations import lookback_start
from app.services.report_service import resolve_date_window


def _today_utc() -> date:
    return datetime.now(timezone.utc).date()


class TestLookbackStart:
    """``dashboard_aggregations.lookback_start`` — dashboard windows."""

    def test_single_day_window_starts_today(self):
        assert lookback_start(1).date() == _today_utc()

    @pytest.mark.parametrize("days", [7, 30, 90, 365])
    def test_window_covers_exactly_n_calendar_days(self, days):
        start = lookback_start(days)
        assert start.date() == _today_utc() - timedelta(days=days - 1)
        assert (_today_utc() - start.date()).days + 1 == days

    def test_window_starts_at_midnight_utc(self):
        start = lookback_start(30)
        assert (start.hour, start.minute, start.second, start.microsecond) == (0, 0, 0, 0)


class TestResolveDateWindow:
    """``report_service.resolve_date_window`` — report and admin windows."""

    def test_single_day_window_starts_today(self):
        start, _end, days = resolve_date_window(days=1)
        assert days == 1
        assert start.date() == _today_utc()

    @pytest.mark.parametrize("days", [7, 30, 90, 365])
    def test_window_covers_exactly_n_calendar_days(self, days):
        start, end, resolved = resolve_date_window(days=days)
        assert resolved == days
        assert start.date() == _today_utc() - timedelta(days=days - 1)
        assert (end.date() - start.date()).days + 1 == days

    def test_days_and_explicit_range_together_are_rejected(self):
        """Ambiguous input silently ignored the range before this guard."""
        with pytest.raises(ValueError):
            resolve_date_window(
                days=7,
                start_date=date(2026, 7, 1),
                end_date=date(2026, 7, 10),
            )


@pytest.mark.parametrize("days", [1, 7, 30, 365])
def test_dashboard_and_report_windows_agree(days):
    """The same ``days=N`` must mean the same period on both surfaces."""
    report_start, _end, _resolved = resolve_date_window(days=days)
    assert lookback_start(days).date() == report_start.date()
