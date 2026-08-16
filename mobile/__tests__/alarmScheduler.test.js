/** Alarm scheduler (spec §6.1, task 6): diffing, idempotency and failure safety. */
jest.mock('../src/api/client', () => ({
    __esModule: true,
    default: {},
    setSessionExpiredHandler: jest.fn(),
    readErrorDetail: jest.fn((error, fallback) => error?.detail || fallback),
}));

jest.mock('../src/api/alarms', () => ({
    listAlarms: jest.fn(),
    createAlarm: jest.fn(),
    updateAlarm: jest.fn(),
    deleteAlarm: jest.fn(),
    toggleAlarm: jest.fn(),
    fetchSchedule: jest.fn(),
}));

const notifee = require('@notifee/react-native').default;
const { AlarmType, TriggerType } = require('@notifee/react-native');

const { fetchSchedule } = require('../src/api/alarms');
const { ALARM_CHANNEL_ID } = require('../src/alarm/channel');
const {
    NOTIFICATION_ID_PREFIX,
    buildNotification,
    cancelAllAlarms,
    occurrenceId,
    syncSchedule,
} = require('../src/alarm/scheduler');

const NOW = Date.parse('2026-08-16T10:00:00Z');

function occurrence(overrides = {}) {
    return {
        alarm_id: 11,
        trigger_at: '2026-08-17T01:30:00+00:00',
        title: 'Morning Alarm',
        challenge_type: 'math',
        challenge_count: 1,
        challenge_difficulty: 'medium',
        snooze_limit: 3,
        snooze_interval_minutes: 5,
        volume: 80,
        vibrate: true,
        ...overrides,
    };
}

/** Shape returned by `notifee.getTriggerNotifications()`. */
function armed(ids) {
    return ids.map((id) => ({ notification: { id }, trigger: {} }));
}

beforeEach(() => {
    jest.clearAllMocks();
    notifee.createChannel.mockResolvedValue(ALARM_CHANNEL_ID);
    notifee.createTriggerNotification.mockResolvedValue(undefined);
    notifee.cancelTriggerNotifications.mockResolvedValue(undefined);
    notifee.getTriggerNotifications.mockResolvedValue([]);
});

describe('occurrenceId', () => {
    it('is derived from the alarm and the exact instant', () => {
        const epoch = Date.parse('2026-08-17T01:30:00+00:00');
        expect(occurrenceId(11, '2026-08-17T01:30:00+00:00')).toBe(
            `${NOTIFICATION_ID_PREFIX}11-${epoch}`
        );
    });

    it('is stable across equivalent representations of the same instant', () => {
        expect(occurrenceId(11, '2026-08-17T01:30:00+00:00')).toBe(
            occurrenceId(11, '2026-08-17T02:30:00+01:00')
        );
    });
});

