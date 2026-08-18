/** Notifee event -> ring bridge (spec §6.2, task 7). */
jest.mock('../src/api/client', () => ({
    __esModule: true,
    default: {},
    setSessionExpiredHandler: jest.fn(),
    readErrorDetail: jest.fn((error, fallback) => fallback),
}));

jest.mock('../src/api/alarms', () => ({
    listAlarms: jest.fn(),
    createAlarm: jest.fn(),
    updateAlarm: jest.fn(),
    deleteAlarm: jest.fn(),
    toggleAlarm: jest.fn(),
    fetchSchedule: jest.fn(async () => ({ occurrences: [] })),
    fetchChallenge: jest.fn(async () => ({ prompt: '1 + 1 = ?', difficulty: 'easy' })),
    verifyChallenge: jest.fn(),
    snoozeAlarm: jest.fn(),
    failWake: jest.fn(),
}));

const { EventType } = require('@notifee/react-native');

const useRingStore = require('../src/store/ringStore').default;
const {
    handleNotifeeEvent,
    ringPayloadFromNotification,
    startRingFromNotification,
} = require('../src/alarm/handlers');

// Exactly the shape scheduler.js writes: notifee ships `data` as strings only.
const NOTIFICATION = {
    id: 'alarm-11-1755390600000',
    title: 'Morning Alarm',
    data: {
        alarmId: '11',
        triggerAt: '2026-08-17T01:30:00+00:00',
        title: 'Morning Alarm',
        snoozeLimit: '3',
        snoozeIntervalMinutes: '5',
        vibrate: 'true',
    },
};

beforeEach(() => {
    jest.clearAllMocks();
    useRingStore.getState().stopRing();
});

describe('ringPayloadFromNotification', () => {
    it('parses the string-only data payload back into numbers', () => {
        expect(ringPayloadFromNotification(NOTIFICATION)).toEqual({
            alarmId: 11,
            notificationId: 'alarm-11-1755390600000',
            title: 'Morning Alarm',
            triggerAt: '2026-08-17T01:30:00+00:00',
            snoozeLimit: 3,
            snoozeIntervalMinutes: 5,
        });
    });

    it('rejects a notification with no usable alarm id', () => {
        expect(ringPayloadFromNotification({ id: 'alarm-x', data: {} })).toBeNull();
        expect(ringPayloadFromNotification(undefined)).toBeNull();
    });
});

describe('startRingFromNotification', () => {
    it('starts the ring for an id this app scheduled', () => {
        expect(startRingFromNotification(NOTIFICATION)).toBe(true);
        expect(useRingStore.getState().alarmId).toBe(11);
        expect(useRingStore.getState().snoozeLimit).toBe(3);
    });

    it('ignores notifications the scheduler does not own', () => {
        // Reminders and other product notifications share the event stream, so
        // the prefix check is what stops them opening the ring screen.
        expect(
            startRingFromNotification({ ...NOTIFICATION, id: 'bedtime-reminder-4' })
        ).toBe(false);
        expect(useRingStore.getState().alarmId).toBeNull();
    });
});

describe('handleNotifeeEvent', () => {
    it.each([
        ['DELIVERED', EventType.DELIVERED],
        ['PRESS', EventType.PRESS],
        ['ACTION_PRESS', EventType.ACTION_PRESS],
    ])('rings on %s', (_label, type) => {
        expect(handleNotifeeEvent({ type, detail: { notification: NOTIFICATION } })).toBe(true);
        expect(useRingStore.getState().alarmId).toBe(11);
    });

    it.each([
        ['DISMISSED', EventType.DISMISSED],
        ['TRIGGER_NOTIFICATION_CREATED', EventType.TRIGGER_NOTIFICATION_CREATED],
    ])('does not ring on %s', (_label, type) => {
        // Arming an alarm emits TRIGGER_NOTIFICATION_CREATED; ringing then would
        // fire the challenge the moment the schedule syncs.
        expect(handleNotifeeEvent({ type, detail: { notification: NOTIFICATION } })).toBe(false);
        expect(useRingStore.getState().alarmId).toBeNull();
    });

    it('survives an event with no notification attached', () => {
        expect(handleNotifeeEvent({ type: EventType.PRESS, detail: {} })).toBe(false);
        expect(handleNotifeeEvent()).toBe(false);
    });
});
