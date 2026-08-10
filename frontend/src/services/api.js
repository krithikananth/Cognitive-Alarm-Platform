/**
 * Axios API client with JWT interceptor for auto-refresh.
 */
import axios from 'axios';
import { jwtDecode } from 'jwt-decode';

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000/api/v1';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  timeout: 15000,
});

/** Shared in-flight refresh so concurrent 401s / expiry checks share one call. */
let refreshPromise = null;

const AUTH_SKIP_REFRESH_PATHS = [
  '/auth/login',
  '/auth/register',
  '/auth/oauth/',
  '/auth/forgot-password',
  '/auth/reset-password',
  '/auth/verify-email',
  '/auth/resend-verification',
  '/auth/refresh',
];

function shouldSkipTokenRefresh(url = '') {
  return AUTH_SKIP_REFRESH_PATHS.some((path) => url.includes(path));
}

function isAccessTokenValid(token, skewMs = 30000) {
  if (!token) return false;
  try {
    const { exp } = jwtDecode(token);
    if (!exp) return false;
    return exp * 1000 > Date.now() + skewMs;
  } catch {
    return false;
  }
}

/**
 * Refresh access token. Concurrent callers share one in-flight request.
 */
async function refreshAccessToken() {
  const refreshToken = localStorage.getItem('refresh_token');
  if (!refreshToken) {
    throw new Error('No refresh token');
  }

  if (!refreshPromise) {
    refreshPromise = axios
      .post(`${API_BASE}/auth/refresh`, { refresh_token: refreshToken })
      .then(({ data }) => {
        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);
        return data.access_token;
      })
      .finally(() => {
        refreshPromise = null;
      });
  }

  return refreshPromise;
}

/**
 * Return a usable access token, refreshing once if expired/near-expiry.
 * Concurrent callers await the same refreshPromise (no stampede).
 */
async function getValidAccessToken() {
  const accessToken = localStorage.getItem('access_token');
  if (isAccessTokenValid(accessToken)) {
    return accessToken;
  }

  if (!localStorage.getItem('refresh_token')) {
    return accessToken; // may be missing/expired; caller still attaches if present
  }

  return refreshAccessToken();
}

function clearSessionAndRedirect() {
  localStorage.removeItem('access_token');
  localStorage.removeItem('refresh_token');
  localStorage.removeItem('user');
  window.location.href = '/login';
}

// ─── Request interceptor: attach JWT (refresh proactively if expired) ───
api.interceptors.request.use(
  async (config) => {
    if (shouldSkipTokenRefresh(config.url)) {
      const token = localStorage.getItem('access_token');
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
      return config;
    }

    try {
      const token = await getValidAccessToken();
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    } catch {
      // Refresh failed here — still attach existing token if any; response
      // interceptor will clear the session on 401.
      const token = localStorage.getItem('access_token');
      if (token) {
        config.headers.Authorization = `Bearer ${token}`;
      }
    }
    return config;
  },
  (error) => Promise.reject(error)
);

// ─── Response interceptor: auto-refresh on 401 ───
api.interceptors.response.use(
  (response) => response,
  async (error) => {
    const originalRequest = error.config;
    if (!originalRequest) {
      return Promise.reject(error);
    }

    if (
      error.response?.status === 401 &&
      !originalRequest._retry &&
      !shouldSkipTokenRefresh(originalRequest.url)
    ) {
      originalRequest._retry = true;

      try {
        // Always refresh on 401 — token may be unexpired locally but rejected
        // by the server (e.g. SECRET_KEY change). Share in-flight refresh.
        const accessToken = await refreshAccessToken();
        originalRequest.headers.Authorization = `Bearer ${accessToken}`;
        return api(originalRequest);
      } catch (refreshError) {
        clearSessionAndRedirect();
        return Promise.reject(refreshError);
      }
    }

    return Promise.reject(error);
  }
);

