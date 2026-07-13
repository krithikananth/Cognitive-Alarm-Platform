/**
 * Zustand auth store — manages authentication state.
 */
import { create } from 'zustand';
import { authAPI, userAPI } from '../services/api';

// Best-effort sync of the browser's detected IANA timezone to the user's
// profile. Runs after every login so accounts created without a timezone
// (older sign-ups, OAuth sign-ups, or a stale/incorrect stored value) get
// self-corrected — otherwise alarm scheduling silently falls back to UTC
// and rings hours late/early relative to the user's local wall-clock time.
const syncBrowserTimezone = () => {
  try {
    const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (detected) {
      userAPI.updateUser({ timezone: detected }).catch(() => {});
    }
  } catch (e) {
    // Intl unsupported or blocked — nothing we can do, keep existing value.
  }
};

const useAuthStore = create((set, get) => ({
  // State
  user: (() => {
    try {
      const stored = localStorage.getItem('user');
      return stored && stored !== 'undefined' ? JSON.parse(stored) : null;
    } catch (e) {
      return null;
    }
  })(),
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
      let message = 'Registration failed';
      const detail = err.response?.data?.detail;
      if (Array.isArray(detail)) {
        message = detail.map(d => d.msg).join(', ');
      } else if (typeof detail === 'string') {
        message = detail;
      } else if (err.code === 'ERR_NETWORK' || err.message === 'Network Error') {
        message = 'Unable to reach the server. Check that the backend is running and CORS is enabled.';
      }
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
      syncBrowserTimezone();
      return { success: true };
    } catch (err) {
      let message = 'Login failed';
      const detail = err.response?.data?.detail;
      if (Array.isArray(detail)) {
        message = detail.map(d => d.msg).join(', ');
      } else if (typeof detail === 'string') {
        message = detail;
      }
      set({ error: message, isLoading: false });
      return { success: false, error: message };
    }
  },

  // ─── OAuth callback (tokens already issued by backend redirect) ───
  completeOAuthLogin: async ({ access_token, refresh_token }) => {
    set({ isLoading: true, error: null });
    try {
      localStorage.setItem('access_token', access_token);
      localStorage.setItem('refresh_token', refresh_token);

      const res = await authAPI.me();
      const user = res.data;
      localStorage.setItem('user', JSON.stringify(user));
      set({ user, isAuthenticated: true, isLoading: false });
      syncBrowserTimezone();
      return { success: true, user };
    } catch (err) {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      localStorage.removeItem('user');
      const message =
        (typeof err.response?.data?.detail === 'string' && err.response.data.detail) ||
        'Google sign-in failed';
      set({ user: null, isAuthenticated: false, error: message, isLoading: false });
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
      // /users/profile returns a flat bundle (user fields + nested profile)
      const bundle = res.data || {};
      const { profile: nestedProfile, ...userFields } = bundle;
      const nextUser = {
        ...get().user,
        ...userFields,
        timezone: userFields.timezone || nestedProfile?.timezone || get().user?.timezone,
      };
      localStorage.setItem('user', JSON.stringify(nextUser));
      set({ profile: nestedProfile || bundle, user: nextUser });
    } catch (err) {
      console.error('Failed to fetch profile:', err);
    }
  },

  // ─── Clear Error ───
  clearError: () => set({ error: null }),
}));

export default useAuthStore;
