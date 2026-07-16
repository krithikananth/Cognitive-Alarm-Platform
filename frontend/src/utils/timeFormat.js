/**
 * Format "HH:MM" (or "HH:MM:SS") as "HH:MM (h:mm AM/PM)".
 * Examples: "08:00 (8:00 AM)", "22:30 (10:30 PM)".
 */
export function formatTimeDisplay(time24) {
  const [hours = 0, minutes = 0] = (time24 || '00:00').slice(0, 5).split(':').map(Number);
  const hour24 = ((hours % 24) + 24) % 24;
  const period = hour24 >= 12 ? 'PM' : 'AM';
  let hour12 = hour24 % 12;
  if (hour12 === 0) hour12 = 12;
  const padded24 = `${String(hour24).padStart(2, '0')}:${String(minutes || 0).padStart(2, '0')}`;
  return `${padded24} (${hour12}:${String(minutes || 0).padStart(2, '0')} ${period})`;
}
