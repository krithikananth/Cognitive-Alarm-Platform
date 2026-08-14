// Axios instance + Bearer auth interceptor + single-flight refresh (spec §5, task 4).
import axios from 'axios';

import { API_BASE_URL, REQUEST_TIMEOUT_MS, requestRefresh } from './refreshClient';
import { clearTokens, getAccessToken, getRefreshToken, saveTokens } from './tokens';

const api = axios.create({
    baseURL: API_BASE_URL,
    headers: { 'Content-Type': 'application/json' },
    timeout: REQUEST_TIMEOUT_MS,
});

// A 401 from these is a real answer, not an expired session. Retrying them
// would turn a rejected password into an infinite refresh loop.
const SKIP_REFRESH_PATHS = [
    '/auth/login',
    '/auth/register',
    '/auth/refresh',
    '/auth/forgot-password',
    '/auth/reset-password',
    '/auth/verify-email',
    '/auth/resend-verification',
];

function shouldSkipRefresh(url = '') {
    return SKIP_REFRESH_PATHS.some((path) => String(url).includes(path));
}

let refreshPromise = null;
let onSessionExpired = () => { };

/** Registered by the auth store so an unrecoverable 401 can route back to Login. */
export function setSessionExpiredHandler(handler) {
    onSessionExpired = typeof handler === 'function' ? handler : () => { };
}

/**
 * Refresh the token pair, sharing one in-flight request across callers.
 *
 * Without this guard, several requests failing at once each spend the refresh
 * token; the server revokes the previous access token on every rotation, so the
 * later responses would invalidate the session the earlier ones just renewed.
 */
function refreshSession() {
    if (!refreshPromise) {
        refreshPromise = (async () => {
            const refreshToken = await getRefreshToken();
            if (!refreshToken) {
                throw new Error('No refresh token stored');
            }
            const tokens = await requestRefresh(refreshToken);
            await saveTokens(tokens);
            return tokens.access_token;
        })().finally(() => {
            refreshPromise = null;
        });
    }
    return refreshPromise;
}

api.interceptors.request.use(async (config) => {
    const token = await getAccessToken();
    if (token) {
        config.headers = config.headers || {};
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

api.interceptors.response.use(
    (response) => response,
    async (error) => {
        const original = error.config;
        const isExpiredSession =
            original &&
            error.response?.status === 401 &&
            !original._retry &&
            !shouldSkipRefresh(original.url);

        if (!isExpiredSession) {
            return Promise.reject(error);
        }

        original._retry = true;
        try {
            const accessToken = await refreshSession();
            original.headers = {
                ...(original.headers || {}),
                Authorization: `Bearer ${accessToken}`,
            };
            return api(original);
        } catch (refreshError) {
            await clearTokens();
            onSessionExpired();
            return Promise.reject(refreshError);
        }
    }
);

/**
 * Turn an axios failure into one line a user can act on.
 *
 * FastAPI is not uniform here: `HTTPException` sends `detail` as a string, while
 * a 422 sends a list of validation objects. Rendering the raw value would put
 * `[object Object]` on screen.
 */
export function readErrorDetail(error, fallback = 'Something went wrong.') {
    if (error?.response?.status === 429) {
        const retryAfter = Number(error.response?.headers?.['retry-after']);
        if (Number.isFinite(retryAfter) && retryAfter > 0) {
            return `Too many attempts. Try again in ${retryAfter} seconds.`;
        }
    }

    const detail = error?.response?.data?.detail;
    if (typeof detail === 'string' && detail.trim()) {
        return detail;
    }
    if (Array.isArray(detail)) {
        const messages = detail
            .map((item) => (typeof item?.msg === 'string' ? item.msg : null))
            .filter(Boolean);
        if (messages.length) {
            return messages.join('\n');
        }
    }
    if (error?.message === 'Network Error') {
        return 'Cannot reach the server. Check the connection and try again.';
    }
    return fallback;
}

export { API_BASE_URL };
export default api;
