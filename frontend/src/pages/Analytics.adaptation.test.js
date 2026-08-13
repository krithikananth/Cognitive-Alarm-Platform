/**
 * Analytics page — the difficulty adaptation effectiveness block.
 *
 * The point of this metric is that it is NOT "accuracy went up": a difficulty
 * increase is supposed to pull accuracy down toward the target band. These
 * tests pin that the page reports the band-fit verdict the backend computed
 * rather than re-deriving a verdict from the accuracy numbers.
 */
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { render, screen, waitFor } from '@testing-library/react';

jest.mock('../services/api');
jest.mock('react-hot-toast', () => ({
    __esModule: true,
    default: { success: jest.fn(), error: jest.fn() },
    Toaster: () => null,
}));

import { alarmAPI } from '../services/api';
import Analytics from './Analytics';

function adaptationWith(overrides = {}) {
    return {
        window: 5,
        min_side_sample: 3,
        min_events: 3,
        target_band: { low: 60.0, high: 85.0 },
        adaptations_detected: 4,
        adaptations_judged: 4,
        effective: 3,
        ineffective: 1,
        neutral: 0,
        effectiveness_rate: 75.0,
        avg_accuracy_before: 96.0,
        avg_accuracy_after: 78.0,
        avg_band_distance_before: 18.0,
        avg_band_distance_after: 4.0,
        avg_band_distance_change: -14.0,
        by_direction: {
            harder: { judged: 3, effective: 3, ineffective: 0, neutral: 0, effectiveness_rate: 100.0 },
            easier: { judged: 1, effective: 0, ineffective: 1, neutral: 0, effectiveness_rate: 0.0 },
        },
        recent_events: [],
        verdict: 'effective',
        ...overrides,
    };
}

function analysisWith(adaptation) {
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
                adaptation_effectiveness: adaptation,
                time_of_day: { buckets: {}, peak_hours: [], low_hours: [] },
                mastered_types: [],
                focus_types: [],
            },
            engagement: {
                state: 'engaged',
                engagement_score: 72,
                // Given a definite direction so its chip never collides with
                // the adaptation verdict these tests assert on.
                improvement: {
                    period_days: 14,
                    current_score: 72,
                    previous_score: 70,
                    change: 2,
                    improvement_rate: 2.9,
                    current_attempts: 10,
                    previous_attempts: 9,
                    direction: 'stable',
                    status: 'ok',
                },
                directives: { difficulty_bias: 0, novelty_boost: 0, underused_types: [], reason: '' },
            },
        },
    };
}

function mountWith(adaptation) {
    alarmAPI.getChallengeStats.mockResolvedValue({ data: { by_type: {} } });
    alarmAPI.getChallengeAnalysis.mockResolvedValue({ data: analysisWith(adaptation) });
    alarmAPI.getChallengeHistory.mockResolvedValue({ data: { history: [], total: 0 } });
    return render(
        <MemoryRouter>
            <Analytics />
        </MemoryRouter>
    );
}

describe('Difficulty adaptation effectiveness', () => {
    test('reports the measured rate and the band-fit movement', async () => {
        mountWith(adaptationWith());

        expect(
            await screen.findByText('Difficulty adaptation effectiveness')
        ).toBeInTheDocument();
        expect(screen.getByText('Working')).toBeInTheDocument();
        expect(
            screen.getByText('75% of 4 adaptations moved you toward the target band')
        ).toBeInTheDocument();
        expect(
            screen.getByText(/Accuracy 96% → 78% · distance from band 18 → 4 pts/)
        ).toBeInTheDocument();
    });

    test('falling accuracy still reads as working when it closed the band gap', async () => {
        mountWith(adaptationWith());

        await screen.findByText('Difficulty adaptation effectiveness');
        // Accuracy dropped 96 -> 78 and the verdict is still positive, because the
        // user moved from 18 points outside the band to 4.
        expect(screen.getByText('Working')).toBeInTheDocument();
        expect(screen.queryByText('Not helping')).not.toBeInTheDocument();
    });

    test('adaptations that widened the gap are reported as not helping', async () => {
        mountWith(
            adaptationWith({
                effective: 1,
                ineffective: 3,
                effectiveness_rate: 25.0,
                avg_accuracy_before: 78.0,
                avg_accuracy_after: 20.0,
                avg_band_distance_before: 4.0,
                avg_band_distance_after: 40.0,
                avg_band_distance_change: 36.0,
                verdict: 'ineffective',
            })
        );

        expect(await screen.findByText('Not helping')).toBeInTheDocument();
        expect(
            screen.getByText('25% of 4 adaptations moved you toward the target band')
        ).toBeInTheDocument();
    });

    test('too few judged adaptations explains the requirement instead of scoring', async () => {
        mountWith(
            adaptationWith({
                adaptations_detected: 1,
                adaptations_judged: 0,
                effective: 0,
                ineffective: 0,
                effectiveness_rate: 0.0,
                avg_accuracy_before: null,
                avg_accuracy_after: null,
                avg_band_distance_before: null,
                avg_band_distance_after: null,
                avg_band_distance_change: null,
                verdict: 'insufficient_data',
            })
        );

        expect(await screen.findByText('Warming up')).toBeInTheDocument();
        expect(
            screen.getByText(
                /1 difficulty change so far — needs 3 with at least 3 attempts on each side/
            )
        ).toBeInTheDocument();
        expect(screen.queryByText(/moved you toward the target band/)).not.toBeInTheDocument();
    });
});