// ─── Auth API ───
export const authAPI = {
  register: (data) => api.post('/auth/register', data),
  login: (data) => api.post('/auth/login', data),
  refresh: (refreshToken) => api.post('/auth/refresh', { refresh_token: refreshToken }),
  logout: () => api.post('/auth/logout'),
  me: () => api.get('/auth/me'),
  forgotPassword: (data) => api.post('/auth/forgot-password', data),
  resetPassword: (data) => api.post('/auth/reset-password', data),
  verifyEmail: (data) => api.post('/auth/verify-email', data),
  resendVerification: (data) => api.post('/auth/resend-verification', data),
  /** Full-page redirect into the Google OAuth2 authorization flow. */
  googleLoginUrl: () => `${API_BASE}/auth/oauth/google`,
};

// ─── User/Profile API ───
export const userAPI = {
  getProfile: () => api.get('/users/profile'),
  updateUser: (data) => api.put('/users/profile', data),
  getPreferences: () => api.get('/users/profile/preferences'),
  updatePreferences: (data) => api.put('/users/profile/preferences', data),
  updateSleepSchedule: (data) => api.put('/users/profile/sleep-schedule', data),
  updateGoals: (data) => api.put('/users/profile/goals', data),
  getStats: () => api.get('/users/profile/stats'),
  deleteAccount: () => api.delete('/users/account'),
};

// ─── Alarm API ───
export const alarmAPI = {
  create: (data) => api.post('/alarms/', data),
  list: (activeOnly = false) => api.get('/alarms/', { params: { is_active: activeOnly === true ? true : undefined } }),
  get: (id) => api.get(`/alarms/${id}`),
  update: (id, data) => api.put(`/alarms/${id}`, data),
  // Named `remove` — `delete` is a JS reserved word and is unreliable as a method key.
  remove: (id) => api.delete(`/alarms/${id}`),
  toggle: (id, isActive) => api.patch(`/alarms/${id}/toggle`, { is_active: isActive }),
  upcoming: (hours = 24) => api.get('/alarms/upcoming', { params: { hours_ahead: hours } }),
  snooze: (id) => api.post(`/alarms/${id}/snooze`),
  dismiss: (id, data = {}) => api.post(`/alarms/${id}/dismiss`, data),
  failWake: (id) => api.post(`/alarms/${id}/fail-wake`),
  getSnoozeInfo: (id) => api.get(`/alarms/${id}/snooze-info`),
  getChallenge: (id) => api.get(`/alarms/${id}/challenge`),
  verifyChallenge: (id, data) => api.post(`/alarms/${id}/verify`, data),
  startPractice: (data = {}) => api.post('/alarms/challenge/practice', data),
  verifyPractice: (data) => api.post('/alarms/challenge/practice/verify', data),
  getChallengeStats: () => api.get('/alarms/challenge/stats'),
  getChallengeHistory: (params = {}) =>
    api.get('/alarms/challenge/history', { params }),
  getChallengeAnalysis: () => api.get('/alarms/challenge/analysis'),
  getAlarmChallengeHistory: (id, params = {}) =>
    api.get(`/alarms/${id}/challenge/history`, { params }),
  getWakefulness: () => api.get('/alarms/wakefulness'),
  getWakeConfirmations: (limit = 20) =>
    api.get('/alarms/wake-confirmations', { params: { limit } }),
};

// ─── Recommendations API (sleep / wake / productivity coaching) ───
export const recommendationAPI = {
  getAll: (params = {}) => api.get('/recommendations', { params }),
  getDaily: () => api.get('/recommendations/daily'),
  getSleep: () => api.get('/recommendations/sleep'),
  getWake: () => api.get('/recommendations/wake'),
  getProductivity: () => api.get('/recommendations/productivity'),
};

