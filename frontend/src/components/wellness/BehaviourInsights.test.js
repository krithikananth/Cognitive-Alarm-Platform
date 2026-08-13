/**
 * Behaviour Insights — the snooze panel must distinguish "this client never
 * snoozed" (a real result) from "there is not enough data to judge".
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import BehaviourInsights from './BehaviourInsights';

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function behavioralWith({ totalSnoozes, verifiedWakes, reduction }) {
  return {
    window_days: 30,
    insights: [],
    snooze_pattern: {
      total_snoozes: totalSnoozes,
      avg_snoozes_per_wake: 0,
      limit_hit_rate: 0,
      peak_weekday: null,
      peak_hour: null,
      trend: 'insufficient_data',
      by_weekday: WEEKDAYS.map((weekday) => ({ weekday, count: 0 })),
      reduction,
    },
    wake_up_consistency: {
      verified_wakes: verifiedWakes,
      trend: 'stable',
      tolerance_minutes: 15,
      rolling_profile_score: 80,
      consistency_score: 72,
      mean_wake_time: '07:00',
      std_wake_minutes: 6,
      on_time_rate: 100,
    },
    sleep_schedule_adherence: {
      trend: 'stable',
      preferred_wake_time: '07:00',
      target_sleep_hours: 8,
      suggested_bedtime: '23:00',
      adherence_rate: 100,
      adherent_days: 4,
      observed_days: 4,
    },
    monthly_trends: { series: [] },
    weekly_trends: { series: [] },
  };
}

describe('Snooze Pattern with zero snoozes', () => {
  test('zero snoozes alongside verified wakes reads as a real "No snoozes" result', () => {
    render(
      <BehaviourInsights
        behavioral={behavioralWith({ totalSnoozes: 0, verifiedWakes: 4 })}
        days={30}
      />
    );

    expect(screen.getByText('Snooze Pattern')).toBeInTheDocument();
    expect(screen.getByText('No snoozes')).toBeInTheDocument();
    expect(screen.queryByText('Not enough data')).not.toBeInTheDocument();
  });

  test('zero snoozes without any verified wake stays "Not enough data"', () => {
    render(
      <BehaviourInsights
        behavioral={behavioralWith({ totalSnoozes: 0, verifiedWakes: 0 })}
        days={30}
      />
    );

    expect(screen.getByText('Not enough data')).toBeInTheDocument();
    expect(screen.queryByText('No snoozes')).not.toBeInTheDocument();
  });

  test('an all-zero weekday breakdown renders the empty-chart message', () => {
    render(
      <BehaviourInsights
        behavioral={behavioralWith({ totalSnoozes: 0, verifiedWakes: 4 })}
        days={30}
      />
    );

    expect(
      screen.getByText(/When this client snoozes an alarm, weekday patterns will appear here/i)
    ).toBeInTheDocument();
  });
});

describe('Snooze reduction row', () => {
  const reductionWith = (overrides) => ({
    period_days: 7,
    current_snoozes: 2,
    previous_snoozes: 8,
    current_wakes: 4,
    previous_wakes: 4,
    current_snoozes_per_wake: 0.5,
    previous_snoozes_per_wake: 2,
    absolute_change_per_wake: -1.5,
    reduction_rate: 75,
    direction: 'improving',
    status: 'ok',
    min_wakes_required: 3,
    ...overrides,
  });

  const renderWith = (reduction) =>
    render(
      <BehaviourInsights
        behavioral={behavioralWith({ totalSnoozes: 2, verifiedWakes: 4, reduction })}
        days={30}
      />
    );

  test('a measured drop renders as a signed percentage with both period rates', () => {
    renderWith(reductionWith({}));

    expect(screen.getByText('\u221275%')).toBeInTheDocument();
    expect(screen.getByText('2.00 \u2192 0.50')).toBeInTheDocument();
  });

  test('an increase renders with a plus sign', () => {
    renderWith(
      reductionWith({
        current_snoozes_per_wake: 2,
        previous_snoozes_per_wake: 1,
        absolute_change_per_wake: 1,
        reduction_rate: -100,
        direction: 'declining',
      })
    );

    expect(screen.getByText('+100%')).toBeInTheDocument();
    expect(screen.getByText('1.00 \u2192 2.00')).toBeInTheDocument();
  });

  test('a zero-snooze baseline says so instead of showing a fake percentage', () => {
    renderWith(
      reductionWith({
        current_snoozes: 0,
        previous_snoozes: 0,
        current_snoozes_per_wake: 0,
        previous_snoozes_per_wake: 0,
        absolute_change_per_wake: 0,
        reduction_rate: null,
        direction: 'stable',
        status: 'no_baseline_snoozes',
      })
    );

    expect(screen.getByText('0.00 \u2192 0.00')).toBeInTheDocument();
    expect(
      screen.getByTitle(/no snoozes in the previous 7 days, so a percentage reduction cannot be calculated/i)
    ).toBeInTheDocument();
  });

  test('insufficient data shows a dash and explains the sample requirement', () => {
    renderWith(
      reductionWith({
        current_snoozes: 0,
        previous_snoozes: 0,
        current_wakes: 1,
        previous_wakes: 0,
        current_snoozes_per_wake: null,
        previous_snoozes_per_wake: null,
        absolute_change_per_wake: null,
        reduction_rate: null,
        direction: 'insufficient_data',
        status: 'insufficient_data',
      })
    );

    expect(
      screen.getByTitle(/Needs at least 3 wake events in the last 7 days/i)
    ).toBeInTheDocument();
  });
});

describe('Verification Accuracy block', () => {
  const verificationWith = (overrides) => ({
    decisions: 6,
    verified: 4,
    rejected: 2,
    correct_decisions: 6,
    accuracy_rate: 100,
    false_verifications: 0,
    missed_verifications: 0,
    first_pass_verifications: 3,
    first_pass_rate: 75,
    answers_recorded: 9,
    avg_answers_per_verification: 2.25,
    avg_wrong_answers_per_verification: 0.25,
    min_decisions_required: 3,
    status: 'ok',
    integrity: 'consistent',
    ...overrides,
  });

  const renderWith = (verification) => {
    const behavioral = behavioralWith({ totalSnoozes: 2, verifiedWakes: 4 });
    return render(
      <BehaviourInsights
        behavioral={{ ...behavioral, verification_accuracy: verification }}
        days={30}
      />
    );
  };

  test('a consistent gate reports 100% correct verdicts alongside the first-try rate', () => {
    renderWith(verificationWith({}));

    expect(screen.getByText('Verification Accuracy')).toBeInTheDocument();
    // '100%' also renders for on-time and adherence rates, so anchor on the row
    expect(
      screen.getByTitle(/6 of 6 finished wake-ups were released only after/i)
    ).toHaveTextContent('100%');
    expect(screen.getByText('75%')).toBeInTheDocument();
    expect(screen.getByText('2.25')).toBeInTheDocument();
  });

  test('a released-unconfirmed wake drags the accuracy below 100%', () => {
    renderWith(
      verificationWith({
        correct_decisions: 5,
        accuracy_rate: 83.33,
        false_verifications: 1,
        integrity: 'inconsistent',
      })
    );

    expect(screen.getByText('83.33%')).toBeInTheDocument();
    expect(
      screen.getByTitle(/marked verified without meeting the required number/i)
    ).toBeInTheDocument();
  });

  test('too few finished wake-ups explains the sample requirement instead of a number', () => {
    renderWith(
      verificationWith({
        decisions: 2,
        verified: 1,
        rejected: 1,
        correct_decisions: 2,
        accuracy_rate: null,
        first_pass_rate: null,
        avg_answers_per_verification: null,
        status: 'insufficient_data',
        integrity: 'unknown',
      })
    );

    expect(
      screen.getByTitle(/Needs at least 3 finished wake-ups in this period \(2 so far\)/i)
    ).toBeInTheDocument();
  });

  test('a missing block does not break the panel', () => {
    renderWith(undefined);

    expect(screen.getByText('Verification Accuracy')).toBeInTheDocument();
    expect(
      screen.getByTitle(/Needs at least 3 finished wake-ups in this period \(0 so far\)/i)
    ).toBeInTheDocument();
  });
});
