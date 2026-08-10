/**
 * Role-based security tests for the client-side guard layer.
 *
 * Covers the browser-driven attack vectors that `App.roleRouting.test.js`
 * does not: typing a privileged URL directly, reloading a protected page,
 * pressing Back after logout, arriving with no/expired session, and trying to
 * reach another role's page by editing the address bar.
 *
 * The backend role dependencies remain the real boundary; these assertions
 * confirm the UI never renders a page it should not.
 */
import React from 'react';
import { render, screen, act } from '@testing-library/react';
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

jest.mock('./components/ActiveAlarmModal', () => ({ __esModule: true, default: () => null }));

jest.mock('./components/Layout', () => {
    const ReactActual = jest.requireActual('react');
    const { Outlet } = jest.requireActual('react-router-dom');
    return { __esModule: true, default: () => ReactActual.createElement(Outlet) };
});

jest.mock('./pages/UserDashboard', () => ({ __esModule: true, default: () => 'User Dashboard Page' }));
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

/** Render the app at `path` as `role` (null role => unauthenticated guest). */
function renderAt(path, role) {
    mockAuthState = role
        ? { user: { id: 1, role }, isAuthenticated: true }
        : { user: null, isAuthenticated: false };
    window.history.pushState({}, '', path);
    return render(<App />);
}

afterEach(() => {
    mockAuthState = { user: null, isAuthenticated: false };
});

// ── 1. Direct URL navigation into another role's page ───────────────────

describe('direct URL navigation', () => {
    test('a user typing /admin is sent to Access Denied, not the Admin page', async () => {
        renderAt('/admin', ROLES.USER);

        expect(await screen.findByText('Access Denied Page')).toBeInTheDocument();
        expect(screen.queryByText('Admin Page')).not.toBeInTheDocument();
    });

    test('a coach typing /admin is sent to Access Denied', async () => {
        renderAt('/admin', ROLES.WELLNESS_COACH);

        expect(await screen.findByText('Access Denied Page')).toBeInTheDocument();
        expect(screen.queryByText('Admin Page')).not.toBeInTheDocument();
    });

    test('a user typing /wellness is sent to Access Denied', async () => {
        renderAt('/wellness', ROLES.USER);

        expect(await screen.findByText('Access Denied Page')).toBeInTheDocument();
        expect(screen.queryByText('Wellness Coach Dashboard Page')).not.toBeInTheDocument();
    });

    test('an admin typing /admin gets the Admin page', async () => {
        renderAt('/admin', ROLES.ADMIN);

        expect(await screen.findByText('Admin Page')).toBeInTheDocument();
    });
});

// ── 2. Reloading a protected page ───────────────────────────────────────

describe('page refresh on a protected route', () => {
    test('an admin reloading /admin still gets the Admin page', async () => {
        const first = renderAt('/admin', ROLES.ADMIN);
        expect(await screen.findByText('Admin Page')).toBeInTheDocument();
        first.unmount();

        // A reload re-mounts the app from the persisted session at the same URL.
        renderAt('/admin', ROLES.ADMIN);
        expect(await screen.findByText('Admin Page')).toBeInTheDocument();
    });

    test('a user reloading /admin is still denied', async () => {
        const first = renderAt('/admin', ROLES.USER);
        expect(await screen.findByText('Access Denied Page')).toBeInTheDocument();
        first.unmount();

        renderAt('/admin', ROLES.USER);
        expect(await screen.findByText('Access Denied Page')).toBeInTheDocument();
        expect(screen.queryByText('Admin Page')).not.toBeInTheDocument();
    });
});

// ── 3. Logout followed by the browser Back button ───────────────────────

describe('logout then browser Back', () => {
    test('a logged-out session cannot re-render the Admin page', async () => {
        const view = renderAt('/admin', ROLES.ADMIN);
        expect(await screen.findByText('Admin Page')).toBeInTheDocument();

        // Logout clears the store; Back replays the URL against empty state.
        mockAuthState = { user: null, isAuthenticated: false };
        await act(async () => {
            view.rerender(<App />);
        });

        expect(await screen.findByText('Login Page')).toBeInTheDocument();
        expect(screen.queryByText('Admin Page')).not.toBeInTheDocument();
    });

    test('a logged-out session cannot re-render the User Dashboard', async () => {
        const view = renderAt('/dashboard', ROLES.USER);
        expect(await screen.findByText('User Dashboard Page')).toBeInTheDocument();

        mockAuthState = { user: null, isAuthenticated: false };
        await act(async () => {
            view.rerender(<App />);
        });

        expect(await screen.findByText('Login Page')).toBeInTheDocument();
        expect(screen.queryByText('User Dashboard Page')).not.toBeInTheDocument();
    });
});

// ── 4. Expired / missing / invalid session ──────────────────────────────

describe('expired or invalid session', () => {
    test.each([
        ['/dashboard'],
        ['/admin'],
        ['/wellness'],
        ['/alarms'],
        ['/analytics'],
        ['/reports'],
        ['/profile'],
    ])('a guest hitting %s is redirected to login', async (path) => {
        renderAt(path, null);

        expect(await screen.findByText('Login Page')).toBeInTheDocument();
    });

    test('an expired session that left a stale user object still lands on login', async () => {
        // isAuthenticated is false once the token is gone, even if `user` lingers.
        mockAuthState = { user: { id: 1, role: ROLES.ADMIN }, isAuthenticated: false };
        window.history.pushState({}, '', '/admin');
        render(<App />);

        expect(await screen.findByText('Login Page')).toBeInTheDocument();
        expect(screen.queryByText('Admin Page')).not.toBeInTheDocument();
    });
});

// ── 5. Role manipulation through the frontend ───────────────────────────

describe('role manipulation attempts', () => {
    test.each([
        ['a missing role', undefined],
        ['a null role', null],
        ['an empty role', ''],
        ['an invented role', 'superadmin'],
        ['a case-mangled admin role', 'ADMIN'],
        ['a whitespace-padded admin role', ' admin '],
    ])('%s cannot open /admin', async (_label, role) => {
        mockAuthState = { user: { id: 1, role }, isAuthenticated: true };
        window.history.pushState({}, '', '/admin');
        render(<App />);

        expect(await screen.findByText('Access Denied Page')).toBeInTheDocument();
        expect(screen.queryByText('Admin Page')).not.toBeInTheDocument();
    });

    test('an unknown role cannot open /wellness', async () => {
        mockAuthState = { user: { id: 1, role: 'coach' }, isAuthenticated: true };
        window.history.pushState({}, '', '/wellness');
        render(<App />);

        expect(await screen.findByText('Access Denied Page')).toBeInTheDocument();
        expect(screen.queryByText('Wellness Coach Dashboard Page')).not.toBeInTheDocument();
    });

    test('a guest cannot reach a guest-only page while authenticated as admin', async () => {
        renderAt('/login', ROLES.ADMIN);

        // GuestRoute bounces an authenticated admin to their role home.
        expect(await screen.findByText('Admin Page')).toBeInTheDocument();
    });
});
