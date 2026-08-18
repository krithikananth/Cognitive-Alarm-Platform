// Zustand ring store. `isRinging` is the idempotency guard shared by all four entry paths:
// full-screen intent, notification tap, FCM backup push, overdue-on-open (spec §6.2, task 7).
import { create } from 'zustand';

import * as alarmApi from '../api/alarms';
import { readErrorDetail } from '../api/client';

export const RING_STATUS = {
    IDLE: 'idle',
    LOADING: 'loading',
    CHALLENGE: 'challenge',
    ERROR: 'error',
    DISMISSED: 'dismissed',
    ABANDONED: 'abandoned',
};

export const selectIsRinging = (state) => state.status !== RING_STATUS.IDLE;

export const selectCanSnooze = (state) =>
    state.snoozeLimit > 0 && state.snoozeCount < state.snoozeLimit;

let ringEffects = {};

/**
 * Registered by the notifee handlers so the store can silence the device.
 *
 * Injected rather than imported for the same reason as `alarmStore`: importing
 * Notifee here would drag the native module into every store test.
 */
export function setRingEffectsHandler(handler) {
    ringEffects = handler && typeof handler === 'object' ? handler : {};
}

async function runEffect(name, ...args) {
    try {
        await ringEffects[name]?.(...args);
    } catch {
        // Silencing the notification is best-effort. A failure here must not
        // strand the user on a ring screen whose alarm the server already closed.
    }
}

const IDLE_STATE = {
    status: RING_STATUS.IDLE,
    alarmId: null,
    notificationId: null,
    title: 'Alarm',
    triggerAt: null,
    snoozeLimit: 0,
    snoozeIntervalMinutes: 5,
    snoozeCount: 0,
    challenge: null,
    issuedAt: null,
    failedAttempts: 0,
    progress: { current: 0, total: 1 },
    feedback: null,
    error: null,
    outcome: null,
    busy: false,
};

const toCount = (value, fallback) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
};

export const useRingStore = create((set, get) => ({
    ...IDLE_STATE,

    /**
     * Enter the ring. Returns false when a ring is already in progress.
     *
     * This is the whole point of the store: the local trigger, a notification
     * press, the FCM backup push and an overdue alarm on app open can all fire
     * for the same instant, and only the first may take effect.
     */
    startRing: (payload) => {
        if (get().status !== RING_STATUS.IDLE) return false;

        const alarmId = toCount(payload?.alarmId, null);
        if (!alarmId || alarmId <= 0) return false;

        set({
            ...IDLE_STATE,
            status: RING_STATUS.LOADING,
            alarmId,
            notificationId: payload?.notificationId ?? null,
            title: payload?.title || 'Alarm',
            triggerAt: payload?.triggerAt ?? null,
            snoozeLimit: Math.max(0, toCount(payload?.snoozeLimit, 0)),
            snoozeIntervalMinutes: Math.max(1, toCount(payload?.snoozeIntervalMinutes, 5)),
        });

        get().loadChallenge();
        return true;
    },

    loadChallenge: async () => {
        const { alarmId } = get();
        if (!alarmId) return false;

        set({ status: RING_STATUS.LOADING, error: null });
        try {
            const challenge = await alarmApi.fetchChallenge(alarmId);
            set({
                status: RING_STATUS.CHALLENGE,
                challenge,
                // Client-side only: the server re-derives elapsed time from its own
                // issuance instant and takes the larger value, so this cannot buy time.
                issuedAt: Date.now(),
                progress: {
                    current: toCount(challenge?.current_step, 1),
                    total: toCount(challenge?.total_steps, 1),
                },
                error: null,
            });
            return true;
        } catch (error) {
            set({
                status: RING_STATUS.ERROR,
                error: readErrorDetail(error, 'Could not load the challenge.'),
            });
            return false;
        }
    },

    submitAnswer: async (answer) => {
        const { alarmId, busy, challenge, failedAttempts, issuedAt, status } = get();
        if (busy || status !== RING_STATUS.CHALLENGE) return null;

        set({ busy: true, feedback: null });
        const timeTaken = issuedAt
            ? Math.max(0, Math.round((Date.now() - issuedAt) / 1000))
            : 0;

        try {
            const result = await alarmApi.verifyChallenge(alarmId, {
                user_answer: String(answer ?? ''),
                time_taken_seconds: timeTaken,
                failed_attempts: failedAttempts,
                challenge_prompt: challenge?.prompt ?? '',
                challenge_difficulty: challenge?.difficulty ?? 'medium',
            });

            if (result?.is_dismissed) {
                set({
                    status: RING_STATUS.DISMISSED,
                    outcome: result,
                    challenge: null,
                    feedback: null,
                    busy: false,
                });
                await get().releaseDevice();
                return 'dismissed';
            }

            set({
                busy: false,
                feedback: result?.message ?? null,
                progress: {
                    current: toCount(result?.current_step, get().progress.current),
                    total: toCount(result?.total_steps, get().progress.total),
                },
            });
            await get().loadChallenge();
            return 'step_complete';
        } catch (error) {
            // A 400 is the documented rejection path (wrong answer, timeout, or a
            // session the server has since cleared) — the alarm keeps ringing and
            // the user gets a fresh challenge, so it is flow control, not an error.
            if (error?.response?.status === 400) {
                set({
                    busy: false,
                    failedAttempts: failedAttempts + 1,
                    feedback: readErrorDetail(error, 'Incorrect answer. Try again.'),
                });
                await get().loadChallenge();
                return 'rejected';
            }
            set({
                busy: false,
                error: readErrorDetail(error, 'Could not check that answer.'),
            });
            return 'error';
        }
    },

    snooze: async () => {
        const { alarmId, busy } = get();
        if (busy || !alarmId) return false;

        set({ busy: true, feedback: null });
        try {
            const alarm = await alarmApi.snoozeAlarm(alarmId);
            set({ snoozeCount: toCount(alarm?.total_snoozes, get().snoozeCount + 1) });
            await get().releaseDevice();
            get().stopRing();
            return true;
        } catch (error) {
            // 400 here is the snooze limit. Keep ringing and say so.
            set({
                busy: false,
                feedback: readErrorDetail(error, 'Could not snooze this alarm.'),
            });
            return false;
        }
    },

    giveUp: async () => {
        const { alarmId, busy } = get();
        if (busy || !alarmId) return false;

        set({ busy: true, feedback: null });
        try {
            const result = await alarmApi.failWake(alarmId);
            set({
                status: RING_STATUS.ABANDONED,
                outcome: result,
                challenge: null,
                busy: false,
            });
            await get().releaseDevice();
            return true;
        } catch (error) {
            set({
                busy: false,
                feedback: readErrorDetail(error, 'Could not close this alarm.'),
            });
            return false;
        }
    },

    /** Silence the device and re-arm from the server's new expansion. */
    releaseDevice: async () => {
        await runEffect('stop', get().notificationId);
        await runEffect('resync');
    },

    stopRing: () => set({ ...IDLE_STATE }),
}));

export default useRingStore;
