/**
 * Role-based routing tests for the authenticated dashboard entry points.
 *
 * Pages, Layout and the alarm stores are stubbed so the assertions cover the
 * routing decision in `App.jsx` only, not each page's own data fetching.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import { ROLES } from './utils/routeAccess';

let mockAuthState = { user: null, isAuthenticated: false };

jest.mock('./store/authStore', () => ({
    __esModule: true,
    default: (selector) => (selector ? selector(mockAuthState) : mockAuthState),
}));

jest.mock('./store/alarmStore', () => ({
    __esModule: true,
    default: () => ({ alarms: [], fetchAlarms: jest.fn() }),
}));

jest.mock('./store/activeAlarmStore', () => {
    const state = { triggerAlarm: jest.fn(), isRinging: false, ringingAlarmId: null };
    const useActiveAlarmStore = () => state;
    useActiveAlarmStore.getState = () => state;
    return { __esModule: true, default: useActiveAlarmStore };
});

jest.mock('./services/analyticsTracker', () => ({
    __esModule: true,
    trackAlarmMissed: jest.fn(),
}));

jest.mock('./components/ActiveAlarmModal', () => ({
    __esModule: true,
    default: () => null,
}));

// Layout only needs to expose its outlet so the matched route renders.
jest.mock('./components/Layout', () => {
    const ReactActual = jest.requireActual('react');
    const { Outlet } = jest.requireActual('react-router-dom');
    return { __esModule: true, default: () => ReactActual.createElement(Outlet) };
});

jest.mock('./pages/UserDashboard', () => ({
    __esModule: true,
    default: () => 'User Dashboard Page',
}));
jest.mock('./pages/WellnessCoachDashboard', () => ({
    __esModule: true,
    default: () => 'Wellness Coach Dashboard Page',
}));
jest.mock('./pages/AdminDashboard', () => ({ __esModule: true, default: () => 'Admin Page' }));
jest.mock('./pages/AccessDenied', () => ({ __esModule: true, default: () => 'Access Denied Page' }));
jest.mock('./pages/AlarmManager', () => ({ __esModule: true, default: () => 'Alarms Page' }));
jest.mock('./pages/Analytics', () => ({ __esModule: true, default: () => 'Analytics Page' }));
jest.mock('./pages/Reports', () => ({ __esModule: true, default: () => 'Reports Page' }));
jest.mock('./pages/Profile', () => ({ __esModule: true, default: () => 'Profile Page' }));
jest.mock('./pages/PracticeChallenge', () => ({ __esModule: true, default: () => 'Practice Page' }));
jest.mock('./pages/Login', () => ({ __esModule: true, default: () => 'Login Page' }));
jest.mock('./pages/Register', () => ({ __esModule: true, default: () => 'Register Page' }));
jest.mock('./pages/ForgotPassword', () => ({ __esModule: true, default: () => 'Forgot Page' }));
jest.mock('./pages/ResetPassword', () => ({ __esModule: true, default: () => 'Reset Page' }));
jest.mock('./pages/VerifyEmail', () => ({ __esModule: true, default: () => 'Verify Page' }));
jest.mock('./pages/OAuthCallback', () => ({ __esModule: true, default: () => 'OAuth Page' }));

// eslint-disable-next-line import/first
import App from './App';

function renderAt(path, role) {
    mockAuthState = { user: { id: 1, role }, isAuthenticated: true };
    window.history.pushState({}, '', path);
    return render(<App />);
}

afterEach(() => {
    mockAuthState = { user: null, isAuthenticated: false };
});

describe('/dashboard role routing', () => {
    test('a normal user gets the User Dashboard', async () => {
        renderAt('/dashboard', ROLES.USER);

        expect(await screen.findByText('User Dashboard Page')).toBeInTheDocument();
        expect(window.location.pathname).toBe('/dashboard');
    });

    test('a wellness coach is redirected to the Wellness Coach Dashboard', async () => {
        renderAt('/dashboard', ROLES.WELLNESS_COACH);

        expect(await screen.findByText('Wellness Coach Dashboard Page')).toBeInTheDocument();
        expect(window.location.pathname).toBe('/wellness');
    });

    test('a wellness coach never renders the User Dashboard', async () => {
        renderAt('/dashboard', ROLES.WELLNESS_COACH);

        await screen.findByText('Wellness Coach Dashboard Page');
        expect(screen.queryByText('User Dashboard Page')).not.toBeInTheDocument();
    });

    test('a normal user is denied the coach dashboard', async () => {
        renderAt('/wellness', ROLES.USER);

        expect(await screen.findByText('Access Denied Page')).toBeInTheDocument();
        expect(screen.queryByText('Wellness Coach Dashboard Page')).not.toBeInTheDocument();
    });
});

describe('unmatched routes', () => {
    test('an unknown path renders the 404 page instead of redirecting', async () => {
        renderAt('/does-not-exist', ROLES.USER);

        expect(await screen.findByText('Page Not Found')).toBeInTheDocument();
        expect(window.location.pathname).toBe('/does-not-exist');
    });

    test('the 404 page links back to the role home', async () => {
        renderAt('/does-not-exist', ROLES.ADMIN);

        const link = await screen.findByRole('link', { name: /back to my dashboard/i });
        expect(link).toHaveAttribute('href', '/admin');
    });

    test('a guest hitting an unknown path is sent to login', async () => {
        mockAuthState = { user: null, isAuthenticated: false };
        window.history.pushState({}, '', '/does-not-exist');
        render(<App />);

        expect(await screen.findByText('Login Page')).toBeInTheDocument();
    });
});
