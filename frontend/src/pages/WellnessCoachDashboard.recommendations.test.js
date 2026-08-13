/**
 * Wellness Coach dashboard — composition-level guard.
 *
 * The coach page fetches GET /coach/clients/{id}/recommendations on every
 * client selection. It previously stored the digest and rendered nothing from
 * it, which made the request pure waste and hid the rule-engine output from
 * the coach. This pins that the digest actually reaches the screen.
 */
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';

jest.mock('../store/authStore');
jest.mock('../hooks/useCoachDashboard');

import useAuthStore from '../store/authStore';
import useCoachDashboard from '../hooks/useCoachDashboard';
import WellnessCoachDashboard from './WellnessCoachDashboard';

const CLIENT_ROW = {
  client_id: 7,
  full_name: 'Dana Client',
  username: 'dana',
  email: 'dana@example.com',
  timezone: 'UTC',
  habit_score: 64,
  wake_consistency: 71,
  streak_days: 3,
  verified_wakes: 5,
  challenge_accuracy: 80,
  is_active: true,
};

const DIGEST = {
  generated_at: '2026-08-11T06:00:00Z',
  summary: {
    habit_score: 64,
    preferred_wake_time: '07:00',
    suggested_bedtime: '23:00',
    goals_count: 2,
    top_focus_label: 'Wake discipline',
  },
  insights: [],
  recommendations: [
    {
      id: 'wake-reduce-snooze',
      category: 'wake',
      priority: 'high',
      title: 'Cut morning snoozes',
      detail: 'Snoozed on ~42% of recent wakes.',
      action_hint: 'Lower snooze limit',
      action_path: '/alarms',
      confidence: 0.9,
      metrics: {},
    },
  ],
  by_category: {
    sleep: [],
    wake: [
      {
        id: 'wake-reduce-snooze',
        category: 'wake',
        priority: 'high',
        title: 'Cut morning snoozes',
        detail: 'Snoozed on ~42% of recent wakes.',
        action_hint: 'Lower snooze limit',
        action_path: '/alarms',
        confidence: 0.9,
        metrics: {},
      },
    ],
    habit: [],
    productivity: [],
    challenge: [],
  },
  daily_plan: {
    suggested_bedtime: '23:00',
    suggested_wake_time: '07:00',
    morning_focus: 'Deep work block',
    priority_actions: [],
  },
};

function dashboardState(overrides = {}) {
  return {
    overview: { active_clients: 1, avg_habit_score: 64 },
    clients: [CLIENT_ROW],
    pageMeta: { page: 1, total_pages: 1, total: 1, clients: [CLIENT_ROW] },
    page: 1,
    setPage: jest.fn(),
    searchInput: '',
    setSearchInput: jest.fn(),
    statusFilter: 'all',
    setStatusFilter: jest.fn(),
    sortKey: 'full_name:asc',
    setSortKey: jest.fn(),
    days: 30,
    setDays: jest.fn(),
    rosterLoading: false,
    rosterError: null,
    refreshing: false,
    reloadRoster: jest.fn(),
    refreshAll: jest.fn(),
    selectedId: CLIENT_ROW.client_id,
    setSelectedId: jest.fn(),
    clientRow: CLIENT_ROW,
    clientDetail: null,
    behavioral: null,
    digest: DIGEST,
    productivity: null,
    challenge: null,
    clientErrors: {
      detail: null,
      behavioral: null,
      recommendations: null,
      productivity: null,
      challenge: null,
    },
    clientErrorSummary: null,
    clientLoading: false,
    reloadClient: jest.fn(),
    periodIsLoading: false,
    ...overrides,
  };
}

function renderDashboard(state) {
  useCoachDashboard.mockReturnValue(state);
  return render(
    <MemoryRouter>
      <WellnessCoachDashboard />
    </MemoryRouter>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  useAuthStore.mockReturnValue({
    user: { id: 2, role: 'wellness_coach', full_name: 'Coach' },
    logout: jest.fn(),
  });
});

describe('Coach client recommendations', () => {
  test('the fetched digest is rendered, not discarded', () => {
    renderDashboard(dashboardState());

    expect(screen.getByText('Recommendations')).toBeInTheDocument();
    expect(screen.getByText('Cut morning snoozes')).toBeInTheDocument();
    expect(screen.getByText('Snoozed on ~42% of recent wakes.')).toBeInTheDocument();
    expect(screen.getByText('Focus: Wake discipline')).toBeInTheDocument();
  });

  test('a failed recommendations request shows its own error, not an empty panel', () => {
    renderDashboard(
      dashboardState({
        digest: null,
        clientErrors: {
          detail: null,
          behavioral: null,
          recommendations: 'Coaching recommendations could not be loaded.',
          productivity: null,
          challenge: null,
        },
      })
    );

    expect(
      screen.getByText('Coaching recommendations could not be loaded.')
    ).toBeInTheDocument();
  });
});
