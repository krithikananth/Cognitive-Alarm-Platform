/**
 * Zustand auth store — manages authentication state.
 *
 * Sessions live in HttpOnly cookies set by the backend; this store only keeps
 * the non-sensitive user object and a session marker.
 */
import { create } from 'zustand';
import {
  authAPI,
  userAPI,
  markSessionActive,
  hasActiveSession,
  clearSessionFlag,
} from '../services/api';

// Best-effort sync of the browser's detected IANA timezone to the user's
// profile. Runs after every login so accounts created without a timezone
// (older sign-ups, OAuth sign-ups, or a stale/incorrect stored value) get
// self-corrected — otherwise alarm scheduling silently falls back to UTC
// and rings hours late/early relative to the user's local wall-clock time.
const syncBrowserTimezone = async () => {
  try {
    const detected = Intl.DateTimeFormat().resolvedOptions().timeZone;
    if (detected) {
      await userAPI.updateUser({ timezone: detected });
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
  isAuthenticated: hasActiveSession(),
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
      const { user } = res.data;
      markSessionActive();
      localStorage.setItem('user', JSON.stringify(user));
      set({ user, isAuthenticated: true, isLoading: false });
      // Sync IANA timezone to profile, then refresh auth user so Profile/UI
      // see timezone immediately (login payload does not include it).
      try {
        await syncBrowserTimezone();
      } catch (e) {
        // Soft-fail — login already succeeded.
      }
      try {
        await get().fetchProfile();
      } catch (e) {
        // Soft-fail — user can still use the app.
      }
      return { success: true, user: get().user || user };
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

  // ─── OAuth callback (session cookies already set by the backend redirect) ───
  completeOAuthLogin: async () => {
    set({ isLoading: true, error: null });
    try {
      const res = await authAPI.me();
      const user = res.data;
      markSessionActive();
      localStorage.setItem('user', JSON.stringify(user));
      set({ user, isAuthenticated: true, isLoading: false });
      try {
        await syncBrowserTimezone();
      } catch (e) {
        // Soft-fail
      }
      try {
        await get().fetchProfile();
      } catch (e) {
        // Soft-fail
      }
      return { success: true, user: get().user || user };
    } catch (err) {
      clearSessionFlag();
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
      const { unregisterNotifications } = await import('../services/notificationService');
      await unregisterNotifications();
    } catch (e) {
      // Ignore notification cleanup errors
    }
    try {
      await authAPI.logout();
    } catch (e) {
      // Ignore errors on logout
    }
    clearSessionFlag();
    localStorage.removeItem('user');
    set({ user: null, profile: null, isAuthenticated: false });
  },

  // ─── Logout everywhere ───
  // Revokes every issued token for the account server-side, so sessions on
  // other devices die immediately instead of living until their token expires.
  logoutAll: async () => {
    try {
      const { unregisterNotifications } = await import('../services/notificationService');
      await unregisterNotifications();
    } catch (e) {
      // Ignore notification cleanup errors
    }
    let revoked = true;
    try {
      await authAPI.logoutAll();
    } catch (e) {
      // The local session is still cleared below, but say so honestly: the
      // other devices may still be signed in.
      revoked = false;
    }
    clearSessionFlag();
    localStorage.removeItem('user');
    set({ user: null, profile: null, isAuthenticated: false });
    return { success: revoked };
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
