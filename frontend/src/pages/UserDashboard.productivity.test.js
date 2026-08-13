/**
 * User dashboard — the Productivity Insights comparison.
 *
 * This panel used to compare clean-wake rate between halves and label that
 * "productivity". These tests pin that it now reports movement in the real
 * productivity scores, and specifically that a rising clean-wake rate does
 * not read as an improvement when cognitive readiness fell.
 */
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';

jest.mock('../services/api');
jest.mock('../store/authStore');
jest.mock('../store/alarmStore');
jest.mock('react-hot-toast', () => ({
  __esModule: true,
  default: { success: jest.fn(), error: jest.fn() },
  Toaster: () => null,
}));

import { userAPI, dashboardAPI, analyticsAPI } from '../services/api';
import useAuthStore from '../store/authStore';
import useAlarmStore from '../store/alarmStore';
import UserDashboard from './UserDashboard';

beforeEach(() => {
  jest.clearAllMocks();
  useAuthStore.mockReturnValue({ user: { id: 1, role: 'user', full_name: 'Test' } });
  useAlarmStore.mockReturnValue({
    alarms: [],
    fetchAlarms: jest.fn(),
    fetchUpcoming: jest.fn(),
  });
});

function metric(previous, current) {
  return {
    previous,
    current,
    change: Number((current - previous).toFixed(1)),
    change_pct: previous
      ? Number((((current - previous) / previous) * 100).toFixed(1))
      : null,
  };
}

function improvementWith(overrides = {}) {
  return {
    period_days: 15,
    current_period_start: '2026-07-28T12:00:00+00:00',
    current_period_end: '2026-08-12T12:00:00+00:00',
    previous_period_start: '2026-07-13T12:00:00+00:00',
    previous_period_end: '2026-07-28T12:00:00+00:00',
    primary_metric: 'cognitive_readiness_score',
    min_wakes: 2,
    min_attempts: 3,
    previous: { verified_wakes: 6, challenge_attempts: 12 },
    current: { verified_wakes: 7, challenge_attempts: 14 },
    metrics: {
      cognitive_readiness_score: metric(52, 84),
      morning_routine_score: metric(40, 80),
      challenge_accuracy: metric(50, 90),
      avg_wakefulness: metric(55, 75),
    },
    change: 32,
    improvement_rate: 61.5,
    direction: 'improving',
    status: 'ok',
    ...overrides,
  };
}

function productivityWith(improvement) {
  return {
    days: 30,
    verified_wakes: 13,
    morning_routine_score: 62,
    cognitive_readiness_score: 70,
    habit_score: 71,
    habit_score_breakdown: {
      wake_up_consistency: 80,
      challenge_completion: 70,
      snooze_reduction: 100,
      sleep_adherence: 20,
    },
    active_days_in_period: 13,
    consistency_rate: 43,
    current_streak: 4,
    best_streak: 9,
    challenge_accuracy: 72,
    avg_wakefulness: 66,
    avg_time_to_productive_seconds: 240,
    productivity_improvement: improvement,
    trend: {
      direction: 'improving',
      recent_clean_wake_rate: 80,
      previous_clean_wake_rate: 40,
      change: 40,
    },
    goals: [],
    goals_count: 0,
    sleep_patterns: null,
    correlations: null,
  };
}

function mountWith(improvement) {
  userAPI.getStats.mockResolvedValue({ data: {} });
  dashboardAPI.getSummary.mockResolvedValue({ data: {} });
  dashboardAPI.getWakeStats.mockResolvedValue({ data: { total_wake_events: 0 } });
  dashboardAPI.getChallengePerformance.mockResolvedValue({
    data: { total_attempts: 0 },
  });
  dashboardAPI.getProductivity.mockResolvedValue({
    data: productivityWith(improvement),
  });
  dashboardAPI.getAlarmHistory.mockResolvedValue({
    data: { events: [], total: 0, page: 1 },
  });
  analyticsAPI.getHabitTrends.mockResolvedValue({
    data: { series: [], totals: {}, trend: 'insufficient_data' },
  });
  analyticsAPI.getMonthlyTrends.mockResolvedValue({
    data: { series: [], totals: {}, trend: 'insufficient_data' },
  });
  analyticsAPI.getWeeklyTrends.mockResolvedValue({
    data: { series: [], totals: {}, trend: 'insufficient_data' },
  });
  analyticsAPI.getSnoozePattern.mockResolvedValue({ data: null });
  analyticsAPI.getSleepAdherence.mockResolvedValue({ data: null });
  analyticsAPI.getVerificationAccuracy.mockResolvedValue({
    data: { status: 'insufficient_data', decisions: 0, min_decisions_required: 3 },
  });
  analyticsAPI.postEvent.mockResolvedValue({ data: { id: 1 } });
  return render(
    <MemoryRouter>
      <UserDashboard />
    </MemoryRouter>
  );
}

describe('Productivity improvement panel', () => {
  test('compares the real productivity scores across two equal periods', async () => {
    mountWith(improvementWith());

    expect(
      await screen.findByText('Productivity: last 15 days vs the 15 before')
    ).toBeInTheDocument();
    expect(screen.getByText('Cognitive readiness +61.5%')).toBeInTheDocument();
    expect(
      screen.getByText(/Headline movement is measured on cognitive readiness/i)
    ).toBeInTheDocument();
    // The old panel only ever charted clean-wake rate
    expect(
      screen.queryByText('Clean Wake Rate: Recent vs Previous')
    ).not.toBeInTheDocument();
  });

  test('a rising clean-wake rate does not mask falling readiness', async () => {
    mountWith(
      improvementWith({
        metrics: {
          cognitive_readiness_score: metric(88, 41),
          morning_routine_score: metric(20, 100),
          challenge_accuracy: metric(95, 30),
          avg_wakefulness: metric(78, 58),
        },
        change: -47,
        improvement_rate: -53.4,
        direction: 'declining',
      })
    );

    expect(
      await screen.findByText('Cognitive readiness -53.4%')
    ).toBeInTheDocument();
    expect(screen.getByText('Declining')).toBeInTheDocument();
    expect(screen.queryByText('Improving')).not.toBeInTheDocument();
  });

  test('too little history hides the comparison instead of charting zeros', async () => {
    mountWith(
      improvementWith({
        previous: { verified_wakes: 0, challenge_attempts: 0 },
        metrics: {
          cognitive_readiness_score: metric(0, 0),
          morning_routine_score: metric(0, 0),
          challenge_accuracy: metric(0, 0),
          avg_wakefulness: metric(0, 0),
        },
        change: null,
        improvement_rate: null,
        direction: 'insufficient_data',
        status: 'insufficient_data',
      })
    );

    expect(await screen.findByText('Productivity Insights')).toBeInTheDocument();
    expect(
      screen.queryByText(/Productivity: last \d+ days vs the/)
    ).not.toBeInTheDocument();
    expect(screen.queryByText(/Cognitive readiness [+-]/)).not.toBeInTheDocument();
  });
});
