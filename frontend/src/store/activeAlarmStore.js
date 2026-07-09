import { create } from 'zustand';
import { alarmAPI } from '../services/api';

const useActiveAlarmStore = create((set, get) => ({
  ringingAlarmId: null,
  isRinging: false,
  challenge: null,
  isLoading: false,
  error: null,

  triggerAlarm: async (alarmId) => {
    // Only trigger if not already ringing
    if (get().isRinging) return;
    
    set({ ringingAlarmId: alarmId, isRinging: true, isLoading: true, error: null });
    try {
      const res = await alarmAPI.getChallenge(alarmId);
      set({ challenge: res.data, isLoading: false });
    } catch (err) {
      set({ error: "Failed to load challenge", isLoading: false });
    }
  },

  snoozeAlarm: async () => {
    const alarmId = get().ringingAlarmId;
    if (!alarmId) return;
    
    set({ isLoading: true });
    try {
      await alarmAPI.snooze(alarmId);
      set({ ringingAlarmId: null, isRinging: false, challenge: null, isLoading: false });
      return { success: true };
    } catch (err) {
      const msg = err.response?.data?.detail || "Failed to snooze";
      set({ error: msg, isLoading: false });
      return { success: false, error: msg };
    }
  },

  verifyAndDismiss: async (userAnswer, timeTakenSeconds, failedAttempts) => {
    const alarmId = get().ringingAlarmId;
    const challenge = get().challenge;
    if (!alarmId || !challenge) return { success: false };
    
    set({ isLoading: true });
    try {
      await alarmAPI.verifyChallenge(alarmId, { 
        expected_answer: challenge.answer,
        user_answer: String(userAnswer),
        time_taken_seconds: timeTakenSeconds || 0,
        failed_attempts: failedAttempts || 0
      });
      // Verification succeeded, backend already dismissed the alarm
      set({ ringingAlarmId: null, isRinging: false, challenge: null, isLoading: false });
      return { success: true };
    } catch (err) {
      const msg = err.response?.data?.detail || "Incorrect answer. Try again.";
      set({ error: msg, isLoading: false });
      
      // If incorrect, fetch a new challenge
      try {
        const res = await alarmAPI.getChallenge(alarmId);
        set({ challenge: res.data });
      } catch (e) {}
      
      return { success: false, error: msg };
    }
  }
}));

export default useActiveAlarmStore;