// ─── Behavioral Analytics API (pandas/numpy aggregates) + event ingest ───
export const analyticsAPI = {
  getBehavioral: (days = 30) =>
    api.get('/analytics/behavioral', { params: { days } }),
  getSnoozePattern: (days = 30) =>
    api.get('/analytics/behavioral/snooze', { params: { days } }),
  getWakeConsistency: (days = 30) =>
    api.get('/analytics/behavioral/wake-consistency', { params: { days } }),
  getSleepAdherence: (days = 30) =>
    api.get('/analytics/behavioral/sleep-adherence', { params: { days } }),
  getWeeklyTrends: (days = 30) =>
    api.get('/analytics/behavioral/trends/weekly', { params: { days } }),
  getMonthlyTrends: (days = 30) =>
    api.get('/analytics/behavioral/trends/monthly', { params: { days } }),
  getHabitTrends: (days = 30) =>
    api.get('/analytics/behavioral/habits', { params: { days } }),
  getSummary: () => api.get('/analytics/summary'),
  /** POST /analytics/events — single client event ingest */
  postEvent: (event) => api.post('/analytics/events', event),
  /** POST /analytics/events/batch — up to 100 events */
  postEventsBatch: (events) => api.post('/analytics/events/batch', { events }),
};

// ─── Admin API ───
/** Normalize admin date params: number → { days }, or pass through { days | start_date, end_date }. */
function adminDateParams(params = 30) {
  if (typeof params === 'number') return { days: params };
  return params;
}

export const adminAPI = {
  getDashboard: (params = 30) =>
    api.get('/admin/dashboard', { params: adminDateParams(params) }),
  getStatistics: (params = 30) =>
    api.get('/admin/statistics', { params: adminDateParams(params) }),
  getRecommendations: (params = 30) =>
    api.get('/admin/recommendations', { params: adminDateParams(params) }),
  getAlarms: (params = 30) =>
    api.get('/admin/alarms', { params: adminDateParams(params) }),
  getAnalytics: (params = 30) =>
    api.get('/admin/analytics', { params: adminDateParams(params) }),
  getReports: () => api.get('/admin/reports'),
  listSystemReports: () => api.get('/admin/system-reports'),
  getSystemReport: (reportType, params = {}) =>
    api.get(`/admin/system-reports/${reportType}`, {
      params: adminDateParams(params),
    }),
  exportSystemReport: (reportType, format = 'pdf', params = {}) =>
    api.get(`/admin/system-reports/${reportType}/export`, {
      params: { ...adminDateParams(params), format },
      responseType: 'blob',
      timeout: 60000,
    }),
  getNotificationSettings: () => api.get('/admin/notification-settings'),
  updateNotificationSettings: (data) =>
    api.put('/admin/notification-settings', data),
  broadcastAnnouncement: (data) =>
    api.post('/admin/announcements/broadcast', data),

  // ── User management ──
  /** GET /admin/users — paginated list with search / filter / sort applied server-side */
  listUsers: (params = {}) => api.get('/admin/users', { params }),
  /** GET /admin/users/{id} — deep read-only detail with profile and activity */
  getUserDetail: (userId, params = {}) =>
    api.get(`/admin/users/${userId}`, { params }),
  /** PUT /users/{id} — admin edit of full_name, email, role, is_active */
  updateUser: (userId, data) => api.put(`/users/${userId}`, data),
  activateUser: (userId) => api.post(`/users/${userId}/activate`),
  deactivateUser: (userId) => api.post(`/users/${userId}/deactivate`),
  // Named `deleteUser` rather than `delete` — reserved word, unreliable as a key.
  deleteUser: (userId) => api.delete(`/users/${userId}`),

  // ── Coach/client assignments (these grant coaches their data access) ──
  listCoachAssignments: (params = {}) =>
    api.get('/admin/coach-assignments', { params }),
  createCoachAssignment: (data) => api.post('/admin/coach-assignments', data),
  removeCoachAssignment: (coachId, clientId) =>
    api.delete('/admin/coach-assignments', {
      params: { coach_id: coachId, client_id: clientId },
    }),
};

