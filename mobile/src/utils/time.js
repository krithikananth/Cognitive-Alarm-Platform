// Alarm time formatting and countdown helpers (spec §6.3, tasks 5-7).

export const DAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

// Weekdays each recurrence pattern may ring on — mirrors `_allowed_weekdays` on
// the backend. One-time alarms fire on a date, so they have no day picker.
export const BASE_DAYS_BY_TYPE = {
    daily: [0, 1, 2, 3, 4, 5, 6],
    weekday: [0, 1, 2, 3, 4],
    weekend: [5, 6],
    smart_adaptive: [0, 1, 2, 3, 4, 5, 6],
};

export const ALARM_TYPES = [
    { value: 'daily', label: 'Daily' },
    { value: 'weekday', label: 'Weekdays' },
    { value: 'weekend', label: 'Weekends' },
    { value: 'one_time', label: 'One time' },
    { value: 'smart_adaptive', label: 'Smart' },
];

export const CHALLENGE_TYPES = [
    { value: 'random', label: 'Random' },
    { value: 'math', label: 'Math' },
    { value: 'logic', label: 'Logic' },
    { value: 'memory', label: 'Memory' },
    { value: 'word_game', label: 'Word game' },
    { value: 'pattern', label: 'Pattern' },
    { value: 'riddle', label: 'Riddle' },
    { value: 'quiz', label: 'Quiz' },
];

export const DIFFICULTIES = ['beginner', 'easy', 'medium', 'hard', 'expert'];

/** Split a stored `HH:MM:SS` into the 12-hour parts the editor binds to. */
export function parseAlarmTime(value) {
    const [rawHour = 7, rawMinute = 0] = String(value || '07:00')
        .split(':')
        .map((part) => Number(part));
    const hour24 = Number.isFinite(rawHour) ? ((rawHour % 24) + 24) % 24 : 7;
    const minute = Number.isFinite(rawMinute) ? Math.min(Math.max(rawMinute, 0), 59) : 0;
    const displayHour = hour24 % 12 === 0 ? 12 : hour24 % 12;
    return {
        hour: String(displayHour),
        minute: String(minute).padStart(2, '0'),
        period: hour24 >= 12 ? 'PM' : 'AM',
    };
}

/** Rebuild the `HH:MM:SS` the API expects from the 12-hour editor parts. */
export function toApiTime({ hour, minute, period }) {
    let hour24 = Number(hour);
    if (!Number.isFinite(hour24) || hour24 < 1 || hour24 > 12) hour24 = 12;
    if (hour24 === 12) hour24 = 0;
    if (period === 'PM') hour24 += 12;
    let minutes = Number(minute);
    if (!Number.isFinite(minutes)) minutes = 0;
    minutes = Math.min(Math.max(Math.trunc(minutes), 0), 59);
    return `${String(hour24).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:00`;
}

/** `07:30:00` -> `7:30 AM`. */
export function formatAlarmTime(value) {
    const { hour, minute, period } = parseAlarmTime(value);
    return `${hour}:${minute} ${period}`;
}

function sameDays(a, b) {
    return a.length === b.length && a.every((day, index) => day === b[index]);
}

/** One line describing when an alarm rings, matching the backend's day rules. */
export function describeRecurrence(alarm) {
    const type = alarm?.alarm_type;
    if (type === 'one_time') {
        return alarm?.one_time_date ? `Once on ${alarm.one_time_date}` : 'Once';
    }

    const base = BASE_DAYS_BY_TYPE[type] || BASE_DAYS_BY_TYPE.daily;
    const selected = Array.isArray(alarm?.days_of_week)
        ? alarm.days_of_week.filter((day) => base.includes(day))
        : [];
    // An empty or disjoint selection falls back to the pattern's own days, so an
    // alarm is never left unschedulable — same rule as `_allowed_weekdays`.
    const days = (selected.length ? selected : base).slice().sort((a, b) => a - b);
    const prefix = type === 'smart_adaptive' ? 'Smart · ' : '';

    if (sameDays(days, BASE_DAYS_BY_TYPE.daily)) return `${prefix}Every day`;
    if (sameDays(days, BASE_DAYS_BY_TYPE.weekday)) return `${prefix}Weekdays`;
    if (sameDays(days, BASE_DAYS_BY_TYPE.weekend)) return `${prefix}Weekends`;
    return prefix + days.map((day) => DAY_LABELS[day]).join(', ');
}

/** Relative time to the next ring, e.g. `in 7h 20m`. */
export function formatCountdown(isoUtc, now = Date.now()) {
    if (!isoUtc) return null;
    const target = new Date(isoUtc).getTime();
    if (!Number.isFinite(target)) return null;

    const diffMs = target - now;
    if (diffMs <= 0) return 'due now';

    const minutes = Math.round(diffMs / 60000);
    if (minutes < 1) return 'in under a minute';
    if (minutes < 60) return `in ${minutes}m`;

    const hours = Math.floor(minutes / 60);
    const remainderMinutes = minutes % 60;
    if (hours < 24) {
        return remainderMinutes ? `in ${hours}h ${remainderMinutes}m` : `in ${hours}h`;
    }

    const days = Math.floor(hours / 24);
    const remainderHours = hours % 24;
    return remainderHours ? `in ${days}d ${remainderHours}h` : `in ${days}d`;
}

/** `2026-08-20` style check used by the one-time date field. */
export function isValidDateInput(value) {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(String(value || ''))) return false;
    const [year, month, day] = value.split('-').map(Number);
    const parsed = new Date(Date.UTC(year, month - 1, day));
    return (
        parsed.getUTCFullYear() === year &&
        parsed.getUTCMonth() === month - 1 &&
        parsed.getUTCDate() === day
    );
}