describe('syncSchedule', () => {
    it('arms one exact alarm-clock trigger per occurrence', async () => {
        fetchSchedule.mockResolvedValue({ occurrences: [occurrence()] });

        const result = await syncSchedule({ now: NOW });

        expect(result).toMatchObject({ ok: true, created: 1, cancelled: 0, total: 1 });
        expect(notifee.createChannel).toHaveBeenCalled();

        const [notification, trigger] = notifee.createTriggerNotification.mock.calls[0];
        expect(notification.id).toBe(occurrenceId(11, '2026-08-17T01:30:00+00:00'));
        expect(notification.android.channelId).toBe(ALARM_CHANNEL_ID);
        expect(notification.android.fullScreenAction).toEqual({
            id: 'ring',
            launchActivity: 'default',
        });
        expect(trigger).toEqual({
            type: TriggerType.TIMESTAMP,
            timestamp: Date.parse('2026-08-17T01:30:00+00:00'),
            // Anything weaker than SET_ALARM_CLOCK can be delayed by Doze.
            alarmManager: { type: AlarmType.SET_ALARM_CLOCK },
        });
    });

    it('is idempotent — re-syncing does not re-arm what is already scheduled', async () => {
        const id = occurrenceId(11, '2026-08-17T01:30:00+00:00');
        fetchSchedule.mockResolvedValue({ occurrences: [occurrence()] });
        notifee.getTriggerNotifications.mockResolvedValue(armed([id]));

        const result = await syncSchedule({ now: NOW });

        expect(notifee.createTriggerNotification).not.toHaveBeenCalled();
        expect(notifee.cancelTriggerNotifications).not.toHaveBeenCalled();
        expect(result).toMatchObject({ created: 0, cancelled: 0, kept: 1 });
    });

    it('cancels occurrences the server no longer returns', async () => {
        const keep = occurrenceId(11, '2026-08-17T01:30:00+00:00');
        const gone = occurrenceId(12, '2026-08-18T05:00:00+00:00');
        fetchSchedule.mockResolvedValue({ occurrences: [occurrence()] });
        notifee.getTriggerNotifications.mockResolvedValue(armed([keep, gone]));

        const result = await syncSchedule({ now: NOW });

        expect(notifee.cancelTriggerNotifications).toHaveBeenCalledWith([gone]);
        expect(result).toMatchObject({ cancelled: 1, created: 0 });
    });

    it('never touches notifications it did not schedule', async () => {
        fetchSchedule.mockResolvedValue({ occurrences: [] });
        notifee.getTriggerNotifications.mockResolvedValue(
            armed(['reminder-42', 'fcm-announcement'])
        );

        await syncSchedule({ now: NOW });

        expect(notifee.cancelTriggerNotifications).not.toHaveBeenCalled();
    });

    it('skips instants in the past, which AlarmManager would fire immediately', async () => {
        fetchSchedule.mockResolvedValue({
            occurrences: [
                occurrence({ trigger_at: '2026-08-16T09:00:00+00:00' }),
                occurrence({ alarm_id: 12, trigger_at: '2026-08-16T11:00:00+00:00' }),
            ],
        });

        const result = await syncSchedule({ now: NOW });

        expect(result).toMatchObject({ created: 1, total: 1 });
        expect(notifee.createTriggerNotification.mock.calls[0][1].timestamp).toBe(
            Date.parse('2026-08-16T11:00:00+00:00')
        );
    });

    it('ignores malformed trigger instants instead of arming NaN', async () => {
        fetchSchedule.mockResolvedValue({
            occurrences: [occurrence({ trigger_at: 'not-a-date' })],
        });

        const result = await syncSchedule({ now: NOW });

        expect(result).toMatchObject({ ok: true, created: 0, total: 0 });
        expect(notifee.createTriggerNotification).not.toHaveBeenCalled();
    });

    it('does NOT disarm the device when the schedule request fails', async () => {
        const id = occurrenceId(11, '2026-08-17T01:30:00+00:00');
        fetchSchedule.mockRejectedValue(new Error('Network Error'));
        notifee.getTriggerNotifications.mockResolvedValue(armed([id]));

        const result = await syncSchedule({ now: NOW });

        expect(result.ok).toBe(false);
        expect(notifee.cancelTriggerNotifications).not.toHaveBeenCalled();
        expect(notifee.createTriggerNotification).not.toHaveBeenCalled();
    });

    it('arms every occurrence of a recurring alarm across the horizon', async () => {
        fetchSchedule.mockResolvedValue({
            occurrences: [
                occurrence({ trigger_at: '2026-08-17T01:30:00+00:00' }),
                occurrence({ trigger_at: '2026-08-18T01:30:00+00:00' }),
                occurrence({ trigger_at: '2026-08-19T01:30:00+00:00' }),
            ],
        });

        const result = await syncSchedule({ now: NOW });

        expect(result).toMatchObject({ created: 3, total: 3 });
        const ids = notifee.createTriggerNotification.mock.calls.map(([n]) => n.id);
        expect(new Set(ids).size).toBe(3);
    });

    it('requests the configured horizon', async () => {
        fetchSchedule.mockResolvedValue({ occurrences: [] });

        await syncSchedule({ horizonDays: 3, now: NOW });

        expect(fetchSchedule).toHaveBeenCalledWith({ days: 3 });
    });
});

describe('buildNotification', () => {
    it('ships every ring parameter as a string, matching the FCM data contract', () => {
        const notification = buildNotification(occurrence());

        expect(notification.data).toEqual({
            alarmId: '11',
            triggerAt: '2026-08-17T01:30:00+00:00',
            title: 'Morning Alarm',
            challengeType: 'math',
            challengeCount: '1',
            challengeDifficulty: 'medium',
            snoozeLimit: '3',
            snoozeIntervalMinutes: '5',
            volume: '80',
            vibrate: 'true',
        });
    });

    it('cannot be swiped away', () => {
        const notification = buildNotification(occurrence());

        expect(notification.android.ongoing).toBe(true);
        expect(notification.android.autoCancel).toBe(false);
        expect(notification.android.loopSound).toBe(true);
    });

    it('honours the alarm vibrate setting', () => {
        expect(buildNotification(occurrence()).android.vibrationPattern).toBeDefined();
        expect(
            buildNotification(occurrence({ vibrate: false })).android.vibrationPattern
        ).toBeUndefined();
    });
});

describe('cancelAllAlarms', () => {
    it('disarms only this app\'s alarms', async () => {
        const mine = occurrenceId(11, '2026-08-17T01:30:00+00:00');
        notifee.getTriggerNotifications.mockResolvedValue(armed([mine, 'reminder-42']));

        const cancelled = await cancelAllAlarms();

        expect(cancelled).toBe(1);
        expect(notifee.cancelTriggerNotifications).toHaveBeenCalledWith([mine]);
    });

    it('is a no-op when nothing is armed', async () => {
        notifee.getTriggerNotifications.mockResolvedValue([]);

        expect(await cancelAllAlarms()).toBe(0);
        expect(notifee.cancelTriggerNotifications).not.toHaveBeenCalled();
    });
});
