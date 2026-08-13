/**
 * UserDashboard "Log sleep now" integration flow.
 *
 * Covers the whole loop the panel-level tests cannot: click -> analytics
 * ingest call -> dashboard reload -> refreshed sleep panel. Also pins the
 * start/end alternation, which is driven by `has_open_session` (the backend's
 * 16-hour open-session boundary).
 */
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

jest.mock('../services/api');
jest.mock('../store/authStore');
jest.mock('../store/alarmStore');

import { analyticsAPI, dashboardAPI, userAPI } from '../services/api';
import useAuthStore from '../store/authStore';
import useAlarmStore from '../store/alarmStore';
import UserDashboard from './UserDashboard';

function sleepPatterns(overrides = {}) {
    return {
        nights_observed: 1,
        nights_with_duration: 1,
        nights_recorded: 1,
        nights_estimated: 0,
        has_recorded_sleep: true,
        duration_source: 'recorded',
        avg_recorded_duration_hours: 8,
        avg_estimated_duration_hours: null,
        avg_sleep_duration_hours: 8,
        std_sleep_duration_hours: 0,
        min_sleep_duration_hours: 8,
        max_sleep_duration_hours: 8,
        avg_bedtime: '23:00',
        bedtime_std_minutes: 0,
        avg_wake_time: '07:00',
        wake_time_std_minutes: 0,
        avg_mid_sleep: '03:00',
        social_jetlag_minutes: null,
        schedule_regularity_score: 100,
        duration_consistency_score: 100,
        target_sleep_hours: 8,
        avg_sleep_debt_hours: 0,
        short_sleep_nights: 0,
        long_sleep_nights: 0,
        avg_wake_latency_seconds: 300,
        weekday: { nights: 1, avg_duration_hours: 8, avg_wake_time: '07:00', avg_bedtime: '23:00' },
        weekend: { nights: 0, avg_duration_hours: null, avg_wake_time: null, avg_bedtime: null },
        recent_7d_avg_duration_hours: 8,
        previous_7d_avg_duration_hours: null,
        trend: 'insufficient_data',
        bedtime_coverage_rate: 100,
        has_open_session: false,
        nights: [
            {
                date: '2026-08-10',
                weekday: 'Mon',
                is_weekend: false,
                source: 'recorded',
                sleep_end_source: 'sleep_record',
                wake_time: '07:00',
                wake_minutes: 420,
                bedtime: '23:00',
                bedtime_minutes: 1380,
                sleep_duration_hours: 8,
                mid_sleep_minutes: 180,
                wake_latency_seconds: 300,
            },
        ],
        ...overrides,
    };
}

function productivity(overrides = {}) {
    return {
        days: 7,
        verified_wakes: 1,
        morning_routine_score: 100,
        cognitive_readiness_score: 60,
        habit_score: 70,
        habit_score_breakdown: {
            wake_up_consistency: 80,
            challenge_completion: 70,
            snooze_reduction: 100,
            sleep_adherence: 20,
        },
        active_days_in_period: 1,
        consistency_rate: 14,
        current_streak: 1,
        best_streak: 1,
        challenge_accuracy: 70,
        avg_wakefulness: 60,
        avg_time_to_productive_seconds: 300,
        trend: {
            direction: 'insufficient_data',
            recent_clean_wake_rate: 0,
            previous_clean_wake_rate: 0,
            change: 0,
        },
        goals: [],
        goals_count: 0,
        sleep_patterns: sleepPatterns(),
        correlations: null,
        ...overrides,
    };
}

const EMPTY_SERIES = { series: [], totals: {}, trend: 'insufficient_data' };

