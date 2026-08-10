/**
 * Format "HH:MM" (or "HH:MM:SS") as "h:mm AM/PM".
 * Examples: "8:00 AM", "11:00 PM".
 */
export function formatTime12Hour(time24) {
  const [hours = 0, minutes = 0] = (time24 || '00:00').slice(0, 5).split(':').map(Number);
  const hour24 = ((hours % 24) + 24) % 24;
  const period = hour24 >= 12 ? 'PM' : 'AM';
  let hour12 = hour24 % 12;
  if (hour12 === 0) hour12 = 12;
  return `${hour12}:${String(minutes || 0).padStart(2, '0')} ${period}`;
}

/**
 * Format "HH:MM" (or "HH:MM:SS") as "HH:MM (h:mm AM/PM)".
 * Examples: "08:00 (8:00 AM)", "22:30 (10:30 PM)".
 */
export function formatTimeDisplay(time24) {
  const [hours = 0, minutes = 0] = (time24 || '00:00').slice(0, 5).split(':').map(Number);
  const hour24 = ((hours % 24) + 24) % 24;
  const padded24 = `${String(hour24).padStart(2, '0')}:${String(minutes || 0).padStart(2, '0')}`;
  return `${padded24} (${formatTime12Hour(padded24)})`;
}

/**
 * Compute bedtime (HH:MM) from wake time and sleep duration hours.
 * Matches backend: wake − sleep goal, wrapped over midnight.
 */
export function computeBedtime(wakeTime, durationHours) {
  const [h = 7, m = 0] = (wakeTime || '07:00').slice(0, 5).split(':').map(Number);
  const wakeMinutes = h * 60 + (m || 0);
  const sleepMinutes = Math.round(Number(durationHours || 8) * 60);
  const bedMinutes = ((wakeMinutes - sleepMinutes) % (24 * 60) + 24 * 60) % (24 * 60);
  const bedH = Math.floor(bedMinutes / 60);
  const bedM = bedMinutes % 60;
  return `${String(bedH).padStart(2, '0')}:${String(bedM).padStart(2, '0')}`;
}

/**
 * Format an instant in an IANA timezone, falling back to UTC for unknown zones.
 * Returns null for missing/unparsable input so callers can render their own placeholder.
 */
export function formatInTimeZone(value, timeZone, options = {}) {
  const date = value instanceof Date ? value : new Date(value);
  if (!value || Number.isNaN(date.getTime())) return null;
  try {
    return new Intl.DateTimeFormat(undefined, { timeZone: timeZone || 'UTC', ...options }).format(date);
  } catch {
    return new Intl.DateTimeFormat(undefined, { timeZone: 'UTC', ...options }).format(date);
  }
}
