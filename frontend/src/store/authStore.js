/**
 * Zustand auth store — manages authentication state.
 */
import { create } from 'zustand';
import { authAPI, userAPI } from '../services/api';

const useAuthStore = create((set, get) => ({
  // State
  user: JSON.parse(localStorage.getItem('user') || 'null'),
  profile: null,
  isAuthenticated: !!localStorage.getItem('access_token'),
  isLoading: false,
  error: null,

  // ─── Register ───
  register: async (data) => {
    set({ isLoading: true, error: null });
    try {
      await authAPI.register(data);
      set({ isLoading: false });
      return { success: true };
    } catch (err) {
      const message = err.response?.data?.detail || 'Registration failed';
      set({ error: message, isLoading: false });
      return { success: false, error: message };
    }
  },

  // ─── Login ───
  login: async (data) => {
    set({ isLoading: true, error: null });
    try {
      const res = await authAPI.login(data);
      const { access_token, refresh_token, user } = res.data;
      localStorage.setItem('access_token', access_token);
      localStorage.setItem('refresh_token', refresh_token);
      localStorage.setItem('user', JSON.stringify(user));
      set({ user, isAuthenticated: true, isLoading: false });
      return { success: true };
    } catch (err) {
      const message = err.response?.data?.detail || 'Login failed';
      set({ error: message, isLoading: false });
      return { success: false, error: message };
    }
  },

  // ─── Logout ───
  logout: async () => {
    try {
      await authAPI.logout();
    } catch (e) {
      // Ignore errors on logout
    }
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
    localStorage.removeItem('user');
    set({ user: null, profile: null, isAuthenticated: false });
  },

  // ─── Fetch Profile ───
  fetchProfile: async () => {
    try {
      const res = await userAPI.getProfile();
      set({ profile: res.data, user: res.data.user });
    } catch (err) {
      console.error('Failed to fetch profile:', err);
    }
  },

  // ─── Clear Error ───
  clearError: () => set({ error: null }),
}));

export default useAuthStore;
