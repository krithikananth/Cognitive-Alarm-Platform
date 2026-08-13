/**
 * Profile — productivity goals and session revocation.
 *
 * Both endpoints existed with no caller: goals were folded into the generic
 * preferences write (so PUT /users/profile/goals was dead), and
 * POST /auth/logout-all had no control at all, meaning a user who left a
 * session open elsewhere had no way to end it.
 */
import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { ROLES } from '../utils/routeAccess';

let mockAuthState;

jest.mock('../store/authStore', () => ({
    __esModule: true,
    default: (selector) => (selector ? selector(mockAuthState) : mockAuthState),
}));

jest.mock('../services/api');

import { notificationAPI, userAPI } from '../services/api';
import Profile from './Profile';

const BUNDLE = {
    id: 1,
    full_name: 'Sam Rivers',
    username: 'sam',
    email: 'sam@example.com',
    timezone: 'UTC',
    profile: {
        timezone: 'UTC',
        preferred_wake_time: '07:00',
        sleep_duration_hours: 8,
        difficulty_preference: 'medium',
        productivity_goals: ['Ship the report'],
        habit_preferences: { preferred_challenge_types: ['math'] },
    },
};

beforeEach(() => {
    mockAuthState = {
        user: { id: 1, role: ROLES.USER, username: 'sam', email: 'sam@example.com' },
        fetchProfile: jest.fn(),
        logout: jest.fn(),
        logoutAll: jest.fn().mockResolvedValue({ success: true }),
    };
    userAPI.getProfile.mockResolvedValue({ data: BUNDLE });
    userAPI.updatePreferences.mockResolvedValue({ data: BUNDLE });
    userAPI.updateGoals.mockResolvedValue({ data: BUNDLE });
    notificationAPI.getPreferences.mockResolvedValue({ data: {} });
});

async function openPreferences() {
    render(<Profile />);
    fireEvent.click(await screen.findByRole('button', { name: /preferences/i }));
    return screen.findByText('Productivity Goals');
}

describe('productivity goals', () => {
    it('writes changed goals through the dedicated goals endpoint', async () => {
        await openPreferences();

        const textarea = screen.getByPlaceholderText(/What are your productivity goals/i);
        fireEvent.change(textarea, { target: { value: 'Ship the report, run daily' } });
        fireEvent.click(screen.getByRole('button', { name: 'Save All Preferences' }));

        await waitFor(() =>
            expect(userAPI.updateGoals).toHaveBeenCalledWith({
                productivity_goals: 'Ship the report, run daily',
            })
        );
        // Challenge preferences still go to their own endpoint, without goals.
        expect(userAPI.updatePreferences).toHaveBeenCalledWith({
            preferred_challenge_types: ['math'],
            difficulty_preference: 'medium',
        });
    });

    it('does not re-write goals that were not edited', async () => {
        await openPreferences();

        fireEvent.click(screen.getByRole('button', { name: 'Save All Preferences' }));

        await waitFor(() => expect(userAPI.updatePreferences).toHaveBeenCalled());
        expect(userAPI.updateGoals).not.toHaveBeenCalled();
    });
});

describe('signing out everywhere', () => {
    it('revokes every session through the store', async () => {
        render(<Profile />);

        fireEvent.click(await screen.findByText('Sign out on all devices'));

        await waitFor(() => expect(mockAuthState.logoutAll).toHaveBeenCalledTimes(1));
    });

    it('keeps the control usable after a failed revocation', async () => {
        mockAuthState.logoutAll.mockResolvedValue({ success: false });
        render(<Profile />);

        const button = await screen.findByText('Sign out on all devices');
        fireEvent.click(button);

        await waitFor(() => expect(button).not.toBeDisabled());
    });
});
