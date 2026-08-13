/**
 * SleepPatternsPanel render tests.
 *
 * The panel's contract is provenance honesty: a night inferred from app
 * activity must never read as recorded sleep, and a night with no sleep start
 * on record must show no duration at all.
 */
import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import SleepPatternsPanel from './SleepPatternsPanel';

function night(overrides = {}) {
    return {
        date: '2026-08-10',
        weekday: 'Mon',
        is_weekend: false,
        source: 'estimated',
        sleep_end_source: 'verified_wake',
        wake_time: '07:00',
        wake_minutes: 420,
        bedtime: '23:00',
        bedtime_minutes: 1380,
        sleep_duration_hours: 8,
        mid_sleep_minutes: 180,
        wake_latency_seconds: 300,
        ...overrides,
    };
}

function sleepPayload(overrides = {}) {
    return {
        nights_observed: 1,
        nights_with_duration: 1,
        nights_recorded: 0,
        nights_estimated: 1,
        has_recorded_sleep: false,
        duration_source: 'estimated',
        avg_recorded_duration_hours: null,
        avg_estimated_duration_hours: 8,
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
        nights: [night()],
        ...overrides,
    };
}

describe('SleepPatternsPanel empty state', () => {
    test('no sleep history shows guidance instead of zeroed metrics', () => {
        render(<SleepPatternsPanel sleep={sleepPayload({ nights_observed: 0, nights: [] })} />);

        expect(screen.getByText(/No sleep history yet/i)).toBeInTheDocument();
        expect(screen.queryByText('Avg duration')).not.toBeInTheDocument();
    });

    test('a missing payload does not crash the panel', () => {
        render(<SleepPatternsPanel sleep={null} />);

        expect(screen.getByText('Sleep Patterns')).toBeInTheDocument();
        expect(screen.getByText(/No sleep history yet/i)).toBeInTheDocument();
    });
});

describe('SleepPatternsPanel provenance', () => {
    test('estimate-only history is labelled and warned about', () => {
        render(<SleepPatternsPanel sleep={sleepPayload()} />);

        expect(
            screen.getByText(/estimated\s+from your last activity before waking/i)
        ).toBeInTheDocument();
        expect(
            screen.getByText(/Estimated nights are an upper bound on real sleep/i)
        ).toBeInTheDocument();
    });

    test('recorded history drops the estimate warning', () => {
        render(
            <SleepPatternsPanel
                sleep={sleepPayload({
                    has_recorded_sleep: true,
                    nights_recorded: 1,
                    nights_estimated: 0,
                    duration_source: 'recorded',
                    avg_recorded_duration_hours: 8,
                    avg_estimated_duration_hours: null,
                    nights: [night({ source: 'recorded', sleep_end_source: 'sleep_record' })],
                })}
            />
        );

        expect(
            screen.queryByText(/Estimated nights are an upper bound on real sleep/i)
        ).not.toBeInTheDocument();
    });

    test('each night row carries its own source badge', () => {
        render(
            <SleepPatternsPanel
                sleep={sleepPayload({
                    nights_observed: 2,
                    nights_with_duration: 2,
                    nights_recorded: 1,
                    nights_estimated: 1,
                    has_recorded_sleep: true,
                    duration_source: 'mixed',
                    nights: [
                        night({ date: '2026-08-10', source: 'recorded', sleep_end_source: 'sleep_record' }),
                        night({ date: '2026-08-09', source: 'estimated' }),
                    ],
                })}
            />
        );

        fireEvent.click(screen.getByText('Show nightly breakdown'));

        const recordedRow = screen.getByText('2026-08-10').closest('tr');
        const estimatedRow = screen.getByText('2026-08-09').closest('tr');
        expect(within(recordedRow).getByText('Recorded')).toBeInTheDocument();
        expect(within(estimatedRow).getByText('Estimated')).toBeInTheDocument();
    });

    test('a night with no sleep start shows no duration', () => {
        render(
            <SleepPatternsPanel
                sleep={sleepPayload({
                    nights_observed: 1,
                    nights_with_duration: 0,
                    avg_sleep_duration_hours: null,
                    avg_bedtime: null,
                    bedtime_coverage_rate: 0,
                    nights: [
                        night({ bedtime: null, bedtime_minutes: null, sleep_duration_hours: null }),
                    ],
                })}
            />
        );

        expect(
            screen.getByText(/have\s+no sleep start on record/i)
        ).toBeInTheDocument();

        fireEvent.click(screen.getByText('Show nightly breakdown'));
        const row = screen.getByText('2026-08-10').closest('tr');
        // bedtime and duration both fall back to an em dash, never a guess
        expect(within(row).getAllByText('—').length).toBeGreaterThanOrEqual(2);
    });
});

describe('SleepPatternsPanel log-sleep control', () => {
    test('clicking Log sleep now invokes the handler', () => {
        const onLogSleep = jest.fn();
        render(<SleepPatternsPanel sleep={sleepPayload()} onLogSleep={onLogSleep} />);

        fireEvent.click(screen.getByRole('button', { name: /log sleep now/i }));

        expect(onLogSleep).toHaveBeenCalledTimes(1);
    });

    test('the control is disabled and reworded while saving', () => {
        const onLogSleep = jest.fn();
        render(
            <SleepPatternsPanel sleep={sleepPayload()} onLogSleep={onLogSleep} logging />
        );

        const button = screen.getByRole('button', { name: /saving/i });
        expect(button).toBeDisabled();

        fireEvent.click(button);
        expect(onLogSleep).not.toHaveBeenCalled();
    });

    test('the control is available even with no history', () => {
        render(
            <SleepPatternsPanel
                sleep={sleepPayload({ nights_observed: 0, nights: [] })}
                onLogSleep={jest.fn()}
            />
        );

        expect(screen.getByRole('button', { name: /log sleep now/i })).toBeEnabled();
    });
});

describe('SleepPatternsPanel metrics', () => {
    test('renders measured values and the profile target', () => {
        render(<SleepPatternsPanel sleep={sleepPayload()} />);

        expect(screen.getByText('8h 00m')).toBeInTheDocument();
        expect(screen.getByText('Target 8h 00m')).toBeInTheDocument();
        expect(screen.getByText('23:00')).toBeInTheDocument();
        expect(screen.getByText('07:00')).toBeInTheDocument();
        expect(screen.getByText('100/100')).toBeInTheDocument();
    });

    test('social jetlag renders only when both segments exist', () => {
        render(<SleepPatternsPanel sleep={sleepPayload({ social_jetlag_minutes: 120 })} />);

        expect(screen.getByText('120 min')).toBeInTheDocument();
    });
});
