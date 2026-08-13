/**
 * Axios API client backed by HttpOnly session cookies.
 *
 * JWTs are never stored in localStorage/sessionStorage — the backend sets
 * HttpOnly cookies on login/refresh, so injected scripts cannot read a session.
 * Expired access cookies are recovered reactively via POST /auth/refresh.
 */
import axios from 'axios';
import { REQUEST_ID_HEADER, newRequestId, setLastRequestId } from './requestId';

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000/api/v1';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  timeout: 15000,
  // Required so the browser sends/stores the HttpOnly auth cookies.
  withCredentials: true,
});

// ─── Request interceptor: correlate this call with the server's logs ───
// The backend honours and echoes this id, so a browser error report and the
// server records for the same action share one traceable value.
export function withCorrelationId(config = {}) {
  const requestId = newRequestId();
  config.headers = config.headers || {};
  config.headers[REQUEST_ID_HEADER] = requestId;
  setLastRequestId(requestId);
  return config;
}

api.interceptors.request.use(withCorrelationId);

/** Shared in-flight refresh so concurrent 401s share one call. */
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

/**
 * Non-sensitive marker telling the UI a session cookie should exist.
 * The cookies themselves are HttpOnly and unreadable from JS.
 */
const SESSION_FLAG = 'icap_session';

export function markSessionActive() {
  localStorage.setItem(SESSION_FLAG, '1');
}

export function hasActiveSession() {
  return localStorage.getItem(SESSION_FLAG) === '1';
}

export function clearSessionFlag() {
  localStorage.removeItem(SESSION_FLAG);
}

/**
 * Ask the backend for a fresh access cookie. The refresh token travels in the
 * HttpOnly cookie, so nothing sensitive is read or written by JS here.
 */
async function refreshAccessToken() {
  if (!refreshPromise) {
    refreshPromise = axios
      .post(`${API_BASE}/auth/refresh`, {}, { withCredentials: true })
      .finally(() => {
        refreshPromise = null;
      });
  }
  return refreshPromise;
}

function clearSessionAndRedirect() {
  clearSessionFlag();
  localStorage.removeItem('user');
  window.location.href = '/login';
}

// ─── Response interceptor: refresh the session cookie once on 401 ───
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
        await refreshAccessToken();
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
  // No `refresh` helper: the 401 interceptor above must call /auth/refresh on a
  // bare axios instance, otherwise its own interceptor would recurse.
  logout: () => api.post('/auth/logout'),
  logoutAll: () => api.post('/auth/logout-all'),
  me: () => api.get('/auth/me'),
  // The only route that can change an email address; PUT /users/profile cannot.
  updateMe: (data) => api.put('/auth/me', data),
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

// ─── Profile resource API (/profiles) ───
// The raw profile record, which carries fields the /users/profile bundle does
// not expose: adapted difficulty, consistency score and lifetime counters.
export const profileAPI = {
  getMe: () => api.get('/profiles/me'),
  /** GET /profiles/me/habit-score — weighted habit score with its components */
  getHabitScore: () => api.get('/profiles/me/habit-score'),
  /** PATCH /profiles/me/habits — habit preferences (no /users equivalent) */
  updateHabits: (data) => api.patch('/profiles/me/habits', data),
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
  /** GET /alarms/challenge/learning-profile — learning patterns and engagement */
  getLearningProfile: () => api.get('/alarms/challenge/learning-profile'),
  /** GET /alarms/challenge/log-health — attempt-log integrity for the caller */
  getChallengeLogHealth: () => api.get('/alarms/challenge/log-health'),
  /** GET /alarms/snooze-history — per-snooze audit rows */
  getSnoozeHistory: (params = {}) =>
    api.get('/alarms/snooze-history', { params }),
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
  getRelevance: (params = {}) => api.get('/recommendations/relevance', { params }),
  sendFeedback: (id, rating) =>
    api.put(`/recommendations/${encodeURIComponent(id)}/feedback`, { rating }),
  clearFeedback: (id) =>
    api.delete(`/recommendations/${encodeURIComponent(id)}/feedback`),
};

// ─── Behavioral Analytics API (pandas/numpy aggregates) + event ingest ───
export const analyticsAPI = {
  getBehavioral: (days = 30) =>
    api.get('/analytics/behavioral', { params: { days } }),
  getSnoozePattern: (days = 30) =>
    api.get('/analytics/behavioral/snooze', { params: { days } }),
  getWakeConsistency: (days = 30) =>
    api.get('/analytics/behavioral/wake-consistency', { params: { days } }),
  getVerificationAccuracy: (days = 30) =>
    api.get('/analytics/behavioral/verification-accuracy', { params: { days } }),
  getSleepAdherence: (days = 30) =>
    api.get('/analytics/behavioral/sleep-adherence', { params: { days } }),
  getSleepPatterns: (days = 30) =>
    api.get('/analytics/behavioral/sleep-patterns', { params: { days } }),
  getProductivityCorrelation: (days = 30) =>
    api.get('/analytics/behavioral/productivity-correlation', { params: { days } }),
  getWeeklyTrends: (days = 30) =>
    api.get('/analytics/behavioral/trends/weekly', { params: { days } }),
  getMonthlyTrends: (days = 30) =>
    api.get('/analytics/behavioral/trends/monthly', { params: { days } }),
  getHabitTrends: (days = 30) =>
    api.get('/analytics/behavioral/habits', { params: { days } }),
  getSummary: () => api.get('/analytics/summary'),
  /** GET /analytics/events — the caller's own recorded events */
  listEvents: (params = {}) => api.get('/analytics/events', { params }),
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
  /** GET /users/{id} — the plain user record, used to refresh an edit form */
  getUser: (userId) => api.get(`/users/${userId}`),
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

// ─── System / observability API ───
export const systemAPI = {
  /**
   * GET /system/metrics — admin-only runtime latency measured by this worker.
   * `top` caps the per-route list to the N slowest routes.
   */
  getMetrics: (top) => api.get('/system/metrics', { params: top ? { top } : {} }),
  /** GET /system/status — public health, version and maintenance state */
  getStatus: () => api.get('/system/status'),
  /** GET /system/alerts — admin-only threshold evaluation (read-only, never pages) */
  getAlerts: () => api.get('/system/alerts'),
  /** GET /system/logging — admin-only view of the active logging configuration */
  getLogging: () => api.get('/system/logging'),
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

