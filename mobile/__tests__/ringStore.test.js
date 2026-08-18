/** Ring state machine (spec §6.2/§6.3, task 7): idempotency and the three verify outcomes. */
jest.mock('../src/api/client', () => ({
    __esModule: true,
    default: {},
    setSessionExpiredHandler: jest.fn(),
    readErrorDetail: jest.fn((error, fallback) => error?.response?.data?.detail || fallback),
}));

jest.mock('../src/api/alarms', () => ({
    fetchChallenge: jest.fn(),
    verifyChallenge: jest.fn(),
    snoozeAlarm: jest.fn(),
    failWake: jest.fn(),
}));

const alarmApi = require('../src/api/alarms');
const useRingStore = require('../src/store/ringStore').default;
const {
    RING_STATUS,
    selectCanSnooze,
    selectIsRinging,
    setRingEffectsHandler,
} = require('../src/store/ringStore');

const CHALLENGE = {
    type: 'math',
    prompt: '7 + 8 = ?',
    options: ['13', '15', '17', '21'],
    difficulty: 'medium',
    time_limit_seconds: 30,
    current_step: 1,
    total_steps: 2,
};

const RING = {
    alarmId: 11,
    notificationId: 'alarm-11-1755390600000',
    title: 'Morning Alarm',
    snoozeLimit: 3,
    snoozeIntervalMinutes: 5,
};

/** Axios raises on 4xx, so rejections carry the body the UI has to read. */
function httpError(status, data) {
    return { response: { status, data } };
}

const effects = { stop: jest.fn(async () => { }), resync: jest.fn(async () => { }) };

beforeEach(() => {
    jest.clearAllMocks();
    setRingEffectsHandler(effects);
    useRingStore.getState().stopRing();
    alarmApi.fetchChallenge.mockResolvedValue(CHALLENGE);
});

const startRinging = async () => {
    useRingStore.getState().startRing(RING);
    await Promise.resolve();
    await Promise.resolve();
};

describe('entering the ring', () => {
    it('loads a challenge and reports that it is ringing', async () => {
        await startRinging();

        const state = useRingStore.getState();
        expect(state.status).toBe(RING_STATUS.CHALLENGE);
        expect(state.challenge).toEqual(CHALLENGE);
        expect(state.progress).toEqual({ current: 1, total: 2 });
        expect(selectIsRinging(state)).toBe(true);
        expect(alarmApi.fetchChallenge).toHaveBeenCalledWith(11);
    });

    it('ignores a second trigger for the alarm already ringing', async () => {
        await startRinging();
        alarmApi.fetchChallenge.mockClear();

        // The local AlarmManager trigger, the FCM backup push and a notification
        // press can all land for one instant; only the first may take effect.
        const accepted = useRingStore.getState().startRing(RING);

        expect(accepted).toBe(false);
        expect(alarmApi.fetchChallenge).not.toHaveBeenCalled();
    });

    it('does not let a different alarm hijack an active ring', async () => {
        await startRinging();

        expect(useRingStore.getState().startRing({ ...RING, alarmId: 12 })).toBe(false);
        expect(useRingStore.getState().alarmId).toBe(11);
    });

    it('keeps ringing when the challenge cannot be fetched', async () => {
        alarmApi.fetchChallenge.mockRejectedValueOnce(new Error('offline'));

        await startRinging();

        const state = useRingStore.getState();
        expect(state.status).toBe(RING_STATUS.ERROR);
        expect(selectIsRinging(state)).toBe(true);
        expect(effects.stop).not.toHaveBeenCalled();
    });
});

