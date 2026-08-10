/**
 * Canonical Habit Score display format.
 *
 * Habit Score is a 0–100 scale (not a percentage). Always show as N/100
 * so Dashboard, Analytics, Reports, and Recommendations stay consistent.
 */

/**
 * @param {number|null|undefined} value
 * @param {{ empty?: string }} [options]
 * @returns {string}
 */
export function formatHabitScore(value, options = {}) {
  const empty = options.empty ?? '—';
  if (value == null || Number.isNaN(Number(value))) return empty;
  return `${Math.round(Number(value))}/100`;
}
