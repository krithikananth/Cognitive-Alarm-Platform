/**
 * Shared constants and pure helpers for the Wellness Coach dashboard.
 *
 * Kept separate from the panels so every panel renders the same chart chrome,
 * the same category colours, and the same trend vocabulary.
 */
import {
  HiOutlineArrowTrendingDown,
  HiOutlineArrowTrendingUp,
  HiOutlineMinus,
} from 'react-icons/hi2';

export const CHART_TOOLTIP_STYLE = {
  contentStyle: { background: '#1e293b', border: '1px solid #334155', borderRadius: 12 },
  labelStyle: { color: '#e2e8f0' },
};

export const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

export const CATEGORY_STYLES = {
  sleep: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/25',
  wake: 'bg-amber-500/15 text-amber-300 border-amber-500/25',
  habit: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
  productivity: 'bg-sky-500/15 text-sky-300 border-sky-500/25',
  challenge: 'bg-violet-500/15 text-violet-300 border-violet-500/25',
};

export const WINDOW_OPTIONS = [7, 30, 90];
export const CLIENTS_PER_PAGE = 8;

export const STATUS_FILTERS = [
  { value: 'all', label: 'All', hint: 'Every client assigned to you' },
  {
    value: 'needs_attention',
    label: 'Needs Attention',
    hint: 'Clients triggering a habit score, wake consistency, or inactivity alert',
  },
  {
    value: 'on_track',
    label: 'On Track',
    hint: 'Clients meeting every alert threshold',
  },
  {
    value: 'inactive',
    label: 'Inactive',
    hint: 'Clients with no wake or challenge activity in the selected period',
  },
];

export const SORT_OPTIONS = [
  { value: 'full_name:asc', label: 'Name (A–Z)' },
  { value: 'habit_score:desc', label: 'Habit score (high → low)' },
  { value: 'habit_score:asc', label: 'Habit score (low → high)' },
  { value: 'wake_consistency:desc', label: 'Wake consistency (high → low)' },
  { value: 'streak_days:desc', label: 'Day streak (high → low)' },
  { value: 'verified_wakes:desc', label: 'Verified wakes (high → low)' },
  { value: 'challenge_accuracy:desc', label: 'Challenge accuracy (high → low)' },
  { value: 'last_wake_at:asc', label: 'Least recently active' },
  { value: 'assigned_at:desc', label: 'Recently assigned' },
];

export const HABIT_COMPONENTS = [
  { key: 'wake_up_consistency', label: 'Wake consistency', color: 'bg-amber-400' },
  { key: 'challenge_completion', label: 'Challenge completion', color: 'bg-violet-400' },
  { key: 'snooze_reduction', label: 'Snooze reduction', color: 'bg-sky-400' },
  { key: 'sleep_adherence', label: 'Sleep adherence', color: 'bg-indigo-400' },
];

export const DEFAULT_HABIT_WEIGHTS = {
  wake_up_consistency: 0.35,
  challenge_completion: 0.25,
  snooze_reduction: 0.2,
  sleep_adherence: 0.2,
};

export function trendMeta(direction) {
  if (direction === 'improving') {
    return { Icon: HiOutlineArrowTrendingUp, label: 'Improving', color: 'text-emerald-400' };
  }
  if (direction === 'declining') {
    return { Icon: HiOutlineArrowTrendingDown, label: 'Declining', color: 'text-orange-400' };
  }
  if (direction === 'stable') {
    return { Icon: HiOutlineMinus, label: 'Stable', color: 'text-slate-300' };
  }
  return { Icon: HiOutlineMinus, label: 'Not enough data', color: 'text-slate-500' };
}

/** Coach-facing label for a roster row. */
export function clientDisplayName(clientRow) {
  return clientRow?.full_name || clientRow?.username || '';
}

/**
 * The client's own stored timezone — every client-facing instant is rendered
 * in it, never in the coach's browser zone.
 */
export function clientTimezoneOf(clientRow) {
  return clientRow?.timezone || 'UTC';
}

/**
 * Label an ISO calendar date (e.g. "2026-08-05") for a chart axis.
 * Daily buckets are whole calendar days, so the label is rendered without a
 * timezone shift — shifting would move activity onto the wrong day.
 */
export function formatDayLabel(isoDate) {
  if (!isoDate) return '';
  const parsed = new Date(`${isoDate}T00:00:00Z`);
  if (Number.isNaN(parsed.getTime())) return isoDate;
  return new Intl.DateTimeFormat(undefined, {
    timeZone: 'UTC',
    month: 'short',
    day: 'numeric',
  }).format(parsed);
}
