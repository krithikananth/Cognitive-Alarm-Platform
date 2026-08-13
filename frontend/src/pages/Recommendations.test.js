/**
 * Recommendations page — the user-facing rule-engine feed.
 *
 * Pins the three things the page owes the engine: the daily digest renders
 * separately from the full feed, the category chips filter against
 * `by_category` (the counts the backend already computed), and a failed feed
 * request shows an error with a working retry instead of an empty list that
 * would read as "you have no advice".
 */
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

jest.mock('../services/api');

import { recommendationAPI } from '../services/api';
import Recommendations from './Recommendations';

function rec(id, category, priority, title) {
  return {
    id,
    category,
    priority,
    title,
    detail: `${title} detail`,
    action_hint: 'Open Profile',
    action_path: '/profile',
    confidence: 0.8,
    metrics: {},
  };
}

const SLEEP = rec('sleep-bedtime-anchor', 'sleep', 'medium', 'Aim for lights-out near 23:00');
const WAKE = rec('wake-reduce-snooze', 'wake', 'high', 'Cut morning snoozes');
const HABIT = rec('habit-raise-score', 'habit', 'medium', 'Raise habit score');
const PRODUCTIVITY = rec('productivity-set-goals', 'productivity', 'high', 'Save your goals');
const CHALLENGE = rec('challenge-practice_focus-math', 'challenge', 'high', 'Focus on math challenges');

const ALL = [WAKE, PRODUCTIVITY, CHALLENGE, SLEEP, HABIT];

function feed(overrides = {}) {
  return {
    generated_at: '2026-08-11T06:00:00Z',
    summary: {
      habit_score: 62,
      wake_consistency: 71,
      streak_days: 3,
      best_streak: 9,
      sleep_target_hours: 8,
      preferred_wake_time: '07:00',
      suggested_bedtime: '23:00',
      goals_count: 2,
      top_focus: 'wake',
      top_focus_label: 'Wake discipline',
    },
    insights: ['Snooze rate is 42% over your last 21 wake-ups.'],
    recommendations: ALL,
    by_category: {
      sleep: [SLEEP],
      wake: [WAKE],
      habit: [HABIT],
      productivity: [PRODUCTIVITY],
      challenge: [CHALLENGE],
    },
    daily_plan: {
      suggested_bedtime: '23:00',
      suggested_wake_time: '07:00',
      morning_focus: 'Deep work block',
      priority_actions: ['Put the phone across the room tonight'],
    },
    ...overrides,
  };
}

function digest(overrides = {}) {
  return {
    ...feed(),
    recommendations: [WAKE, PRODUCTIVITY],
    by_category: { sleep: [], wake: [WAKE], habit: [], productivity: [PRODUCTIVITY], challenge: [] },
    ...overrides,
  };
}

function relevance(overrides = {}) {
  return {
    days: null,
    responses: 0,
    rated: 0,
    helpful: 0,
    not_helpful: 0,
    dismissed: 0,
    relevance_rate: 0,
    avg_stated_confidence: null,
    confidence_gap: null,
    status: 'no_data',
    min_responses: 3,
    by_category: {},
    by_priority: {},
    last_feedback_at: null,
    ...overrides,
  };
}

function renderPage() {
  return render(
    <MemoryRouter>
      <Recommendations />
    </MemoryRouter>
  );
}

beforeEach(() => {
  jest.clearAllMocks();
  recommendationAPI.getAll.mockResolvedValue({ data: feed() });
  recommendationAPI.getDaily.mockResolvedValue({ data: digest() });
  recommendationAPI.getRelevance.mockResolvedValue({ data: relevance() });
  recommendationAPI.getSleep.mockResolvedValue({
    data: { category: 'sleep', insights: ['Lights-out drifted 40 minutes later this week.'], recommendations: [SLEEP] },
  });
  recommendationAPI.getWake.mockResolvedValue({
    data: { category: 'wake', insights: [], recommendations: [WAKE, HABIT] },
  });
  recommendationAPI.getProductivity.mockResolvedValue({
    data: { category: 'productivity', insights: [], recommendations: [PRODUCTIVITY] },
  });
  recommendationAPI.sendFeedback.mockResolvedValue({ data: {} });
  recommendationAPI.clearFeedback.mockResolvedValue({ data: null });
});

