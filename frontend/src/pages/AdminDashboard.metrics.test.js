/**
 * Admin API performance panel.
 *
 * GET /api/v1/system/metrics existed and was measured server-side, but nothing
 * in the UI ever read it — the numbers were only reachable with curl and an
 * admin token. These tests pin that the panel requests the endpoint and renders
 * the measured distribution, including the slow-route highlight.
 */
import React from 'react';
import { render, screen, waitFor } from '@testing-library/react';

jest.mock('../services/api');
jest.mock('../components/AdminUserManagement', () => ({
    __esModule: true,
    default: () => null,
}));

import { adminAPI, readErrorDetail, systemAPI } from '../services/api';
import AdminDashboard from './AdminDashboard';

const METRICS = {
    requests: {
        sample_size: 500,
        routes_tracked: 2,
        total_requests: 1200,
        total_errors: 6,
        overall: {
            sampled: 1200,
            p50_ms: 4.2,
            p95_ms: 18.7,
            p99_ms: 41.3,
            min_ms: 0.8,
            max_ms: 120.4,
            mean_ms: 6.1,
        },
        routes: [
            {
                route: 'GET /api/v1/dashboard/productivity',
                requests: 300,
                errors: 0,
                sampled: 300,
                p50_ms: 410.2,
                p95_ms: 620.9,
                p99_ms: 810.5,
                min_ms: 180.1,
                max_ms: 900.2,
                mean_ms: 430.7,
            },
            {
                route: 'GET /api/v1/system/status',
                requests: 900,
                errors: 6,
                sampled: 500,
                p50_ms: 1.9,
                p95_ms: 3.4,
                p99_ms: 5.1,
                min_ms: 0.8,
                max_ms: 9.9,
                mean_ms: 2.2,
            },
        ],
    },
    challenge_generation: {
        sample_size: 500,
        keys_tracked: 3,
        total_generations: 240,
        total_failures: 2,
        overall: { sampled: 240, p50_ms: 6.4, p95_ms: 21.8, p99_ms: 33.1, min_ms: 1.1, max_ms: 40.2, mean_ms: 8.0 },
        budget_ms: 50,
    },
};

function mockAdminEndpoints() {
    adminAPI.getDashboard.mockResolvedValue({
        data: { total_users: 12, total_alarms: 30, users: [], engagement: {}, period: { days: 30 } },
    });
    adminAPI.getStatistics.mockResolvedValue({ data: {} });
    adminAPI.getAlarms.mockResolvedValue({ data: {} });
    adminAPI.getRecommendations.mockResolvedValue({ data: {} });
    adminAPI.getAnalytics.mockResolvedValue({ data: {} });
    adminAPI.getReports.mockResolvedValue({ data: {} });
    adminAPI.listSystemReports.mockResolvedValue({ data: { reports: [] } });
    adminAPI.getSystemReport.mockResolvedValue({ data: {} });
    adminAPI.getNotificationSettings.mockResolvedValue({ data: {} });
}

beforeEach(() => {
    mockAdminEndpoints();
    readErrorDetail.mockImplementation(async (err, fallback) =>
        err?.response?.data?.detail || fallback
    );
    systemAPI.getMetrics.mockResolvedValue({ data: METRICS });
});

describe('API performance panel', () => {
    it('reads the measured metrics endpoint', async () => {
        render(<AdminDashboard />);

        await waitFor(() => expect(systemAPI.getMetrics).toHaveBeenCalled());
        // Only the slowest routes are requested, not the whole table.
        expect(systemAPI.getMetrics).toHaveBeenCalledWith(expect.any(Number));
    });

    it('renders the measured distribution and per-route rows', async () => {
        render(<AdminDashboard />);

        expect(await screen.findByText('API Performance')).toBeInTheDocument();
        expect(await screen.findByText('4.2 ms')).toBeInTheDocument();
        expect(screen.getByText('18.7 ms')).toBeInTheDocument();
        expect(screen.getByText('GET /api/v1/dashboard/productivity')).toBeInTheDocument();
        expect(screen.getByText('GET /api/v1/system/status')).toBeInTheDocument();
    });

    it('flags a route whose p95 is over the latency target', async () => {
        render(<AdminDashboard />);

        const slow = await screen.findByText('620.9');
        const healthy = screen.getByText('3.4');
        expect(slow).toHaveClass('text-orange-400');
        expect(healthy).toHaveClass('text-emerald-400');
    });

    it('reports challenge generation against its own budget', async () => {
        render(<AdminDashboard />);

        // Awaited on a measured value: the section heading also renders while the
        // request is still in flight, so matching it would prove nothing.
        expect(await screen.findByText('Budget 50 ms')).toBeInTheDocument();
        expect(screen.getByText('Challenge generation')).toBeInTheDocument();
        expect(screen.getByText('240')).toBeInTheDocument();
    });

    it('shows an error instead of a blank panel when metrics fail', async () => {
        systemAPI.getMetrics.mockRejectedValue({
            response: { data: { detail: 'Not enough permissions' } },
        });
        render(<AdminDashboard />);

        expect(await screen.findByText('Not enough permissions')).toBeInTheDocument();
    });
});