function mockDashboard(productivityPayload) {
    userAPI.getStats.mockResolvedValue({ data: {} });
    dashboardAPI.getSummary.mockResolvedValue({ data: {} });
    dashboardAPI.getWakeStats.mockResolvedValue({ data: { total_wake_events: 0 } });
    dashboardAPI.getChallengePerformance.mockResolvedValue({ data: { total_attempts: 0 } });
    dashboardAPI.getProductivity.mockResolvedValue({ data: productivityPayload });
    dashboardAPI.getAlarmHistory.mockResolvedValue({
        data: { events: [], total: 0, page: 1 },
    });
    analyticsAPI.getHabitTrends.mockResolvedValue({ data: { series: [] } });
    analyticsAPI.getMonthlyTrends.mockResolvedValue({ data: EMPTY_SERIES });
    analyticsAPI.getWeeklyTrends.mockResolvedValue({ data: EMPTY_SERIES });
    analyticsAPI.getSnoozePattern.mockResolvedValue({ data: null });
    analyticsAPI.getSleepAdherence.mockResolvedValue({ data: null });
    analyticsAPI.getVerificationAccuracy.mockResolvedValue({
        data: { status: 'insufficient_data', decisions: 0, min_decisions_required: 3 },
    });
    analyticsAPI.postEvent.mockResolvedValue({ data: { id: 1 } });
}

function renderDashboard() {
    return render(
        <MemoryRouter>
            <UserDashboard />
        </MemoryRouter>
    );
}

beforeEach(() => {
    jest.clearAllMocks();
    useAuthStore.mockReturnValue({ user: { id: 1, role: 'user', full_name: 'Test' } });
    useAlarmStore.mockReturnValue({
        alarms: [],
        fetchAlarms: jest.fn(),
        fetchUpcoming: jest.fn(),
    });
});

describe('Log sleep now — click to API to UI', () => {
    test('a closed night logs a sleep start and refreshes the dashboard', async () => {
        mockDashboard(productivity());
        renderDashboard();

        const button = await screen.findByRole('button', { name: /log sleep now/i });
        expect(dashboardAPI.getProductivity).toHaveBeenCalledTimes(1);

        fireEvent.click(button);

        await waitFor(() => expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1));
        const sent = analyticsAPI.postEvent.mock.calls[0][0];
        expect(sent.event_type).toBe('sleep.started');
        expect(sent.source).toBe('client');
        expect(Date.parse(sent.event_data.at)).not.toBeNaN();

        // The dashboard reloads so the new record shows up
        await waitFor(() => expect(dashboardAPI.getProductivity).toHaveBeenCalledTimes(2));
    });

    test('an open session (start within 16h, no end) logs the sleep end instead', async () => {
        mockDashboard(
            productivity({ sleep_patterns: sleepPatterns({ has_open_session: true }) })
        );
        renderDashboard();

        fireEvent.click(await screen.findByRole('button', { name: /log sleep now/i }));

        await waitFor(() => expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1));
        expect(analyticsAPI.postEvent.mock.calls[0][0].event_type).toBe('sleep.ended');
    });

    test('a start older than the 16h boundary is not open, so a new start is logged', async () => {
        // The backend clears has_open_session once the start ages past
        // SLEEP_MAX_DURATION_HOURS, which puts the button back to "start".
        mockDashboard(
            productivity({ sleep_patterns: sleepPatterns({ has_open_session: false }) })
        );
        renderDashboard();

        fireEvent.click(await screen.findByRole('button', { name: /log sleep now/i }));

        await waitFor(() => expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1));
        expect(analyticsAPI.postEvent.mock.calls[0][0].event_type).toBe('sleep.started');
    });

    test('the refreshed payload updates the panel', async () => {
        mockDashboard(
            productivity({
                sleep_patterns: sleepPatterns({
                    nights_observed: 0,
                    nights_with_duration: 0,
                    nights: [],
                    avg_sleep_duration_hours: null,
                }),
            })
        );
        renderDashboard();

        expect(await screen.findByText(/No sleep history yet/i)).toBeInTheDocument();

        // Next reload returns a measured night
        dashboardAPI.getProductivity.mockResolvedValue({ data: productivity() });

        fireEvent.click(screen.getByRole('button', { name: /log sleep now/i }));

        await waitFor(() =>
            expect(screen.queryByText(/No sleep history yet/i)).not.toBeInTheDocument()
        );
        expect(screen.getByText('8h 00m')).toBeInTheDocument();
    });

    test('a failed ingest leaves the button usable', async () => {
        mockDashboard(productivity());
        analyticsAPI.postEvent.mockRejectedValue(new Error('offline'));
        renderDashboard();

        const button = await screen.findByRole('button', { name: /log sleep now/i });
        fireEvent.click(button);

        await waitFor(() => expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1));
        await waitFor(() =>
            expect(screen.getByRole('button', { name: /log sleep now/i })).toBeEnabled()
        );
    });
});

