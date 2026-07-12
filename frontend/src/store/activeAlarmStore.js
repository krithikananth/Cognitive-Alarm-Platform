/**
 * Active Alarm Store — manages the ringing alarm state, multi-step
 * challenge flow, countdown timer, and snooze restrictions.
 */
import { create } from 'zustand';
import { alarmAPI } from '../services/api';
import useAlarmStore from './alarmStore';

const useActiveAlarmStore = create((set, get) => ({
  // ── Core state ──
  ringingAlarmId: null,
  isRinging: false,
  challenge: null,       // { type, prompt, answer, options, difficulty, time_limit_seconds }
  isLoading: false,
  error: null,

  // ── Multi-step state ──
  currentStep: 1,
  totalSteps: 1,         // from alarm.challenge_count
  challengeCount: 1,

  // ── Snooze state ──
  canSnooze: true,
  snoozeCount: 0,
  snoozeLimit: 3,

  // ── Timer state ──
  timeLeft: 30,          // countdown in seconds
  timerInterval: null,

  // ── Analytics ──
  failedAttempts: 0,
  startTime: null,

  // ─────────────────────────────────────────────────────────
  // TRIGGER — alarm starts ringing
  // ─────────────────────────────────────────────────────────
  triggerAlarm: async (alarmId) => {
    if (get().isRinging) return;

    set({
      ringingAlarmId: alarmId,
      isRinging: true,
      isLoading: true,
      error: null,
      currentStep: 1,
      failedAttempts: 0,
      startTime: Date.now(),
    });

    try {
      // Fetch alarm details to get challenge_count and snooze info
      const [challengeRes, alarmRes] = await Promise.all([
        alarmAPI.getChallenge(alarmId),
        alarmAPI.get(alarmId),
      ]);

      const alarm = alarmRes.data;
      const challenge = challengeRes.data;
      const timeLimit = challenge.time_limit_seconds || 30;

      set({
        challenge,
        isLoading: false,
        totalSteps: alarm.challenge_count || 1,
        challengeCount: alarm.challenge_count || 1,
        canSnooze: (alarm.total_snoozes || 0) < (alarm.snooze_limit || 3),
        snoozeCount: alarm.total_snoozes || 0,
        snoozeLimit: alarm.snooze_limit || 3,
        timeLeft: timeLimit,
        startTime: Date.now(),
      });

      // Start countdown timer
      get()._startTimer(timeLimit);
    } catch (err) {
      set({ error: "Failed to load challenge", isLoading: false });
    }
  },

  // ─────────────────────────────────────────────────────────
  // COUNTDOWN TIMER
  // ─────────────────────────────────────────────────────────
  _startTimer: (seconds) => {
    // Clear any existing timer
    const existing = get().timerInterval;
    if (existing) clearInterval(existing);

    set({ timeLeft: seconds });

    const interval = setInterval(() => {
      const current = get().timeLeft;
      if (current <= 1) {
        clearInterval(interval);
        set({ timeLeft: 0, timerInterval: null });
        // Time expired — don't auto-fail, just show 0
      } else {
        set({ timeLeft: current - 1 });
      }
    }, 1000);

    set({ timerInterval: interval });
  },

  _stopTimer: () => {
    const interval = get().timerInterval;
    if (interval) clearInterval(interval);
    set({ timerInterval: null });
  },

  // ─────────────────────────────────────────────────────────
  // SNOOZE — with restriction
  // ─────────────────────────────────────────────────────────
  snoozeAlarm: async () => {
    const alarmId = get().ringingAlarmId;
    if (!alarmId) return { success: false };
    if (!get().canSnooze) {
      set({ error: "Maximum snooze limit reached. Solve the challenge!" });
      return { success: false, error: "Snooze limit reached" };
    }

    set({ isLoading: true });
    try {
      await alarmAPI.snooze(alarmId);
      get()._stopTimer();
      const newSnoozeCount = get().snoozeCount + 1;
      set({
        ringingAlarmId: null,
        isRinging: false,
        challenge: null,
        isLoading: false,
        currentStep: 1,
        failedAttempts: 0,
        snoozeCount: newSnoozeCount,
        canSnooze: newSnoozeCount < get().snoozeLimit,
      });
      try {
        await useAlarmStore.getState().fetchAlarms();
      } catch (e) { /* ignore */ }
      return { success: true };
    } catch (err) {
      const msg = err.response?.data?.detail || "Failed to snooze";
      set({ error: msg, isLoading: false, canSnooze: false });
      return { success: false, error: msg };
    }
  },

  // ─────────────────────────────────────────────────────────
  // VERIFY — with multi-step and per-attempt logging
  // ─────────────────────────────────────────────────────────
  verifyAndDismiss: async (userAnswer, timeTakenSeconds, failedAttempts) => {
    const alarmId = get().ringingAlarmId;
    const challenge = get().challenge;
    if (!alarmId || !challenge) return { success: false };

    // Prefer countdown-based elapsed time (avoids stale startTime refs)
    const timeLimit = challenge.time_limit_seconds || 30;
    const elapsedFromTimer = Math.max(0, timeLimit - (get().timeLeft ?? timeLimit));
    const timeTaken = Number.isFinite(timeTakenSeconds)
      ? Math.max(0, timeTakenSeconds)
      : elapsedFromTimer;

    set({ isLoading: true, error: null });
    try {
      const res = await alarmAPI.verifyChallenge(alarmId, {
        // Server verifies against its stored session — do not trust client answer
        user_answer: String(userAnswer),
        time_taken_seconds: timeTaken,
        failed_attempts: failedAttempts || 0,
        challenge_prompt: challenge.prompt || "",
        challenge_difficulty: challenge.difficulty || "medium",
        challenge_step: get().currentStep,
        challenge_total_steps: get().totalSteps,
      });

      const data = res.data;

      if (data.is_dismissed) {
        // All steps done — alarm dismissed
        get()._stopTimer();
        const dismissedId = alarmId;
        set({
          ringingAlarmId: null,
          isRinging: false,
          challenge: null,
          isLoading: false,
          currentStep: 1,
          failedAttempts: 0,
        });
        // Refresh alarm list so AlarmWatcher does not re-fire from stale state
        try {
          await useAlarmStore.getState().fetchAlarms();
          useAlarmStore.setState((state) => ({
            alarms: state.alarms.map((a) =>
              a.id === dismissedId
                ? { ...a, is_active: false, next_trigger_at: null }
                : a
            ),
          }));
        } catch (e) { /* ignore refresh errors */ }
        return { success: true, dismissed: true, message: data.message };
      }

      // Multi-step: move to next step, fetch a new challenge
      const nextStep = data.next_step;
      set({ currentStep: nextStep, isLoading: true, error: null });

      const nextChallengeRes = await alarmAPI.getChallenge(alarmId);
      const nextChallenge = nextChallengeRes.data;
      const nextTimeLimit = nextChallenge.time_limit_seconds || 30;

      set({
        challenge: nextChallenge,
        isLoading: false,
        startTime: Date.now(),
        timeLeft: nextTimeLimit,
      });
      get()._startTimer(nextTimeLimit);

      return {
        success: true,
        dismissed: false,
        message: data.message,
        step: nextStep,
        totalSteps: data.total_steps,
      };
    } catch (err) {
      const msg = err.response?.data?.detail || "Incorrect answer. Try again.";
      set({
        error: msg,
        isLoading: false,
        failedAttempts: get().failedAttempts + 1,
      });

      // Fetch a new challenge on wrong answer / timeout
      try {
        const res = await alarmAPI.getChallenge(alarmId);
        const newChallenge = res.data;
        const nextTimeLimit = newChallenge.time_limit_seconds || 30;
        set({
          challenge: newChallenge,
          startTime: Date.now(),
          timeLeft: nextTimeLimit,
        });
        get()._startTimer(nextTimeLimit);
      } catch (e) { /* ignore fetch error */ }

      return { success: false, error: msg };
    }
  },
}));

export default useActiveAlarmStore;
