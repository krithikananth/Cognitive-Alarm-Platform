// k6 load test for the ICAP dashboard APIs.
//
// Equivalent coverage to perf/loadtest/locustfile.py, for environments that
// already run k6 in CI. Thresholds encode the same p95 budgets used by
// perf/benchmark.py, so a run fails the build when a dashboard regresses.
//
// Run:
//   k6 run -e BASE_URL=http://localhost:8000 \
//          -e USER_EMAIL=perf-user-00000@perf.example.com \
//          -e USER_PASSWORD=... \
//          -e ADMIN_EMAIL=admin@perf.example.com -e ADMIN_PASSWORD=... \
//          -e COACH_EMAIL=coach@perf.example.com -e COACH_PASSWORD=... \
//          perf/loadtest/k6_dashboard.js
//
// Never point this at production.

import http from 'k6/http';
import { check, group, sleep } from 'k6';
import { Trend } from 'k6/metrics';

const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';
const API = `${BASE_URL}/api/v1`;

const userDashboardLatency = new Trend('user_dashboard_page_ms', true);
const adminDashboardLatency = new Trend('admin_dashboard_page_ms', true);
const coachDashboardLatency = new Trend('coach_dashboard_page_ms', true);

export const options = {
    scenarios: {
        user_dashboard: {
            executor: 'ramping-vus',
            exec: 'userDashboard',
            startVUs: 0,
            stages: [
                { duration: '30s', target: 20 },
                { duration: '2m', target: 20 },
                { duration: '30s', target: 0 },
            ],
        },
        admin_dashboard: {
            executor: 'constant-vus',
            exec: 'adminDashboard',
            vus: 2,
            duration: '3m',
            startTime: '30s',
        },
        coach_dashboard: {
            executor: 'constant-vus',
            exec: 'coachDashboard',
            vus: 2,
            duration: '3m',
            startTime: '30s',
        },
    },
    thresholds: {
        http_req_failed: ['rate<0.01'],
        'http_req_duration{endpoint:dashboard_summary}': ['p(95)<400'],
        'http_req_duration{endpoint:dashboard_wake_stats}': ['p(95)<400'],
        'http_req_duration{endpoint:dashboard_challenge_performance}': ['p(95)<400'],
        'http_req_duration{endpoint:dashboard_productivity}': ['p(95)<400'],
        'http_req_duration{endpoint:dashboard_alarm_history}': ['p(95)<400'],
        'http_req_duration{endpoint:admin_dashboard}': ['p(95)<1500'],
        'http_req_duration{endpoint:admin_statistics}': ['p(95)<1500'],
        'http_req_duration{endpoint:coach_overview}': ['p(95)<1000'],
        'http_req_duration{endpoint:coach_clients}': ['p(95)<1000'],
    },
};

function login(email, password) {
    const res = http.post(
        `${API}/auth/login`,
        JSON.stringify({ email, password }),
        { headers: { 'Content-Type': 'application/json' }, tags: { endpoint: 'login' } }
    );
    check(res, { 'login succeeded': (r) => r.status === 200 });
    return res.json('access_token');
}

function authHeaders(token, endpoint) {
    return {
        headers: { Authorization: `Bearer ${token}` },
        tags: { endpoint },
    };
}

export function setup() {
    if (!__ENV.USER_PASSWORD) {
        throw new Error('USER_PASSWORD is required — refusing to run without credentials.');
    }
    return {
        userToken: login(__ENV.USER_EMAIL, __ENV.USER_PASSWORD),
        adminToken: __ENV.ADMIN_PASSWORD
            ? login(__ENV.ADMIN_EMAIL, __ENV.ADMIN_PASSWORD)
            : null,
        coachToken: __ENV.COACH_PASSWORD
            ? login(__ENV.COACH_EMAIL, __ENV.COACH_PASSWORD)
            : null,
    };
}

export function userDashboard(data) {
    const days = [7, 30, 90][Math.floor(Math.random() * 3)];
    const period = days === 7 ? 'weekly' : 'monthly';
    const started = Date.now();

    group('user dashboard page load', () => {
        const responses = http.batch([
            ['GET', `${API}/dashboard/summary?period=${period}`, null, authHeaders(data.userToken, 'dashboard_summary')],
            ['GET', `${API}/dashboard/wake-stats?days=${days}`, null, authHeaders(data.userToken, 'dashboard_wake_stats')],
            ['GET', `${API}/dashboard/challenge-performance?days=${days}`, null, authHeaders(data.userToken, 'dashboard_challenge_performance')],
            ['GET', `${API}/dashboard/productivity?days=${days}`, null, authHeaders(data.userToken, 'dashboard_productivity')],
            ['GET', `${API}/analytics/behavioral/habits?days=${days}`, null, authHeaders(data.userToken, 'analytics_habits')],
            ['GET', `${API}/analytics/behavioral/trends/monthly?days=${days}`, null, authHeaders(data.userToken, 'analytics_monthly')],
        ]);
        responses.forEach((res) => check(res, { 'status is 200': (r) => r.status === 200 }));
    });

    const history = http.get(
        `${API}/dashboard/alarm-history?page=1&per_page=20&days=30`,
        authHeaders(data.userToken, 'dashboard_alarm_history')
    );
    check(history, { 'history status is 200': (r) => r.status === 200 });

    userDashboardLatency.add(Date.now() - started);
    sleep(Math.random() * 2 + 1);
}

export function adminDashboard(data) {
    if (!data.adminToken) {
        return;
    }
    const started = Date.now();
    const responses = http.batch([
        ['GET', `${API}/admin/dashboard?days=30`, null, authHeaders(data.adminToken, 'admin_dashboard')],
        ['GET', `${API}/admin/statistics?days=30`, null, authHeaders(data.adminToken, 'admin_statistics')],
        ['GET', `${API}/admin/alarms?days=30`, null, authHeaders(data.adminToken, 'admin_alarms')],
        ['GET', `${API}/admin/recommendations?days=30`, null, authHeaders(data.adminToken, 'admin_recommendations')],
        ['GET', `${API}/admin/analytics?days=30`, null, authHeaders(data.adminToken, 'admin_analytics')],
        ['GET', `${API}/admin/reports`, null, authHeaders(data.adminToken, 'admin_reports')],
    ]);
    responses.forEach((res) => check(res, { 'status is 200': (r) => r.status === 200 }));
    adminDashboardLatency.add(Date.now() - started);
    sleep(3);
}

export function coachDashboard(data) {
    if (!data.coachToken) {
        return;
    }
    const started = Date.now();
    const responses = http.batch([
        ['GET', `${API}/coach/overview?days=30`, null, authHeaders(data.coachToken, 'coach_overview')],
        ['GET', `${API}/coach/clients?page=1&per_page=20`, null, authHeaders(data.coachToken, 'coach_clients')],
    ]);
    responses.forEach((res) => check(res, { 'status is 200': (r) => r.status === 200 }));
    coachDashboardLatency.add(Date.now() - started);
    sleep(3);
}