describe('Log sleep now — duplicate protection', () => {
    test('a rapid double click records only one event', async () => {
        mockDashboard(productivity());
        renderDashboard();

        const button = await screen.findByRole('button', { name: /log sleep now/i });
        fireEvent.click(button);
        fireEvent.click(button);

        await waitFor(() => expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1));
        // Let the reload settle so a queued second call would have surfaced
        await waitFor(() => expect(dashboardAPI.getProductivity).toHaveBeenCalledTimes(2));
        expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1);
        expect(analyticsAPI.postEvent.mock.calls[0][0].event_type).toBe('sleep.started');
    });

    test('a triple click still records only one event', async () => {
        mockDashboard(productivity());
        renderDashboard();

        const button = await screen.findByRole('button', { name: /log sleep now/i });
        fireEvent.click(button);
        fireEvent.click(button);
        fireEvent.click(button);

        await waitFor(() => expect(dashboardAPI.getProductivity).toHaveBeenCalledTimes(2));
        expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1);
    });

    test('clicking again right after the request settles is still ignored', async () => {
        mockDashboard(productivity());
        renderDashboard();

        const button = await screen.findByRole('button', { name: /log sleep now/i });
        fireEvent.click(button);
        // Wait for the first call to fully settle — the in-flight latch is released
        await waitFor(() => expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1));
        await waitFor(() => expect(button).toBeEnabled());

        fireEvent.click(button);

        await waitFor(() => expect(dashboardAPI.getProductivity).toHaveBeenCalledTimes(2));
        // The cooldown, not the latch, blocks this one
        expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1);
    });

    test('a failed attempt does not start a cooldown, so a retry goes through', async () => {
        mockDashboard(productivity());
        analyticsAPI.postEvent.mockRejectedValueOnce(new Error('offline'));
        renderDashboard();

        const button = await screen.findByRole('button', { name: /log sleep now/i });
        fireEvent.click(button);
        await waitFor(() => expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1));
        await waitFor(() => expect(button).toBeEnabled());

        fireEvent.click(button);

        await waitFor(() => expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(2));
    });
});

describe('Correlations panel wiring', () => {
    test('is hidden when the payload carries no correlations', async () => {
        mockDashboard(productivity({ correlations: null }));
        renderDashboard();

        await screen.findByRole('button', { name: /log sleep now/i });
        expect(
            screen.queryByText(/Behaviour ↔ Productivity Correlations/i)
        ).not.toBeInTheDocument();
    });

    test('renders measured pairs straight from /dashboard/productivity', async () => {
        mockDashboard(
            productivity({
                correlations: {
                    status: 'ok',
                    method: {
                        coefficients: ['pearson', 'spearman'],
                        significance_test: 'fisher_z',
                        alpha: 0.05,
                        min_pairs: 5,
                    },
                    window_days: 30,
                    days_analyzed: 14,
                    pairs: [
                        {
                            id: 'snooze_vs_accuracy',
                            behavior: 'snooze_count',
                            behavior_label: 'daily snoozes',
                            outcome: 'challenge_accuracy',
                            outcome_label: 'challenge accuracy',
                            expected_direction: 'negative',
                            status: 'ok',
                            n: 14,
                            min_pairs: 5,
                            pearson_r: -0.91,
                            spearman_rho: -0.9,
                            p_value: 0.0001,
                            significant: true,
                            strength: 'very_strong',
                            direction: 'negative',
                            interpretation: 'Very strong negative link.',
                        },
                    ],
                    significant_findings: ['snooze_vs_accuracy'],
                    strongest: null,
                    insights: [],
                },
            })
        );
        renderDashboard();

        expect(
            await screen.findByText(/Behaviour ↔ Productivity Correlations/i)
        ).toBeInTheDocument();
        expect(screen.getByText('-0.91')).toBeInTheDocument();
        expect(screen.getByText('Significant')).toBeInTheDocument();
    });
});
