// Zustand auth store: tokens in SecureStore, current user (spec §5, task 4).
import { create } from 'zustand';

import * as authApi from '../api/auth';
import { syncTimezone } from '../api/profile';
import { readErrorDetail, setSessionExpiredHandler } from '../api/client';
import { clearTokens, getAccessToken, saveTokens } from '../api/tokens';
import { deviceTimezone } from '../utils/timezone';

export const AUTH_STATUS = {
    UNKNOWN: 'unknown',
    ANONYMOUS: 'anonymous',
    AUTHENTICATED: 'authenticated',
};

export const useAuthStore = create((set, get) => ({
    status: AUTH_STATUS.UNKNOWN,
    user: null,
    error: null,
    submitting: false,

    clearError: () => set({ error: null }),

    /**
     * Decide on cold start whether the stored tokens still represent a session.
     *
     * A 401 here is normal (the access token outlives the app rarely); the client
     * interceptor transparently refreshes, and only an unrecoverable failure
     * drops through to anonymous.
     */
    restore: async () => {
        const token = await getAccessToken();
        if (!token) {
            set({ status: AUTH_STATUS.ANONYMOUS, user: null });
            return;
        }
        try {
            const user = await authApi.me();
            set({ status: AUTH_STATUS.AUTHENTICATED, user, error: null });
        } catch {
            await clearTokens();
            set({ status: AUTH_STATUS.ANONYMOUS, user: null });
        }
    },

    login: async (email, password) => {
        set({ submitting: true, error: null });
        try {
            const payload = await authApi.login(email, password);
            await saveTokens(payload);
            set({
                status: AUTH_STATUS.AUTHENTICATED,
                user: payload.user ?? null,
                submitting: false,
            });
            // Best effort: a failed timezone sync must not strand a valid session.
            try {
                await syncTimezone(deviceTimezone());
            } catch {
                /* retried on the next successful login */
            }
            return true;
        } catch (error) {
            set({
                submitting: false,
                error: readErrorDetail(error, 'Could not sign in.'),
            });
            return false;
        }
    },

    /** Register, then sign in — `/auth/register` returns a user, not tokens. */
    register: async ({ email, username, password, fullName }) => {
        set({ submitting: true, error: null });
        try {
            await authApi.register({
                email,
                username,
                password,
                fullName,
                timezone: deviceTimezone(),
            });
        } catch (error) {
            set({
                submitting: false,
                error: readErrorDetail(error, 'Could not create the account.'),
            });
            return false;
        }
        set({ submitting: false });
        return get().login(email, password);
    },

    logout: async () => {
        try {
            await authApi.logout();
        } catch {
            // The local session is dropped regardless; an unreachable server must
            // never trap the user in a signed-in shell.
        }
        await clearTokens();
        set({ status: AUTH_STATUS.ANONYMOUS, user: null, error: null });
    },

    /** Called by the API client when a refresh fails and the session is gone. */
    handleSessionExpired: () => {
        set({
            status: AUTH_STATUS.ANONYMOUS,
            user: null,
            error: 'Your session expired. Please sign in again.',
        });
    },
}));

setSessionExpiredHandler(() => useAuthStore.getState().handleSessionExpired());

export default useAuthStore;