// ─── Wellness Coach API (assigned clients only — enforced server-side) ───
export const coachAPI = {
  /** GET /coach/overview — roster-wide KPIs across all assigned clients */
  getOverview: (days = 30) => api.get('/coach/overview', { params: { days } }),
  /** GET /coach/clients — paginated client roster with search / filter / sort */
  listClients: (params = {}) => api.get('/coach/clients', { params }),
  /** GET /coach/clients/{id} — one client's roster row plus profile context */
  getClient: (clientId, days = 30) =>
    api.get(`/coach/clients/${clientId}`, { params: { days } }),
  /** GET /coach/clients/{id}/behavioral — sleep, wake, habit, and snooze trends */
  getBehavioral: (clientId, days = 30) =>
    api.get(`/coach/clients/${clientId}/behavioral`, { params: { days } }),
  getSleepTrends: (clientId, days = 30) =>
    api.get(`/coach/clients/${clientId}/sleep-trends`, { params: { days } }),
  getWakeConsistency: (clientId, days = 30) =>
    api.get(`/coach/clients/${clientId}/wake-consistency`, { params: { days } }),
  getHabitScore: (clientId, days = 30) =>
    api.get(`/coach/clients/${clientId}/habit-score`, { params: { days } }),
  getChallengePerformance: (clientId, days = 30) =>
    api.get(`/coach/clients/${clientId}/challenge-performance`, {
      params: { days },
    }),
  getProductivity: (clientId, days = 30) =>
    api.get(`/coach/clients/${clientId}/productivity`, { params: { days } }),
  getRecommendations: (clientId) =>
    api.get(`/coach/clients/${clientId}/recommendations`),
};

// ─── Dashboard Aggregation API ───
export const dashboardAPI = {
  getSummary: (period = 'weekly') =>
    api.get('/dashboard/summary', { params: { period } }),
  getAlarmHistory: (params = {}) =>
    api.get('/dashboard/alarm-history', { params }),
  getWakeStats: (days = 30) =>
    api.get('/dashboard/wake-stats', { params: { days } }),
  getChallengePerformance: (days = 30) =>
    api.get('/dashboard/challenge-performance', { params: { days } }),
  getProductivity: (days = 30) =>
    api.get('/dashboard/productivity', { params: { days } }),
};

// ─── Reports API (PDF / Excel lifestyle reports) ───
export const reportsAPI = {
  list: () => api.get('/reports'),
  get: (reportType, params = {}) =>
    api.get(`/reports/${reportType}`, { params }),
  export: (reportType, format = 'pdf', params = {}) =>
    api.get(`/reports/${reportType}/export`, {
      params: { ...params, format },
      responseType: 'blob',
      timeout: 60000,
    }),
};

/**
 * Extract the server error message from a failed request.
 * Blob responses (file downloads) carry the JSON error body as a Blob, so it
 * must be read back before `detail` is reachable.
 */
export async function readErrorDetail(err, fallback = 'Request failed') {
  const data = err?.response?.data;
  if (typeof data?.detail === 'string') return data.detail;

  if (data instanceof Blob) {
    try {
      const parsed = JSON.parse(await data.text());
      if (typeof parsed?.detail === 'string') return parsed.detail;
      if (Array.isArray(parsed?.detail) && parsed.detail[0]?.msg) {
        return parsed.detail[0].msg;
      }
    } catch {
      // Not a JSON error body — fall through to the generic message.
    }
  }

  if (Array.isArray(data?.detail) && data.detail[0]?.msg) {
    return data.detail[0].msg;
  }
  return fallback;
}

// ─── Notification API ───
export const notificationAPI = {
  /** Register/update an FCM device token */
  registerToken: (data) => api.post('/notifications/device-token', data),
  /** Unregister an FCM device token */
  removeToken: (fcmToken) =>
    api.delete('/notifications/device-token', { params: { fcm_token: fcmToken } }),
  /** Get notification preferences */
  getPreferences: () => api.get('/notifications/preferences'),
  /** Update notification preferences */
  updatePreferences: (data) => api.put('/notifications/preferences', data),
  /** Get paginated notification feed */
  getNotifications: (params = {}) => api.get('/notifications/', { params }),
  /** Upcoming pending notifications for local scheduling */
  getPending: (params = {}) => api.get('/notifications/pending', { params }),
  /** Get unread notification count */
  getUnreadCount: () => api.get('/notifications/unread-count'),
  /** Mark notifications as read */
  markRead: (data) => api.post('/notifications/mark-read', data),
  /** Send a test notification */
  sendTest: () => api.post('/notifications/test'),
};

export default api;

