/**
 * Per-alarm challenge history.
 *
 * GET /alarms/{id}/challenge/history was implemented on the backend and
 * wrapped in `api.js`, but no screen ever opened it — an alarm's own attempt
 * record was unreachable from the UI. These tests pin that the alarm card can
 * open it, that the rows come from that endpoint, and that a failure is
 * reported instead of rendering as "no attempts".
 */
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

jest.mock('../services/api');

const mockAlarmState = {
    alarms: [
        {
            id: 12,
            label: 'Weekday wake-up',
            alarm_time: '06:30',
            alarm_type: 'daily',
            challenge_type: 'math',
            challenge_difficulty: 'medium',
            is_active: true,
            days_of_week: [0, 1, 2, 3, 4],
            snooze_limit: 2,
        },
    ],
    fetchAlarms: jest.fn(),
    createAlarm: jest.fn(),
    updateAlarm: jest.fn(),
    deleteAlarm: jest.fn(),
    toggleAlarm: jest.fn(),
    isLoading: false,
};

jest.mock('../store/alarmStore', () => ({
    __esModule: true,
    default: () => mockAlarmState,
}));

jest.mock('../store/activeAlarmStore', () => {
    const state = { triggerAlarm: () => { } };
    const useActiveAlarmStore = (selector) => (selector ? selector(state) : state);
    useActiveAlarmStore.getState = () => state;
    return { __esModule: true, default: useActiveAlarmStore };
});

import { alarmAPI, readErrorDetail, userAPI } from '../services/api';
import AlarmManager from './AlarmManager';

const ATTEMPTS = {
    alarm_id: 12,
    total: 2,
    page: 1,
    per_page: 10,
    history: [
        {
            id: 501,
            challenge_type: 'math',
            difficulty: 'medium',
            challenge_prompt: '17 + 26 = ?',
            is_correct: true,
            time_taken_seconds: 9,
            failed_attempts: 0,
            points_earned: 15,
            created_at: '2026-08-12T06:31:00Z',
        },
        {
            id: 500,
            challenge_type: 'word_game',
            difficulty: 'hard',
            challenge_prompt: 'Unscramble RATS',
            is_correct: false,
            time_taken_seconds: 31,
            failed_attempts: 2,
            points_earned: 0,
            created_at: '2026-08-11T06:33:00Z',
        },
    ],
};

beforeEach(() => {
    userAPI.getProfile.mockResolvedValue({
        data: { profile: { difficulty_preference: 'medium' } },
    });
    alarmAPI.getAlarmChallengeHistory.mockResolvedValue({ data: ATTEMPTS });
    readErrorDetail.mockImplementation(async (err, fallback) =>
        err?.response?.data?.detail || fallback
    );
});

function openHistory() {
    render(<AlarmManager />);
    fireEvent.click(
        screen.getByRole('button', { name: 'Challenge history for Weekday wake-up' })
    );
}

describe('alarm challenge history', () => {
    it('requests the history for that specific alarm', async () => {
        openHistory();

        await waitFor(() =>
            expect(alarmAPI.getAlarmChallengeHistory).toHaveBeenCalledWith(12, {
                page: 1,
                per_page: 10,
            })
        );
    });

    it('renders the attempts returned by the endpoint', async () => {
        openHistory();

        expect(await screen.findByText('Correct')).toBeInTheDocument();
        expect(screen.getByText('Wrong')).toBeInTheDocument();
        expect(screen.getByText('word game')).toBeInTheDocument();
        expect(screen.getByText('Weekday wake-up · 2 attempts')).toBeInTheDocument();
    });

    it('shows an empty state rather than an error when there are no attempts', async () => {
        alarmAPI.getAlarmChallengeHistory.mockResolvedValue({
            data: { alarm_id: 12, total: 0, page: 1, per_page: 10, history: [] },
        });
        openHistory();

        expect(
            await screen.findByText('No challenge attempts recorded for this alarm yet.')
        ).toBeInTheDocument();
    });

    it('surfaces a failed request instead of an empty list', async () => {
        alarmAPI.getAlarmChallengeHistory.mockRejectedValue({
            response: { data: { detail: 'Alarm not found' } },
        });
        openHistory();

        const alert = await screen.findByRole('alert');
        expect(alert).toHaveTextContent('Alarm not found');
    });
});
