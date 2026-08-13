/**
 * Dashboard behaviour analytics: snooze pattern and sleep-schedule adherence.
 *
 * Both endpoints were built and wrapped but never called, so the two habit
 * sub-scores ("Snooze control", "Sleep adherence") were shown as bare numbers
 * with nothing behind them. The weekly trend endpoint was likewise unused —
 * the weekly view was quietly backed by the monthly aggregate.
 */
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

jest.mock('../services/api');

let mockAuthState;
let mockAlarmState;

jest.mock('../store/authStore', () => ({
    __esModule: true,
    default: (selector) => (selector ? selector(mockAuthState) : mockAuthState),
}));

jest.mock('../store/alarmStore', () => ({
    __esModule: true,
    default: (selector) => (selector ? selector(mockAlarmState) : mockAlarmState),
}));

import { analyticsAPI, dashboardAPI, userAPI } from '../services/api';
import UserDashboard from './UserDashboard';

const EMPTY_SERIES = { series: [], totals: {}, trend: 'insufficient_data' };

const SNOOZE_PATTERN = {
    total_snoozes: 31,
    avg_snoozes_per_wake: 0.74,
    avg_snooze_number: 1.3,
    limit_hit_count: 4,
    limit_hit_rate: 12.9,
    by_hour: [],
    by_weekday: [],
    peak_hour: 6,
    peak_weekday: 'Mon',
    trend: 'improving',
    recent_7d_count: 5,
    previous_7d_count: 9,
    reduction: {
        period_days: 7,
        status: 'ok',
        direction: 'improving',
        reduction_rate: 31.2,
        current_snoozes_per_wake: 0.55,
        previous_snoozes_per_wake: 0.8,
    },
};

const SLEEP_ADHERENCE = {
    preferred_wake_time: '07:00',
    target_sleep_hours: 8,
    suggested_bedtime: '23:00',
    adherence_rate: 68.4,
    adherent_days: 13,
    observed_days: 19,
    avg_deviation_minutes: 22.5,
    profile_streak_days: 4,
    profile_adherence_score: 68.4,
    tolerance_minutes: 30,
    trend: 'stable',
};

function mockDashboard() {
    userAPI.getStats.mockResolvedValue({ data: {} });
    dashboardAPI.getSummary.mockResolvedValue({ data: {} });
    dashboardAPI.getWakeStats.mockResolvedValue({ data: { total_wake_events: 0 } });
    dashboardAPI.getChallengePerformance.mockResolvedValue({ data: { total_attempts: 0 } });
    dashboardAPI.getProductivity.mockResolvedValue({ data: { days: 7 } });
    dashboardAPI.getAlarmHistory.mockResolvedValue({
        data: { events: [], total: 0, page: 1 },
    });
    analyticsAPI.getHabitTrends.mockResolvedValue({ data: EMPTY_SERIES });
    analyticsAPI.getWeeklyTrends.mockResolvedValue({ data: EMPTY_SERIES });
    analyticsAPI.getMonthlyTrends.mockResolvedValue({ data: EMPTY_SERIES });
    analyticsAPI.getVerificationAccuracy.mockResolvedValue({
        data: { status: 'insufficient_data', decisions: 0, min_decisions_required: 3 },
    });
    analyticsAPI.getSnoozePattern.mockResolvedValue({ data: SNOOZE_PATTERN });
    analyticsAPI.getSleepAdherence.mockResolvedValue({ data: SLEEP_ADHERENCE });
}

beforeEach(() => {
    mockAuthState = { user: { id: 1, role: 'user', username: 'sam' } };
    mockAlarmState = { alarms: [], fetchAlarms: () => { }, fetchUpcoming: () => { } };
    mockDashboard();
});

function renderDashboard() {
    return render(
        <MemoryRouter>
            <UserDashboard />
        </MemoryRouter>
    );
}

describe('snooze and sleep schedule panel', () => {
    it('loads both behaviour endpoints for the selected period', async () => {
        renderDashboard();

        await waitFor(() => expect(analyticsAPI.getSnoozePattern).toHaveBeenCalledWith(7));
        expect(analyticsAPI.getSleepAdherence).toHaveBeenCalledWith(7);
    });

    it('renders the measured snooze figures', async () => {
        renderDashboard();

        expect(await screen.findByText('0.74')).toBeInTheDocument();
        expect(screen.getByText('31')).toBeInTheDocument();
        expect(screen.getByText('4 times (12.9%)')).toBeInTheDocument();
        expect(
            screen.getByText('Snooze reduction +31.2% vs the previous 7 days')
        ).toBeInTheDocument();
    });

    it('renders the measured sleep-schedule figures', async () => {
        renderDashboard();

        expect(await screen.findByText('68.4%')).toBeInTheDocument();
        expect(screen.getByText('13/19')).toBeInTheDocument();
        expect(screen.getByText('22.5 min')).toBeInTheDocument();
        expect(
            screen.getByText(/within 30 minutes of your goal\. Current streak 4d\./)
        ).toBeInTheDocument();
    });

    it('says so when the behaviour endpoints fail, instead of showing zeros', async () => {
        analyticsAPI.getSnoozePattern.mockRejectedValue(new Error('boom'));
        analyticsAPI.getSleepAdherence.mockRejectedValue(new Error('boom'));
        renderDashboard();

        expect(
            await screen.findByText('Behaviour analytics could not be loaded for this period.')
        ).toBeInTheDocument();
    });
});

describe('trend series matches the selected period', () => {
    it('uses the weekly aggregate for the weekly view', async () => {
        renderDashboard();

        await waitFor(() => expect(analyticsAPI.getWeeklyTrends).toHaveBeenCalledWith(7));
        expect(analyticsAPI.getMonthlyTrends).not.toHaveBeenCalled();
    });

    it('switches to the monthly aggregate for the monthly view', async () => {
        renderDashboard();
        await waitFor(() => expect(analyticsAPI.getWeeklyTrends).toHaveBeenCalled());

        fireEvent.click(screen.getByRole('button', { name: /monthly/i }));

        await waitFor(() => expect(analyticsAPI.getMonthlyTrends).toHaveBeenCalledWith(30));
        expect(analyticsAPI.getSnoozePattern).toHaveBeenCalledWith(30);
    });
});
