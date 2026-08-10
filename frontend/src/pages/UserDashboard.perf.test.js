/**
 * UI responsiveness budgets for the user dashboard.
 *
 * This is the browser-side half of the performance suite: `perf/benchmark.py`
 * measures how fast the API answers, this measures how long the app then takes
 * to turn a full-size payload into rendered UI.
 *
 * Scope, honestly stated: jsdom does no layout or paint, so these numbers are
 * React reconciliation + chart data preparation, not Largest Contentful Paint.
 * That is still the part of UI latency this repository owns and can regress —
 * an accidental O(n^2) derivation or a lost `useMemo` shows up here.
 *
 * Payloads are sized like a real active account (90-day trend series, a full
 * challenge-type breakdown, 24-hour and 7-day histograms). Fixtures are
 * `mock`-prefixed so the hoisted `jest.mock` factories may reference them.
 */
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';

// Budgets are deliberately loose: they exist to catch order-of-magnitude
// regressions on varied CI hardware, not to police a few milliseconds.
const MOUNT_BUDGET_MS = 1500;
const DATA_RENDER_BUDGET_MS = 3000;
const INTERACTION_BUDGET_MS = 2000;

const mockSeries = Array.from({ length: 90 }, (_, i) => ({
  date: `2026-05-${String((i % 28) + 1).padStart(2, '0')}`,
  verified_wakes: (i % 3) + 1,
  snoozes: i % 4,
  on_time_wakes: i % 2,
  habit_score: 60 + (i % 30),
}));

const mockWakeStats = {
  total_wake_events: 300,
  verified_wakes: 264,
  abandoned_wakes: 36,
  success_rate: 88,
  first_try_success_rate: 70,
  avg_time_to_dismiss_seconds: 62,
  avg_snoozes_before_dismiss: 0.6,
  avg_failed_attempts: 0.3,
  by_weekday: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'].map((weekday, i) => ({
    weekday,
    count: 30 + i,
  })),
  by_hour: Array.from({ length: 24 }, (_, hour) => ({ hour, count: hour % 9 })),
};

const mockChallengePerf = {
  total_attempts: 900,
  accuracy: 82,
  total_points_earned: 5400,
  best_type: 'math',
  worst_type: 'riddle',
  by_type: {
    math: { total: 220, correct: 190, accuracy: 86.4 },
    logic: { total: 180, correct: 140, accuracy: 77.8 },
    memory: { total: 120, correct: 88, accuracy: 73.3 },
    word_game: { total: 140, correct: 121, accuracy: 86.4 },
    pattern: { total: 110, correct: 84, accuracy: 76.4 },
    riddle: { total: 90, correct: 61, accuracy: 67.8 },
    quiz: { total: 40, correct: 33, accuracy: 82.5 },
  },
  trend: { direction: 'improving', previous_accuracy: 78, recent_accuracy: 85 },
};

const mockProductivity = {
  verified_wakes: 264,
  morning_routine_score: 78,
  cognitive_readiness_score: 81,
  consistency_rate: 74,
  active_days_in_period: 27,
  days: 30,
  current_streak: 12,
  challenge_accuracy: 82,
  avg_wakefulness: 76,
  avg_time_to_productive_seconds: 300,
  trend: {
    direction: 'improving',
    previous_clean_wake_rate: 60,
    recent_clean_wake_rate: 72,
  },
};

const mockHabitTrend = {
  current_habit_score: 72.4,
  trend: 'improving',
  weights: {
    wake_up_consistency: 0.35,
    challenge_completion: 0.25,
    snooze_reduction: 0.2,
    sleep_adherence: 0.2,
  },
  current_breakdown: {
    wake_up_consistency: 81.2,
    challenge_completion: 82.0,
    snooze_reduction: 74.5,
    sleep_adherence: 66.7,
  },
};

const mockHistoryEvents = Array.from({ length: 6 }, (_, i) => ({
  id: i + 1,
  alarm_id: 100 + i,
  event_type: i % 2 === 0 ? 'dismissed' : 'snoozed',
  timestamp: '2026-08-09T07:03:00Z',
  verified: i % 2 === 0,
  snooze_count: i % 3,
}));

// Plain functions, not jest.fn(): CRA enables `resetMocks`, which would strip
// mock implementations before each test.
jest.mock('../services/api', () => ({
  __esModule: true,
  userAPI: {
    getStats: () =>
      Promise.resolve({
        data: {
          active_alarms: 4,
          current_streak: 12,
          wakeup_success_rate: 87.5,
          current_habit_score: 72.4,
        },
      }),
  },
  dashboardAPI: {
    getSummary: () =>
      Promise.resolve({
        data: {
          period_stats: { total_snoozes: 40, verified_wakes: 264 },
          habit_score_breakdown: mockHabitTrend.current_breakdown,
        },
      }),
    getWakeStats: () => Promise.resolve({ data: mockWakeStats }),
    getChallengePerformance: () => Promise.resolve({ data: mockChallengePerf }),
    getProductivity: () => Promise.resolve({ data: mockProductivity }),
    getAlarmHistory: () =>
      Promise.resolve({ data: { events: mockHistoryEvents, total: 240, page: 1 } }),
  },
  analyticsAPI: {
    getHabitTrends: () => Promise.resolve({ data: mockHabitTrend }),
    getMonthlyTrends: () => Promise.resolve({ data: { series: mockSeries } }),
  },
}));

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

// eslint-disable-next-line import/first
import UserDashboard from './UserDashboard';

beforeEach(() => {
  mockAuthState = {
    user: { id: 1, role: 'user', username: 'sam', full_name: 'Sam Rivers' },
  };
  mockAlarmState = {
    alarms: Array.from({ length: 8 }, (_, i) => ({
      id: i + 1,
      title: `Alarm ${i + 1}`,
      alarm_time: '07:00',
      is_active: i % 2 === 0,
    })),
    fetchAlarms: () => { },
    fetchUpcoming: () => { },
  };
});

function renderDashboard() {
  return render(
    <MemoryRouter>
      <UserDashboard />
    </MemoryRouter>,
  );
}

describe('UserDashboard rendering performance', () => {
  test('mounts and renders a full-size payload within budget', async () => {
    const startedAt = performance.now();
    renderDashboard();
    const mountMs = performance.now() - startedAt;

    // A data-derived label proves the cards and charts actually rendered.
    await screen.findByText('Overall accuracy');
    const dataMs = performance.now() - startedAt;

    // eslint-disable-next-line no-console
    console.log(
      `[perf] UserDashboard mount=${mountMs.toFixed(1)}ms data=${dataMs.toFixed(1)}ms`,
    );

    expect(mountMs).toBeLessThan(MOUNT_BUDGET_MS);
    expect(dataMs).toBeLessThan(DATA_RENDER_BUDGET_MS);
  });

  test('stays responsive when the dashboard is refreshed', async () => {
    renderDashboard();
    await screen.findByText('Overall accuracy');

    const refresh = screen.getByLabelText('Refresh dashboard');
    const startedAt = performance.now();
    fireEvent.click(refresh);
    await waitFor(() => expect(refresh).not.toBeDisabled());
    const interactionMs = performance.now() - startedAt;

    // eslint-disable-next-line no-console
    console.log(`[perf] UserDashboard refresh=${interactionMs.toFixed(1)}ms`);

    expect(interactionMs).toBeLessThan(INTERACTION_BUDGET_MS);
    expect(screen.getByText('Overall accuracy')).toBeInTheDocument();
  });
});