describe('Recommendations page', () => {
  test('renders the daily plan and the full feed from both endpoints', async () => {
    renderPage();

    expect(await screen.findByText("Today's Plan")).toBeInTheDocument();
    expect(recommendationAPI.getAll).toHaveBeenCalledTimes(1);
    expect(recommendationAPI.getDaily).toHaveBeenCalledTimes(1);

    expect(screen.getByText('Deep work block')).toBeInTheDocument();
    expect(screen.getByText('Put the phone across the room tonight')).toBeInTheDocument();
    expect(screen.getByText('62/100')).toBeInTheDocument();
    expect(
      screen.getByText('Snooze rate is 42% over your last 21 wake-ups.')
    ).toBeInTheDocument();

    // Every category the engine produced reaches the user, not just challenge.
    expect(screen.getByText('Aim for lights-out near 23:00')).toBeInTheDocument();
    expect(screen.getByText('Raise habit score')).toBeInTheDocument();
    expect(screen.getByText('Focus on math challenges')).toBeInTheDocument();
    // Wake + productivity appear in both the digest and the full feed.
    expect(screen.getAllByText('Cut morning snoozes')).toHaveLength(2);
    expect(screen.getAllByText('Save your goals')).toHaveLength(2);
  });

  test('category chips carry backend counts and filter the feed', async () => {
    renderPage();

    const sleepChip = await screen.findByRole('button', { name: 'Sleep · 1' });
    expect(screen.getByRole('button', { name: 'All · 5' })).toBeInTheDocument();

    fireEvent.click(sleepChip);

    expect(sleepChip).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByText('Aim for lights-out near 23:00')).toBeInTheDocument();
    expect(screen.queryByText('Raise habit score')).not.toBeInTheDocument();
    // The digest section keeps rendering its own items while a filter is on.
    expect(screen.getAllByText('Cut morning snoozes')).toHaveLength(1);

    // Selecting a category also loads its scoped insights; settle that request
    // before moving on so the assertions below are not racing it.
    await waitFor(() => expect(recommendationAPI.getSleep).toHaveBeenCalled());
    await screen.findByText('Lights-out drifted 40 minutes later this week.');

    fireEvent.click(screen.getByRole('button', { name: 'All · 5' }));
    expect(screen.getByText('Raise habit score')).toBeInTheDocument();
  });

  test('an empty category reports itself instead of looking like no advice', async () => {
    recommendationAPI.getAll.mockResolvedValue({
      data: feed({
        recommendations: [WAKE],
        by_category: { sleep: [], wake: [WAKE], habit: [], productivity: [], challenge: [] },
      }),
    });
    renderPage();

    fireEvent.click(await screen.findByRole('button', { name: 'Sleep · 0' }));

    expect(
      screen.getByText(/No Sleep recommendations in this feed right now/i)
    ).toBeInTheDocument();
  });

  test('a failed feed request shows an error with a retry, not an empty list', async () => {
    recommendationAPI.getAll.mockRejectedValue(new Error('boom'));
    renderPage();

    const alerts = await screen.findAllByRole('alert');
    expect(alerts.length).toBeGreaterThan(0);

    recommendationAPI.getAll.mockResolvedValue({ data: feed() });
    fireEvent.click(screen.getAllByRole('button', { name: /try again/i })[0]);

    await waitFor(() => expect(recommendationAPI.getAll).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('Raise habit score')).toBeInTheDocument();
  });

  test('the daily digest failing does not take the full feed down with it', async () => {
    recommendationAPI.getDaily.mockRejectedValue(new Error('boom'));
    renderPage();

    expect(await screen.findByText('Raise habit score')).toBeInTheDocument();
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });
});

describe('Recommendation relevance feedback', () => {
  test('rating a card sends the verdict and refreshes the measurement', async () => {
    renderPage();

    const button = await screen.findByRole('button', {
      name: 'Helpful: Raise habit score',
    });
    fireEvent.click(button);

    await waitFor(() => expect(button).toHaveAttribute('aria-pressed', 'true'));
    expect(recommendationAPI.sendFeedback).toHaveBeenCalledWith(
      'habit-raise-score',
      'helpful'
    );
    // The report is re-read so the panel reflects the new verdict
    await waitFor(() =>
      expect(recommendationAPI.getRelevance).toHaveBeenCalledTimes(2)
    );
  });

  test('clicking the active verdict again clears it', async () => {
    recommendationAPI.getAll.mockResolvedValue({
      data: feed({
        recommendations: [{ ...HABIT, feedback: 'helpful' }],
        by_category: {
          sleep: [],
          wake: [],
          habit: [{ ...HABIT, feedback: 'helpful' }],
          productivity: [],
          challenge: [],
        },
      }),
    });
    renderPage();

    const button = await screen.findByRole('button', {
      name: 'Helpful: Raise habit score',
    });
    expect(button).toHaveAttribute('aria-pressed', 'true');

    fireEvent.click(button);

    await waitFor(() => expect(button).toHaveAttribute('aria-pressed', 'false'));
    expect(recommendationAPI.clearFeedback).toHaveBeenCalledWith('habit-raise-score');
    expect(recommendationAPI.sendFeedback).not.toHaveBeenCalled();
  });

  test('too little feedback asks for more instead of publishing a rate', async () => {
    recommendationAPI.getRelevance.mockResolvedValue({
      data: relevance({ responses: 1, rated: 1, helpful: 1, relevance_rate: 100 }),
    });
    renderPage();

    expect(
      await screen.findByText(/Rate 2 more recommendations to see how relevant/i)
    ).toBeInTheDocument();
    expect(screen.queryByText('Relevance')).not.toBeInTheDocument();
  });

  test('a measured rate is shown against the confidence the engine claimed', async () => {
    recommendationAPI.getRelevance.mockResolvedValue({
      data: relevance({
        status: 'ok',
        responses: 6,
        rated: 4,
        helpful: 3,
        not_helpful: 1,
        dismissed: 2,
        relevance_rate: 75,
        avg_stated_confidence: 90,
        confidence_gap: -15,
        by_category: {
          sleep: {
            responses: 4,
            rated: 4,
            helpful: 3,
            not_helpful: 1,
            dismissed: 0,
            relevance_rate: 75,
            avg_stated_confidence: 90,
            confidence_gap: -15,
          },
        },
      }),
    });
    renderPage();

    expect(await screen.findByText('75%')).toBeInTheDocument();
    expect(screen.getByText('3 of 4 rated helpful')).toBeInTheDocument();
    expect(screen.getByText('90%')).toBeInTheDocument();
    expect(screen.getByText('-15 pts vs measured')).toBeInTheDocument();
    expect(screen.getByText('Not counted in the rate')).toBeInTheDocument();
    expect(screen.getByText('75% · 3/4')).toBeInTheDocument();
  });

  test('a failed relevance read never blanks the advice itself', async () => {
    recommendationAPI.getRelevance.mockRejectedValue(new Error('boom'));
    renderPage();

    expect(await screen.findByText('Raise habit score')).toBeInTheDocument();
    expect(
      screen.getByText(/Rate at least 3 recommendations as helpful or not helpful/i)
    ).toBeInTheDocument();
  });
});
