/**
 * Sleep Trends — the coach panel must separate what the client actually logged
 * from what was inferred, and must not present the profile's suggested bedtime
 * as an observed one.
 */
import React from 'react';
import { render, screen, within } from '@testing-library/react';
import SleepTrends from './SleepTrends';

function behavioralWith(sleepPatterns) {
    return {
        window_days: 30,
        sleep_schedule_adherence: {
            trend: 'stable',
            preferred_wake_time: '07:00',
            target_sleep_hours: 8,
            suggested_bedtime: '23:00',
            adherence_rate: 100,
            adherent_days: 4,
            observed_days: 4,
            avg_deviation_minutes: 3,
            tolerance_minutes: 15,
        },
        wake_up_consistency: {
            verified_wakes: 4,
            trend: 'stable',
            tolerance_minutes: 15,
            rolling_profile_score: 80,
            consistency_score: 72,
            mean_wake_time: '07:00',
            std_wake_minutes: 6,
            on_time_rate: 100,
        },
        habit_trends: { series: [] },
        window_trends: { series: [], totals: { on_time_rate: 100, on_time_wakes: 4, verified_wakes: 4 }, trend: 'stable' },
        sleep_patterns: sleepPatterns,
    };
}

const RECORDED = {
    nights_observed: 5,
    nights_with_duration: 5,
    nights_recorded: 5,
    nights_estimated: 0,
    has_recorded_sleep: true,
    duration_source: 'recorded',
    avg_sleep_duration_hours: 7.5,
    avg_bedtime: '23:15',
    avg_wake_time: '06:45',
    schedule_regularity_score: 92,
    social_jetlag_minutes: 45,
    trend: 'stable',
    nights: [],
};

const ESTIMATED = {
    ...RECORDED,
    nights_recorded: 0,
    nights_estimated: 5,
    has_recorded_sleep: false,
    duration_source: 'estimated',
};

const NO_DATA = {
    nights_observed: 0,
    nights_with_duration: 0,
    nights_recorded: 0,
    nights_estimated: 0,
    has_recorded_sleep: false,
    duration_source: 'none',
    avg_sleep_duration_hours: null,
    avg_bedtime: null,
    avg_wake_time: null,
    schedule_regularity_score: 0,
    social_jetlag_minutes: null,
    trend: 'insufficient_data',
    nights: [],
};

function measuredBlock() {
    return screen.getByText('Measured Sleep').closest('.rounded-xl');
}

describe('Coach Measured Sleep block', () => {
    test('shows measured duration, observed bedtime and regularity', () => {
        render(<SleepTrends behavioral={behavioralWith(RECORDED)} days={30} />);

        const block = measuredBlock();
        expect(within(block).getByText('7.5 h')).toBeInTheDocument();
        expect(within(block).getByText('92/100')).toBeInTheDocument();
        expect(within(block).getByText('45 min')).toBeInTheDocument();
        expect(within(block).getByText('5/5')).toBeInTheDocument();
    });

    test('recorded history is described as client-logged', () => {
        render(<SleepTrends behavioral={behavioralWith(RECORDED)} days={30} />);

        expect(
            screen.getByText(/Sleep sessions the client logged themselves/i)
        ).toBeInTheDocument();
        expect(screen.getByTitle('5 recorded · 0 estimated')).toBeInTheDocument();
    });

    test('estimated history is explicitly flagged as an upper bound', () => {
        render(<SleepTrends behavioral={behavioralWith(ESTIMATED)} days={30} />);

        expect(
            screen.getByText(/an upper bound, not logged sleep/i)
        ).toBeInTheDocument();
        expect(screen.getByTitle('0 recorded · 5 estimated')).toBeInTheDocument();
    });

  test('mixed history is not described as fully client-logged', () => {
    render(
      <SleepTrends
        behavioral={behavioralWith({
          ...RECORDED,
          nights_recorded: 3,
          nights_estimated: 2,
          duration_source: 'mixed',
        })}
        days={30}
      />
    );

    expect(
      screen.getByText(/Part logged by the client, part estimated/i)
    ).toBeInTheDocument();
    expect(
      screen.queryByText(/Sleep sessions the client logged themselves/i)
    ).not.toBeInTheDocument();
    expect(screen.getByTitle('3 recorded · 2 estimated')).toBeInTheDocument();
  });

  test('no measured nights renders dashes rather than zeros', () => {
    render(<SleepTrends behavioral={behavioralWith(NO_DATA)} days={30} />);

    const block = measuredBlock();
    expect(within(block).getAllByText('—').length).toBeGreaterThanOrEqual(3);
    expect(within(block).getByText('0/0')).toBeInTheDocument();
    expect(
      screen.getByText(/No sleep sessions could be measured/i)
    ).toBeInTheDocument();
  });

    test('a payload without sleep_patterns does not break the panel', () => {
        render(<SleepTrends behavioral={behavioralWith(undefined)} days={30} />);

        expect(screen.getByText('Measured Sleep')).toBeInTheDocument();
        expect(screen.getByText('Sleep Adherence')).toBeInTheDocument();
    });

    test('the suggested bedtime stays distinct from the observed one', () => {
        render(<SleepTrends behavioral={behavioralWith(RECORDED)} days={30} />);

        // Adherence block keeps the profile-derived suggestion...
        const adherence = screen.getByText('Sleep Adherence').closest('.rounded-xl');
        expect(within(adherence).getByText(/^23:00 \(/)).toBeInTheDocument();
        // ...while the measured block shows what was actually observed
        expect(within(measuredBlock()).getByText(/^23:15 \(/)).toBeInTheDocument();
    });
});
