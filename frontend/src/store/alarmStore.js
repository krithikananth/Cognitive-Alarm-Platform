/**
 * Zustand alarm store — manages alarm CRUD state.
 */
import { create } from 'zustand';
import { alarmAPI } from '../services/api';

const useAlarmStore = create((set, get) => ({
  // State
  alarms: [],
  currentAlarm: null,
  upcoming: [],
  history: [],
  totalHistory: 0,
  isLoading: false,
  error: null,

  // ─── Fetch All Alarms ───
  fetchAlarms: async (activeOnly = false) => {
    set({ isLoading: true });
    try {
      const res = await alarmAPI.list(activeOnly);
      set({ alarms: res.data.alarms, isLoading: false });
    } catch (err) {
      set({ error: err.response?.data?.detail || 'Failed to fetch alarms', isLoading: false });
    }
  },

  // ─── Create Alarm ───
  createAlarm: async (data) => {
    set({ isLoading: true, error: null });
    try {
      const res = await alarmAPI.create(data);
      set((state) => ({
        alarms: [...state.alarms, res.data],
        isLoading: false,
      }));
      return { success: true, alarm: res.data };
    } catch (err) {
      const message = err.response?.data?.detail || 'Failed to create alarm';
      set({ error: message, isLoading: false });
      return { success: false, error: message };
    }
  },

  // ─── Update Alarm ───
  updateAlarm: async (id, data) => {
    set({ isLoading: true, error: null });
    try {
      const res = await alarmAPI.update(id, data);
      set((state) => ({
        alarms: state.alarms.map((a) => (a.id === id ? res.data : a)),
        isLoading: false,
      }));
      return { success: true, alarm: res.data };
    } catch (err) {
      set({ error: err.response?.data?.detail, isLoading: false });
      return { success: false };
    }
  },

  // ─── Delete Alarm ───
  deleteAlarm: async (id) => {
    try {
      await alarmAPI.delete(id);
      set((state) => ({
        alarms: state.alarms.filter((a) => a.id !== id),
      }));
      return { success: true };
    } catch (err) {
      return { success: false, error: err.response?.data?.detail };
    }
  },

  // ─── Toggle Alarm ───
  toggleAlarm: async (id, isActive) => {
    try {
      const res = await alarmAPI.toggle(id, isActive);
      set((state) => ({
        alarms: state.alarms.map((a) => (a.id === id ? res.data : a)),
      }));
    } catch (err) {
      console.error('Toggle failed:', err);
    }
  },

  // ─── Fetch Upcoming ───
  fetchUpcoming: async () => {
    try {
      const res = await alarmAPI.upcoming();
      set({ upcoming: res.data });
    } catch (err) {
      console.error('Fetch upcoming failed:', err);
    }
  },

  // ─── Fetch Wake Confirmations (dismiss history) ───
  fetchHistory: async (limit = 50) => {
    try {
      const res = await alarmAPI.getWakeConfirmations(limit);
      const events = res.data?.events || res.data || [];
      set({
        history: Array.isArray(events) ? events : [],
        totalHistory: res.data?.total ?? (Array.isArray(events) ? events.length : 0),
      });
    } catch (err) {
      console.error('Fetch history failed:', err);
    }
  },

  // ─── Clear Error ───
  clearError: () => set({ error: null }),
}));

export default useAlarmStore;
