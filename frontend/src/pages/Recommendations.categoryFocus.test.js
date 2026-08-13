/**
 * Category-scoped recommendation endpoints.
 *
 * /recommendations/sleep, /wake and /productivity were implemented and wrapped
 * in `api.js` but never called: the page filtered the combined feed instead, so
 * the category-scoped insight text those endpoints compute never reached a
 * user. Selecting a chip now loads it.
 */
import React from 'react';
import { MemoryRouter } from 'react-router-dom';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';

jest.mock('../services/api');

import { recommendationAPI } from '../services/api';
import Recommendations from './Recommendations';

function rec(id, category, title) {
    return {
        id,
        category,
        priority: 'medium',
        title,
        detail: `${title} detail`,
        confidence: 0.8,
        metrics: {},
    };
}

const SLEEP = rec('sleep-bedtime-anchor', 'sleep', 'Anchor lights-out');
const WAKE = rec('wake-reduce-snooze', 'wake', 'Cut morning snoozes');
const HABIT = rec('habit-raise-score', 'habit', 'Raise habit score');
const PRODUCTIVITY = rec('productivity-set-goals', 'productivity', 'Save your goals');
const CHALLENGE = rec('challenge-practice', 'challenge', 'Practice math');

const FEED = {
    generated_at: '2026-08-13T06:00:00Z',
    summary: { habit_score: 62 },
    insights: ['Snooze rate is 42% over your last 21 wake-ups.'],
    recommendations: [SLEEP, WAKE, HABIT, PRODUCTIVITY, CHALLENGE],
    by_category: {
        sleep: [SLEEP],
        wake: [WAKE],
        habit: [HABIT],
        productivity: [PRODUCTIVITY],
        challenge: [CHALLENGE],
    },
    daily_plan: {},
};

beforeEach(() => {
    recommendationAPI.getAll.mockResolvedValue({ data: FEED });
    recommendationAPI.getDaily.mockResolvedValue({
        data: { ...FEED, recommendations: [WAKE] },
    });
    recommendationAPI.getRelevance.mockResolvedValue({
        data: { status: 'no_data', rated: 0, min_responses: 3, by_category: {} },
    });
    recommendationAPI.getSleep.mockResolvedValue({
        data: {
            category: 'sleep',
            insights: ['Lights-out drifted 42 minutes later this week.'],
            recommendations: [SLEEP],
        },
    });
    recommendationAPI.getWake.mockResolvedValue({
        data: { category: 'wake', insights: [], recommendations: [WAKE, HABIT] },
    });
    recommendationAPI.getProductivity.mockResolvedValue({
        data: {
            category: 'productivity',
            insights: ['Two saved goals are driving these suggestions.'],
            recommendations: [PRODUCTIVITY],
        },
    });
});

function renderPage() {
    return render(
        <MemoryRouter>
            <Recommendations />
        </MemoryRouter>
    );
}

async function selectChip(name) {
    const chip = await screen.findByRole('button', { name });
    fireEvent.click(chip);
    return chip;
}

describe('category focus', () => {
    it('loads nothing extra on first paint', async () => {
        renderPage();
        await screen.findByText('All Recommendations');

        expect(recommendationAPI.getSleep).not.toHaveBeenCalled();
        expect(recommendationAPI.getWake).not.toHaveBeenCalled();
        expect(recommendationAPI.getProductivity).not.toHaveBeenCalled();
    });

    it('loads the sleep endpoint and shows its scoped insights', async () => {
        renderPage();
        await selectChip('Sleep · 1');

        await waitFor(() => expect(recommendationAPI.getSleep).toHaveBeenCalledTimes(1));
        expect(
            await screen.findByText('Lights-out drifted 42 minutes later this week.')
        ).toBeInTheDocument();
        expect(screen.getByText('Sleep focus')).toBeInTheDocument();
    });

    it('loads the productivity endpoint for its own chip', async () => {
        renderPage();
        await selectChip('Productivity · 1');

        expect(
            await screen.findByText('Two saved goals are driving these suggestions.')
        ).toBeInTheDocument();
        expect(recommendationAPI.getSleep).not.toHaveBeenCalled();
    });

    it('caches a category instead of refetching on every chip click', async () => {
        renderPage();
        await selectChip('Wake-up · 1');
        await waitFor(() => expect(recommendationAPI.getWake).toHaveBeenCalledTimes(1));

        fireEvent.click(screen.getByRole('button', { name: 'All · 5' }));
        fireEvent.click(screen.getByRole('button', { name: 'Wake-up · 1' }));

        await waitFor(() =>
            expect(screen.getByText('Wake-up focus')).toBeInTheDocument()
        );
        expect(recommendationAPI.getWake).toHaveBeenCalledTimes(1);
    });

    it('keeps the cards visible when the scoped request fails', async () => {
        recommendationAPI.getSleep.mockRejectedValue(new Error('down'));
        renderPage();
        await selectChip('Sleep · 1');

        await waitFor(() => expect(recommendationAPI.getSleep).toHaveBeenCalled());
        expect(await screen.findByText('Anchor lights-out')).toBeInTheDocument();
        expect(
            screen.getByText('No sleep-specific insights yet.')
        ).toBeInTheDocument();
    });

    it('does not query a category without a dedicated endpoint', async () => {
        renderPage();
        await selectChip('Habit · 1');

        expect(screen.queryByText('Habit focus')).not.toBeInTheDocument();
        expect(recommendationAPI.getSleep).not.toHaveBeenCalled();
        expect(recommendationAPI.getWake).not.toHaveBeenCalled();
        expect(recommendationAPI.getProductivity).not.toHaveBeenCalled();
    });
});
