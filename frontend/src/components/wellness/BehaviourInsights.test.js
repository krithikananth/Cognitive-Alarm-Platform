/**
 * Behaviour Insights — the snooze panel must distinguish "this client never
 * snoozed" (a real result) from "there is not enough data to judge".
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import BehaviourInsights from './BehaviourInsights';

const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

function behavioralWith({ totalSnoozes, verifiedWakes }) {
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
