/**
 * Active Alarm Store — manages the ringing alarm state, multi-step
 * challenge flow, countdown timer, and snooze restrictions.
 */
import { create } from 'zustand';
import { alarmAPI } from '../services/api';
import {
  trackAlarmDismissed,
  trackAlarmSnoozed,
  trackChallengeCompleted,
  trackChallengeFailed,
  trackWakeVerified,
} from '../services/analyticsTracker';
import useAlarmStore from './alarmStore';

const useActiveAlarmStore = create((set, get) => ({
  // ── Core state ──
  ringingAlarmId: null,
  isRinging: false,
  challenge: null,       // { type, prompt, answer, options, difficulty, time_limit_seconds }
  isLoading: false,
  error: null,

  // ── Multi-step / consecutive state (server-authoritative) ──
  currentStep: 1,
  totalSteps: 1,         // from alarm.challenge_count / server required_correct
  challengeCount: 1,
  consecutiveCorrect: 0,

  // ── Snooze / anti-snooze state ──
  canSnooze: true,
  snoozeCount: 0,
  snoozeLimit: 3,
  snoozeIntervalMinutes: 5,
  escalationLevel: 0,
  nextChallengeDifficulty: null,
  antiSnoozeEnforced: false,

  // ── Timer state ──
  timeLeft: 30,          // countdown in seconds
  timerInterval: null,

  // ── Analytics ──
  failedAttempts: 0,
  startTime: null,
  lastWakefulness: null,

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
      // Challenge payload includes server progress; snooze-info for escalation
      const [challengeRes, alarmRes, snoozeRes] = await Promise.all([
        alarmAPI.getChallenge(alarmId),
        alarmAPI.get(alarmId),
        alarmAPI.getSnoozeInfo(alarmId).catch(() => null),
      ]);

      const alarm = alarmRes.data;
      const challenge = challengeRes.data;
      const snooze = snoozeRes?.data;
      const timeLimit = challenge.time_limit_seconds || 30;
      const totalSteps =
        challenge.required_correct || alarm.challenge_count || 1;
      const consecutive = challenge.consecutive_correct || 0;

      set({
        challenge,
        isLoading: false,
        totalSteps,
        challengeCount: totalSteps,
        consecutiveCorrect: consecutive,
        currentStep: consecutive + 1,
        canSnooze: snooze
          ? snooze.can_snooze
          : (alarm.total_snoozes || 0) < (alarm.snooze_limit ?? 3),
        snoozeCount: snooze?.snooze_count ?? alarm.total_snoozes ?? 0,
        snoozeLimit: snooze?.snooze_limit ?? alarm.snooze_limit ?? 3,
        snoozeIntervalMinutes:
          snooze?.snooze_interval_minutes ?? alarm.snooze_interval_minutes ?? 5,
        escalationLevel:
          snooze?.escalation_level ?? challenge.escalation_level ?? 0,
        nextChallengeDifficulty:
          snooze?.next_challenge_difficulty ?? challenge.difficulty ?? null,
        antiSnoozeEnforced: snooze
          ? Boolean(snooze.anti_snooze_enforced)
          : (alarm.total_snoozes || 0) >= (alarm.snooze_limit ?? 3),
        timeLeft: timeLimit,
        startTime: Date.now(),
        lastWakefulness: null,
      });

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
      const prevSnoozeCount = get().snoozeCount;
      await alarmAPI.snooze(alarmId);
      get()._stopTimer();
      const newSnoozeCount = prevSnoozeCount + 1;
      const limit = get().snoozeLimit;
      const canStillSnooze = newSnoozeCount < limit;
      set({
        ringingAlarmId: null,
        isRinging: false,
        challenge: null,
        isLoading: false,
        currentStep: 1,
        failedAttempts: 0,
        snoozeCount: newSnoozeCount,
        escalationLevel: newSnoozeCount,
        canSnooze: canStillSnooze,
        antiSnoozeEnforced: !canStillSnooze,
      });
      trackAlarmSnoozed(
        alarmId,
        {
          snooze_count: newSnoozeCount,
          snooze_limit: limit,
          interval_minutes: get().snoozeIntervalMinutes,
          escalation_level: newSnoozeCount,
        },
        `${alarmId}:snooze:${newSnoozeCount}`
      );
      try {
        await useAlarmStore.getState().fetchAlarms();
      } catch (e) { /* ignore */ }
      return {
        success: true,
        snoozeCount: newSnoozeCount,
        snoozeLimit: limit,
        intervalMinutes: get().snoozeIntervalMinutes,
        escalationLevel: newSnoozeCount,
      };
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

    const challengeStep = get().currentStep;
    const attemptNonce = `${Date.now()}:${get().failedAttempts}:${timeTaken}`;
    const challengeMeta = {
      challenge_type: challenge.type || null,
      challenge_difficulty: challenge.difficulty || 'medium',
      challenge_step: challengeStep,
      challenge_total_steps: get().totalSteps,
      time_taken_seconds: timeTaken,
      failed_attempts: failedAttempts || 0,
      attempt_nonce: attemptNonce,
    };

    set({ isLoading: true, error: null });
    try {
      const res = await alarmAPI.verifyChallenge(alarmId, {
        // Server verifies against its stored session — do not trust client answer
        user_answer: String(userAnswer),
        time_taken_seconds: timeTaken,
        failed_attempts: failedAttempts || 0,
        challenge_prompt: challenge.prompt || "",
        challenge_difficulty: challenge.difficulty || "medium",
        challenge_step: challengeStep,
        challenge_total_steps: get().totalSteps,
      });

      const data = res.data;

      trackChallengeCompleted(
        alarmId,
        challengeMeta,
        `${alarmId}:challenge_ok:${challengeStep}:${attemptNonce}`
      );

      if (data.is_dismissed) {
        get()._stopTimer();
        const wakePayload = {
          dismiss_method: 'challenge',
          wakefulness_score: data.wakefulness?.score ?? null,
          wakefulness_level: data.wakefulness?.level ?? null,
          consecutive_correct: data.consecutive_correct ?? get().totalSteps,
        };
        trackAlarmDismissed(
          alarmId,
          wakePayload,
          `${alarmId}:dismiss:${attemptNonce}`
        );
        trackWakeVerified(
          alarmId,
          wakePayload,
          `${alarmId}:wake:${attemptNonce}`
        );
        set({
          ringingAlarmId: null,
          isRinging: false,
          challenge: null,
          isLoading: false,
          currentStep: 1,
          consecutiveCorrect: 0,
          failedAttempts: 0,
          lastWakefulness: data.wakefulness || null,
        });
        try {
          // Refresh from server — recurring alarms stay active with a new
          // next_trigger_at; only one-time alarms are deactivated.
          await useAlarmStore.getState().fetchAlarms();
        } catch (e) { /* ignore refresh errors */ }
        return {
          success: true,
          dismissed: true,
          message: data.message,
          wakefulness: data.wakefulness,
        };
      }

      // Server-tracked consecutive progress — fetch next puzzle
      const nextStep = data.next_step || (data.consecutive_correct || 0) + 1;
      const totalSteps = data.total_steps || data.required_correct || get().totalSteps;
      set({
        currentStep: nextStep,
        totalSteps,
        consecutiveCorrect: data.consecutive_correct || 0,
        isLoading: true,
        error: null,
        lastWakefulness: data.wakefulness || null,
      });

      const nextChallengeRes = await alarmAPI.getChallenge(alarmId);
      const nextChallenge = nextChallengeRes.data;
      const nextTimeLimit = nextChallenge.time_limit_seconds || 30;

      set({
        challenge: nextChallenge,
        isLoading: false,
        startTime: Date.now(),
        timeLeft: nextTimeLimit,
        currentStep:
          (nextChallenge.consecutive_correct || data.consecutive_correct || 0) + 1,
        totalSteps:
          nextChallenge.required_correct || totalSteps,
      });
      get()._startTimer(nextTimeLimit);

      return {
        success: true,
        dismissed: false,
        message: data.message,
        step: nextStep,
        totalSteps,
        wakefulness: data.wakefulness,
      };
    } catch (err) {
      const payload = err.response?.data || {};
      const msg =
        (typeof payload.detail === 'string' ? payload.detail : null) ||
        "Incorrect answer. Try again.";
      const streakReset = payload.streak_reset === true;

      // Only treat verification/validation failures as challenge fails.
      // Network/5xx errors should not emit a failed-challenge analytics event.
      const status = err.response?.status;
      if (status === 400 || status === 422) {
        trackChallengeFailed(
          alarmId,
          challengeMeta,
          `${alarmId}:challenge_fail:${challengeStep}:${attemptNonce}`
        );
      }

      set({
        error: msg,
        isLoading: false,
        failedAttempts: get().failedAttempts + 1,
        consecutiveCorrect: streakReset ? 0 : get().consecutiveCorrect,
        currentStep: streakReset ? 1 : get().currentStep,
        lastWakefulness: payload.wakefulness || null,
      });

      // Fetch a new challenge on wrong answer / timeout (streak may have reset)
      try {
        const res = await alarmAPI.getChallenge(alarmId);
        const newChallenge = res.data;
        const nextTimeLimit = newChallenge.time_limit_seconds || 30;
        set({
          challenge: newChallenge,
          startTime: Date.now(),
          timeLeft: nextTimeLimit,
          consecutiveCorrect: newChallenge.consecutive_correct || 0,
          currentStep: (newChallenge.consecutive_correct || 0) + 1,
          totalSteps:
            newChallenge.required_correct || get().totalSteps,
        });
        get()._startTimer(nextTimeLimit);
      } catch (e) { /* ignore fetch error */ }

      return { success: false, error: msg, streakReset, wakefulness: payload.wakefulness };
    }
  },
}));

export default useActiveAlarmStore;