describe('answering', () => {
    it('sends the prompt and difficulty the server logs against', async () => {
        await startRinging();
        alarmApi.verifyChallenge.mockResolvedValue({ status: 'step_complete', is_dismissed: false });

        await useRingStore.getState().submitAnswer('15');

        expect(alarmApi.verifyChallenge).toHaveBeenCalledWith(
            11,
            expect.objectContaining({
                user_answer: '15',
                challenge_prompt: '7 + 8 = ?',
                challenge_difficulty: 'medium',
                failed_attempts: 0,
            })
        );
    });

    it('fetches the next challenge on step_complete without leaving the ring', async () => {
        await startRinging();
        alarmApi.verifyChallenge.mockResolvedValue({
            status: 'step_complete',
            message: 'Correct! 1 of 2 consecutive challenges complete.',
            current_step: 1,
            total_steps: 2,
            is_dismissed: false,
        });

        const outcome = await useRingStore.getState().submitAnswer('15');

        expect(outcome).toBe('step_complete');
        expect(alarmApi.fetchChallenge).toHaveBeenCalledTimes(2);
        expect(selectIsRinging(useRingStore.getState())).toBe(true);
        expect(effects.stop).not.toHaveBeenCalled();
    });

    it('silences the device and re-syncs once the wake is verified', async () => {
        await startRinging();
        alarmApi.verifyChallenge.mockResolvedValue({
            status: 'dismissed',
            message: 'Wake-up verified!',
            is_dismissed: true,
            wake_confirmed: true,
            success_streak: 4,
        });

        const outcome = await useRingStore.getState().submitAnswer('15');

        expect(outcome).toBe('dismissed');
        expect(useRingStore.getState().status).toBe(RING_STATUS.DISMISSED);
        expect(effects.stop).toHaveBeenCalledWith('alarm-11-1755390600000');
        expect(effects.resync).toHaveBeenCalled();
    });

    it('treats a rejected answer as flow control, not as a dismissal', async () => {
        await startRinging();
        alarmApi.verifyChallenge.mockRejectedValue(
            httpError(400, { detail: 'Incorrect answer. Consecutive streak reset — need 2 in a row.' })
        );

        const outcome = await useRingStore.getState().submitAnswer('13');

        const state = useRingStore.getState();
        expect(outcome).toBe('rejected');
        expect(state.status).toBe(RING_STATUS.CHALLENGE);
        expect(state.feedback).toMatch(/Incorrect answer/);
        expect(state.failedAttempts).toBe(1);
        // The load-bearing part: a wrong answer must never stop the alarm.
        expect(effects.stop).not.toHaveBeenCalled();
        expect(alarmApi.fetchChallenge).toHaveBeenCalledTimes(2);
    });

    it('refuses a timeout the same way, since the server owns the clock', async () => {
        await startRinging();
        alarmApi.verifyChallenge.mockRejectedValue(
            httpError(400, { detail: "Time's up! You took 41s but the limit is 30s." })
        );

        await useRingStore.getState().submitAnswer('15');

        expect(useRingStore.getState().feedback).toMatch(/Time's up/);
        expect(selectIsRinging(useRingStore.getState())).toBe(true);
        expect(effects.stop).not.toHaveBeenCalled();
    });

    it('does not submit twice while a request is in flight', async () => {
        await startRinging();
        let release;
        alarmApi.verifyChallenge.mockReturnValue(
            new Promise((resolve) => {
                release = () => resolve({ status: 'step_complete', is_dismissed: false });
            })
        );

        const first = useRingStore.getState().submitAnswer('15');
        const second = await useRingStore.getState().submitAnswer('15');
        release();
        await first;

        expect(second).toBeNull();
        expect(alarmApi.verifyChallenge).toHaveBeenCalledTimes(1);
    });
});

describe('snoozing', () => {
    it('releases the device and leaves the ring', async () => {
        await startRinging();
        alarmApi.snoozeAlarm.mockResolvedValue({ id: 11, total_snoozes: 1 });

        const snoozed = await useRingStore.getState().snooze();

        expect(snoozed).toBe(true);
        expect(effects.stop).toHaveBeenCalledWith('alarm-11-1755390600000');
        expect(effects.resync).toHaveBeenCalled();
        expect(selectIsRinging(useRingStore.getState())).toBe(false);
    });

    it('keeps ringing and surfaces the server message at the snooze limit', async () => {
        await startRinging();
        alarmApi.snoozeAlarm.mockRejectedValue(
            httpError(400, {
                detail: 'Maximum snooze limit reached. Solve the challenge to dismiss.',
            })
        );

        const snoozed = await useRingStore.getState().snooze();

        expect(snoozed).toBe(false);
        expect(useRingStore.getState().feedback).toMatch(/Maximum snooze limit/);
        expect(selectIsRinging(useRingStore.getState())).toBe(true);
        expect(effects.stop).not.toHaveBeenCalled();
    });

    it('reports the remaining snoozes from the server count', async () => {
        await startRinging();

        expect(selectCanSnooze(useRingStore.getState())).toBe(true);

        useRingStore.setState({ snoozeCount: 3 });
        expect(selectCanSnooze(useRingStore.getState())).toBe(false);
    });

    it('cannot snooze an alarm that allows none', async () => {
        useRingStore.getState().startRing({ ...RING, snoozeLimit: 0 });
        await Promise.resolve();

        expect(selectCanSnooze(useRingStore.getState())).toBe(false);
    });
});

describe('giving up', () => {
    it('records the abandoned cycle and stops the alarm', async () => {
        await startRinging();
        alarmApi.failWake.mockResolvedValue({
            status: 'failed',
            message: 'Wake cycle abandoned.',
            wake_confirmed: false,
            success_streak: 0,
            failure_streak: 1,
        });

        await useRingStore.getState().giveUp();

        const state = useRingStore.getState();
        expect(state.status).toBe(RING_STATUS.ABANDONED);
        expect(state.outcome.wake_confirmed).toBe(false);
        expect(effects.stop).toHaveBeenCalled();
    });
});

describe('leaving the ring', () => {
    it('resets to idle so the next alarm can start cleanly', async () => {
        await startRinging();
        useRingStore.setState({ failedAttempts: 4, feedback: 'stale' });

        useRingStore.getState().stopRing();

        const state = useRingStore.getState();
        expect(state.status).toBe(RING_STATUS.IDLE);
        expect(state.alarmId).toBeNull();
        expect(state.failedAttempts).toBe(0);
        expect(state.feedback).toBeNull();
        expect(useRingStore.getState().startRing(RING)).toBe(true);
    });
});
