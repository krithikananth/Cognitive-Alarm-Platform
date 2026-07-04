/**
 * Axios API client with JWT interceptor for auto-refresh.
 */
import axios from 'axios';

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000/api/v1';

const api = axios.create({
  baseURL: API_BASE,
  headers: { 'Content-Type': 'application/json' },
  timeout: 15000,
});

// ─── Request interceptor: attach JWT ───
api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
      config.headers.Authorization = `Bearer ${token}`;
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

    if (error.response?.status === 401 && !originalRequest._retry) {
      originalRequest._retry = true;

      try {
        const refreshToken = localStorage.getItem('refresh_token');
        if (!refreshToken) throw new Error('No refresh token');

        const { data } = await axios.post(`${API_BASE}/auth/refresh`, {
          refresh_token: refreshToken,
        });

        localStorage.setItem('access_token', data.access_token);
        localStorage.setItem('refresh_token', data.refresh_token);

        originalRequest.headers.Authorization = `Bearer ${data.access_token}`;
        return api(originalRequest);
      } catch (refreshError) {
        // Refresh failed — logout
        localStorage.removeItem('access_token');
        localStorage.removeItem('refresh_token');
        localStorage.removeItem('user');
        window.location.href = '/login';
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
  forgotPassword: (email) => api.post('/auth/forgot-password', { email }),
  resetPassword: (token, newPassword) =>
    api.post('/auth/reset-password', { token, new_password: newPassword }),
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
  create: (data) => api.post('/alarms', data),
  list: (activeOnly = false) => api.get('/alarms', { params: { active_only: activeOnly } }),
  get: (id) => api.get(`/alarms/${id}`),
  update: (id, data) => api.put(`/alarms/${id}`, data),
  delete: (id) => api.delete(`/alarms/${id}`),
  toggle: (id, isActive) => api.patch(`/alarms/${id}/toggle`, { is_active: isActive }),
  upcoming: (limit = 5) => api.get('/alarms/upcoming', { params: { limit } }),
  history: (limit = 50, offset = 0) =>
    api.get('/alarms/history', { params: { limit, offset } }),
  trigger: (id) => api.post(`/alarms/${id}/trigger`),
  snooze: (eventId) => api.post(`/alarms/events/${eventId}/snooze`),
  dismiss: (eventId, data) => api.post(`/alarms/events/${eventId}/dismiss`, null, { params: data }),
};

export default api;
