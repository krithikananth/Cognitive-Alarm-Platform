/**
 * User dashboard — the Verification Accuracy panel.
 *
 * Pins that the dashboard reports how accurately the wake-up check decided,
 * which is a different number from the wake-up success rate rendered beside
 * it: every wake here succeeded, yet one verdict was reached without the
 * required evidence.
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

const EMPTY_SERIES = { series: [], totals: {}, trend: 'insufficient_data' };

beforeEach(() => {
  jest.clearAllMocks();
  useAuthStore.mockReturnValue({ user: { id: 1, role: 'user', full_name: 'Test' } });
  useAlarmStore.mockReturnValue({
    alarms: [],
    fetchAlarms: jest.fn(),
    fetchUpcoming: jest.fn(),
  });
});

function verificationWith(overrides = {}) {
  return {
    decisions: 6,
    verified: 6,
    rejected: 0,
    correct_decisions: 6,
    accuracy_rate: 100,
    false_verifications: 0,
    missed_verifications: 0,
    first_pass_verifications: 3,
    first_pass_rate: 50,
    answers_recorded: 12,
    avg_answers_per_verification: 2,
    avg_wrong_answers_per_verification: 1,
    min_decisions_required: 3,
    status: 'ok',
    integrity: 'consistent',
    ...overrides,
  };
}

function mountWith(verification) {
  userAPI.getStats.mockResolvedValue({ data: {} });
  dashboardAPI.getSummary.mockResolvedValue({ data: {} });
  dashboardAPI.getWakeStats.mockResolvedValue({
    data: {
      total_wake_events: 6,
      verified_wakes: 6,
      success_rate: 100,
      first_try_success_rate: 50,
      avg_time_to_dismiss_seconds: 42,
      avg_snoozes_before_dismiss: 0,
      avg_failed_attempts: 1,
      by_hour: [],
      by_weekday: [],
    },
  });
  dashboardAPI.getChallengePerformance.mockResolvedValue({ data: { total_attempts: 0 } });
  dashboardAPI.getProductivity.mockResolvedValue({ data: { days: 30 } });
  dashboardAPI.getAlarmHistory.mockResolvedValue({
    data: { events: [], total: 0, page: 1 },
  });
  analyticsAPI.getHabitTrends.mockResolvedValue({ data: EMPTY_SERIES });
  analyticsAPI.getMonthlyTrends.mockResolvedValue({ data: EMPTY_SERIES });
  analyticsAPI.getWeeklyTrends.mockResolvedValue({ data: EMPTY_SERIES });
  analyticsAPI.getSnoozePattern.mockResolvedValue({ data: null });
  analyticsAPI.getSleepAdherence.mockResolvedValue({ data: null });
  analyticsAPI.getVerificationAccuracy.mockResolvedValue({ data: verification });
  analyticsAPI.postEvent.mockResolvedValue({ data: { id: 1 } });
  return render(
    <MemoryRouter>
      <UserDashboard />
    </MemoryRouter>
  );
}

describe('Verification accuracy panel', () => {
  test('reports the share of verdicts that matched the evidence held', async () => {
    mountWith(verificationWith());

    expect(await screen.findByText('Verification Accuracy')).toBeInTheDocument();
    const caption = await screen.findByText('6 of 6 verdicts matched the evidence held');
    // '100%' also renders as the wake-up success rate, so scope to this card
    expect(caption.closest('div')).toHaveTextContent('100%');
  });

  test('is not the wake-up success rate: a perfect success rate can hide a bad verdict', async () => {
    mountWith(
      verificationWith({
        correct_decisions: 5,
        accuracy_rate: 83.33,
        false_verifications: 1,
        integrity: 'inconsistent',
      })
    );

    // The wake-up panel still reports 100% success for the same six wakes
    expect(await screen.findByText('100%')).toBeInTheDocument();
    expect(screen.getByText('83.33%')).toBeInTheDocument();
    expect(
      screen.getByText('5 of 6 verdicts matched the evidence held')
    ).toBeInTheDocument();
  });

  test('too few finished wake-ups explains the requirement instead of a number', async () => {
    mountWith(
      verificationWith({
        decisions: 1,
        verified: 1,
        correct_decisions: 1,
        accuracy_rate: null,
        first_pass_rate: null,
        avg_answers_per_verification: null,
        status: 'insufficient_data',
        integrity: 'unknown',
      })
    );

    expect(await screen.findByText('Verification Accuracy')).toBeInTheDocument();
    expect(
      screen.getByText(/Needs 3 completed wake-ups in this window \(1 so far\)/i)
    ).toBeInTheDocument();
  });
});
