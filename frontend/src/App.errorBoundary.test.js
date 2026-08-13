/**
 * App-level render-error containment.
 *
 * An uncaught exception during render unmounts the whole React tree, which
 * shows the user a blank white page with no way back. `ErrorBoundary` itself is
 * unit-tested; these tests pin that it is actually wired into `App` — a page
 * that throws must produce a recoverable fallback, and navigating away must
 * clear it rather than trapping the session.
 */
import React from 'react';
import { act, render, screen } from '@testing-library/react';
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

jest.mock('./services/errorReporting', () => ({
    __esModule: true,
    reportClientError: jest.fn(),
    installGlobalErrorHandlers: jest.fn(),
}));

// The ringing modal lives outside the routed tree; make it explode on demand.
let mockModalExplodes = false;
jest.mock('./components/ActiveAlarmModal', () => ({
    __esModule: true,
    default: () => {
        if (mockModalExplodes) throw new Error('modal exploded');
        return null;
    },
}));

jest.mock('./components/Layout', () => {
    const ReactActual = jest.requireActual('react');
    const { Outlet } = jest.requireActual('react-router-dom');
    return { __esModule: true, default: () => ReactActual.createElement(Outlet) };
});

jest.mock('./pages/UserDashboard', () => ({
    __esModule: true,
    default: () => {
        throw new Error('dashboard exploded');
    },
}));
jest.mock('./pages/Profile', () => ({ __esModule: true, default: () => 'Profile Page' }));
jest.mock('./pages/WellnessCoachDashboard', () => ({ __esModule: true, default: () => 'Coach Page' }));
jest.mock('./pages/AdminDashboard', () => ({ __esModule: true, default: () => 'Admin Page' }));
jest.mock('./pages/AccessDenied', () => ({ __esModule: true, default: () => 'Access Denied Page' }));
jest.mock('./pages/AlarmManager', () => ({ __esModule: true, default: () => 'Alarms Page' }));
jest.mock('./pages/Analytics', () => ({ __esModule: true, default: () => 'Analytics Page' }));
jest.mock('./pages/Recommendations', () => ({ __esModule: true, default: () => 'Recommendations Page' }));
jest.mock('./pages/Reports', () => ({ __esModule: true, default: () => 'Reports Page' }));
jest.mock('./pages/PracticeChallenge', () => ({ __esModule: true, default: () => 'Practice Page' }));
jest.mock('./pages/Login', () => ({ __esModule: true, default: () => 'Login Page' }));
jest.mock('./pages/Register', () => ({ __esModule: true, default: () => 'Register Page' }));
jest.mock('./pages/ForgotPassword', () => ({ __esModule: true, default: () => 'Forgot Page' }));
jest.mock('./pages/ResetPassword', () => ({ __esModule: true, default: () => 'Reset Page' }));
jest.mock('./pages/VerifyEmail', () => ({ __esModule: true, default: () => 'Verify Page' }));
jest.mock('./pages/OAuthCallback', () => ({ __esModule: true, default: () => 'OAuth Page' }));
jest.mock('./pages/NotFound', () => ({ __esModule: true, default: () => 'Not Found Page' }));

// eslint-disable-next-line import/first
import App from './App';
// eslint-disable-next-line import/first
import { reportClientError } from './services/errorReporting';

let consoleError;

beforeEach(() => {
    mockModalExplodes = false;
    reportClientError.mockReturnValue({ request_id: 'trace-xyz' });
    // React logs every boundary-caught error; that noise is expected here.
    consoleError = jest.spyOn(console, 'error').mockImplementation(() => { });
});

afterEach(() => {
    consoleError.mockRestore();
    mockAuthState = { user: null, isAuthenticated: false };
});

function renderAt(path) {
    mockAuthState = { user: { id: 1, role: ROLES.USER }, isAuthenticated: true };
    window.history.pushState({}, '', path);
    return render(<App />);
}

describe('a crashing page does not white-screen the app', () => {
    // Routes are code-split, so the boundary only catches once the chunk resolves.
    it('renders a recoverable fallback instead of an empty tree', async () => {
        renderAt('/dashboard');

        expect(await screen.findByRole('alert')).toBeInTheDocument();
        expect(screen.getByText('Something went wrong')).toBeInTheDocument();
        expect(screen.getByRole('button', { name: /try again/i })).toBeInTheDocument();
    });

    it('reports the crash with the boundary that caught it', async () => {
        renderAt('/dashboard');

        expect(await screen.findByRole('alert')).toBeInTheDocument();
        expect(reportClientError).toHaveBeenCalledWith(
            expect.any(Error),
            expect.objectContaining({ source: 'error_boundary', boundary: 'route' })
        );
        expect(screen.getByText('trace-xyz')).toBeInTheDocument();
    });

    it('clears the fallback when the user navigates away', async () => {
        renderAt('/dashboard');
        expect(await screen.findByRole('alert')).toBeInTheDocument();

        act(() => {
            window.history.pushState({}, '', '/profile');
            window.dispatchEvent(new PopStateEvent('popstate'));
        });

        expect(await screen.findByText('Profile Page')).toBeInTheDocument();
        expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    });
});

describe('a crashing alarm modal does not take the app with it', () => {
    it('keeps the routed page rendered', () => {
        mockModalExplodes = true;
        renderAt('/profile');

        expect(screen.getByText('Profile Page')).toBeInTheDocument();
        expect(reportClientError).toHaveBeenCalledWith(
            expect.any(Error),
            expect.objectContaining({ boundary: 'active-alarm' })
        );
    });
});
