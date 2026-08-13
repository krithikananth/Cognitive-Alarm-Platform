/**
 * Analytics page — the engagement improvement block.
 *
 * The engagement score on its own is a snapshot. This pins that the page
 * reports the period-over-period delta the backend measured, and that a
 * healthy-looking current score does not hide a decline.
 */
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { render, screen } from '@testing-library/react';

jest.mock('../services/api');
jest.mock('react-hot-toast', () => ({
    __esModule: true,
    default: { success: jest.fn(), error: jest.fn() },
    Toaster: () => null,
}));

import { alarmAPI } from '../services/api';
import Analytics from './Analytics';

function improvementWith(overrides = {}) {
    return {
        period_days: 14,
        current_period_start: '2026-07-29T12:00:00+00:00',
        current_period_end: '2026-08-12T12:00:00+00:00',
        previous_period_start: '2026-07-15T12:00:00+00:00',
        previous_period_end: '2026-07-29T12:00:00+00:00',
        current_attempts: 18,
        previous_attempts: 9,
        current_active_days: 6,
        previous_active_days: 3,
        min_sample: 6,
        current_score: 88,
        previous_score: 62,
        current_state: 'thriving',
        previous_state: 'steady',
        change: 26,
        improvement_rate: 41.9,
        direction: 'improving',
        status: 'ok',
        ...overrides,
    };
}

function analysisWith(improvement) {
    return {
        summary: {
            total_attempts: 40,
            correct_answers: 32,
            accuracy_percentage: 80,
            avg_response_time: 9.5,
            total_points_earned: 160,
            completion_rate: 90,
            trend: 'stable',
            trend_label: 'Holding steady',
        },
        strengths: [],
        weaknesses: [],
        by_type: {},
        by_difficulty: {},
        recommendations: [],
        insights: [],
        suggested_preferred_types: [],
        personalization: {
            learning_patterns: {
                sample_size: 40,
                has_enough_data: true,
                accuracy: 80,
                learning_state: 'steady',
                learning_state_label: 'Holding steady at 80%.',
                accuracy_trend_pp_per_10: 1.2,
                speed_trend_seconds_per_10: -0.4,
                consistency: 82,
                by_type: {},
                by_difficulty: {},
                optimal_difficulty: 'medium',
                adaptation_effectiveness: {
                    window: 5,
                    min_side_sample: 3,
                    min_events: 3,
                    target_band: { low: 60.0, high: 85.0 },
                    adaptations_detected: 0,
                    adaptations_judged: 0,
                    effective: 0,
                    ineffective: 0,
                    neutral: 0,
                    effectiveness_rate: 0,
                    avg_accuracy_before: null,
                    avg_accuracy_after: null,
                    avg_band_distance_before: null,
                    avg_band_distance_after: null,
                    avg_band_distance_change: null,
                    by_direction: {},
                    recent_events: [],
                    verdict: 'insufficient_data',
                },
                time_of_day: { buckets: {}, peak_hours: [], low_hours: [] },
                mastered_types: [],
                focus_types: [],
            },
            engagement: {
                state: 'thriving',
                engagement_score: 88,
                improvement,
                directives: {
                    difficulty_bias: 0,
                    novelty_boost: 0,
                    underused_types: [],
                    reason: 'Holding the current level.',
                },
            },
        },
    };
}

function mountWith(improvement) {
    alarmAPI.getChallengeStats.mockResolvedValue({ data: { by_type: {} } });
    alarmAPI.getChallengeAnalysis.mockResolvedValue({
        data: analysisWith(improvement),
    });
    alarmAPI.getChallengeHistory.mockResolvedValue({ data: { history: [], total: 0 } });
    return render(
        <MemoryRouter>
            <Analytics />
        </MemoryRouter>
    );
}

describe('Engagement improvement', () => {
    test('a rise reports the signed delta and both period scores', async () => {
        mountWith(improvementWith());

        expect(await screen.findByText('vs 14d ago')).toBeInTheDocument();
        expect(screen.getByText('Improving · +26')).toBeInTheDocument();
        expect(screen.getByText(/62 → 88 \(\+41\.9%\) · 9 → 18 attempts/)).toBeInTheDocument();
    });

    test('a decline is shown even while the current score still looks healthy', async () => {
        mountWith(
            improvementWith({
                current_score: 55,
                previous_score: 91,
                current_state: 'steady',
                previous_state: 'thriving',
                current_attempts: 2,
                previous_attempts: 21,
                change: -36,
                improvement_rate: -39.6,
                direction: 'declining',
            })
        );

        expect(await screen.findByText('Declining · -36')).toBeInTheDocument();
        expect(screen.getByText(/91 → 55 \(-39\.6%\) · 21 → 2 attempts/)).toBeInTheDocument();
    });

    test('an unchanged rhythm reads as holding steady', async () => {
        mountWith(
            improvementWith({
                current_score: 80,
                previous_score: 78,
                change: 2,
                improvement_rate: 2.6,
                direction: 'stable',
            })
        );

        expect(await screen.findByText('Holding steady · +2')).toBeInTheDocument();
    });

    test('too little history shows no delta rather than a fabricated zero', async () => {
        mountWith(
            improvementWith({
                current_score: null,
                previous_score: null,
                current_state: 'insufficient_data',
                previous_state: 'insufficient_data',
                previous_attempts: 0,
                change: null,
                improvement_rate: null,
                direction: 'insufficient_data',
                status: 'insufficient_data',
            })
        );

        expect(await screen.findByText('vs 14d ago')).toBeInTheDocument();
        expect(screen.getAllByText('Warming up').length).toBeGreaterThan(0);
        expect(screen.queryByText(/\d+ → \d+ attempts/)).not.toBeInTheDocument();
    });
});
