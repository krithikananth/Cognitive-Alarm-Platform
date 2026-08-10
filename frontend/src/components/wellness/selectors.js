/**
 * Derived series/shape helpers shared by more than one Wellness Coach panel.
 *
 * Kept out of the panels so Habit Insights and Wellness Analytics chart the
 * exact same numbers from the same payload.
 */
import { formatDayLabel } from './constants';

/**
 * Daily habit-score series with component breakdown.
 * Days without activity are dropped — plotting them as 0 would read as a bad
 * day rather than a day with nothing recorded.
 */
export function buildHabitSeries(habitTrends) {
  return (habitTrends?.series || [])
    .filter((row) => row.has_activity)
    .map((row) => ({
      date: formatDayLabel(row.date),
      score: row.habit_score,
      sleep: row.breakdown?.sleep_adherence ?? 0,
      wake: row.breakdown?.wake_up_consistency ?? 0,
      challenge: row.breakdown?.challenge_completion ?? 0,
      snooze: row.breakdown?.snooze_reduction ?? 0,
    }));
}

/** Daily sleep-adherence vs wake-consistency series from the habit proxy. */
export function buildSleepAdherenceSeries(habitTrends) {
  return (habitTrends?.series || [])
    .filter((row) => row.has_activity)
    .map((row) => ({
      date: formatDayLabel(row.date),
      sleep_adherence: Math.round(row.breakdown?.sleep_adherence ?? 0),
      wake_consistency: Math.round(row.breakdown?.wake_up_consistency ?? 0),
    }));
}

/**
 * On-time wake series across exactly the selected 7/30/90-day window.
 * `window_trends` is sized to the requested window by the backend.
 */
export function buildScheduleSeries(windowTrends) {
  return (windowTrends?.series || [])
    .filter((row) => row.verified_wakes > 0 || row.on_time_wakes > 0)
    .map((row) => ({
      date: formatDayLabel(row.date),
      on_time: row.on_time_wakes,
      verified: row.verified_wakes,
      adherence_pct:
        row.verified_wakes > 0
          ? Math.round((row.on_time_wakes / row.verified_wakes) * 100)
          : 0,
    }));
}
