/** Alarm time helpers (spec §6.3): parsing, recurrence copy, countdown. */
const {
    BASE_DAYS_BY_TYPE,
    describeRecurrence,
    formatAlarmTime,
    formatCountdown,
    isValidDateInput,
    parseAlarmTime,
    toApiTime,
} = require('../src/utils/time');

describe('parseAlarmTime / toApiTime', () => {
    it('round-trips a stored time through the 12-hour editor parts', () => {
        expect(toApiTime(parseAlarmTime('07:30:00'))).toBe('07:30:00');
        expect(toApiTime(parseAlarmTime('19:05:00'))).toBe('19:05:00');
    });

    it('maps midnight and noon to the right period', () => {
        expect(parseAlarmTime('00:00:00')).toEqual({
            hour: '12',
            minute: '00',
            period: 'AM',
        });
        expect(parseAlarmTime('12:00:00')).toEqual({
            hour: '12',
            minute: '00',
            period: 'PM',
        });
    });

    it('clamps out-of-range editor input instead of emitting an invalid time', () => {
        expect(toApiTime({ hour: '', minute: '', period: 'AM' })).toBe('00:00:00');
        expect(toApiTime({ hour: '9', minute: '99', period: 'AM' })).toBe('09:59:00');
    });

    it('formats for display', () => {
        expect(formatAlarmTime('07:05:00')).toBe('7:05 AM');
        expect(formatAlarmTime('23:45:00')).toBe('11:45 PM');
    });
});

describe('describeRecurrence', () => {
    it('names the common patterns', () => {
        expect(describeRecurrence({ alarm_type: 'daily' })).toBe('Every day');
        expect(describeRecurrence({ alarm_type: 'weekday' })).toBe('Weekdays');
        expect(describeRecurrence({ alarm_type: 'weekend' })).toBe('Weekends');
    });

    it('lists an explicit day selection', () => {
        expect(
            describeRecurrence({ alarm_type: 'daily', days_of_week: [2, 0] })
        ).toBe('Mon, Wed');
    });

    it('falls back to the pattern days when the selection is disjoint', () => {
        // Mirrors `_allowed_weekdays`: a selection outside the pattern cannot
        // make an alarm unschedulable, so the base set still applies.
        expect(
            describeRecurrence({ alarm_type: 'weekend', days_of_week: [0, 1] })
        ).toBe('Weekends');
        expect(BASE_DAYS_BY_TYPE.weekend).toEqual([5, 6]);
    });

    it('describes one-time alarms by date', () => {
        expect(
            describeRecurrence({ alarm_type: 'one_time', one_time_date: '2026-08-20' })
        ).toBe('Once on 2026-08-20');
        expect(describeRecurrence({ alarm_type: 'one_time' })).toBe('Once');
    });

    it('marks smart adaptive alarms', () => {
        expect(describeRecurrence({ alarm_type: 'smart_adaptive' })).toBe(
            'Smart · Every day'
        );
    });
});

describe('formatCountdown', () => {
    const now = Date.parse('2026-08-14T10:00:00Z');

    it('renders minutes, hours and days', () => {
        expect(formatCountdown('2026-08-14T10:45:00Z', now)).toBe('in 45m');
        expect(formatCountdown('2026-08-14T17:20:00Z', now)).toBe('in 7h 20m');
        expect(formatCountdown('2026-08-14T18:00:00Z', now)).toBe('in 8h');
        expect(formatCountdown('2026-08-16T13:00:00Z', now)).toBe('in 2d 3h');
    });

    it('handles a trigger that has already passed', () => {
        expect(formatCountdown('2026-08-14T09:59:00Z', now)).toBe('due now');
    });

    it('returns null when there is no scheduled trigger', () => {
        expect(formatCountdown(null, now)).toBeNull();
        expect(formatCountdown('not-a-date', now)).toBeNull();
    });
});

describe('isValidDateInput', () => {
    it('accepts real calendar dates only', () => {
        expect(isValidDateInput('2026-08-20')).toBe(true);
        expect(isValidDateInput('2026-02-30')).toBe(false);
        expect(isValidDateInput('20-08-2026')).toBe(false);
        expect(isValidDateInput('')).toBe(false);
    });
});
