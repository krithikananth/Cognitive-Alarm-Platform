/**
 * Profile settings visibility by role.
 *
 * Sleep Schedule and Preferences are alarm-user settings; a wellness coach
 * account must only see the account Profile tab.
 */
import React from 'react';
import { render, screen } from '@testing-library/react';
import { ROLES } from '../utils/routeAccess';

let mockAuthState = { user: null, fetchProfile: jest.fn(), logout: jest.fn() };

jest.mock('../store/authStore', () => ({
  __esModule: true,
  default: (selector) => (selector ? selector(mockAuthState) : mockAuthState),
}));

// Plain functions, not jest.fn(): CRA enables `resetMocks`, which would strip
// mock implementations before each test.
jest.mock('../services/api', () => ({
  __esModule: true,
  userAPI: {
    getProfile: () =>
      Promise.resolve({ data: { timezone: 'UTC', profile: { timezone: 'UTC' } } }),
    updateUser: () => Promise.resolve({ data: {} }),
    updateSleepSchedule: () => Promise.resolve({ data: {} }),
    updatePreferences: () => Promise.resolve({ data: {} }),
    deleteAccount: () => Promise.resolve({ data: {} }),
  },
  notificationAPI: {
    getPreferences: () => Promise.resolve({ data: {} }),
    updatePreferences: () => Promise.resolve({ data: {} }),
  },
}));

// eslint-disable-next-line import/first
import Profile from './Profile';

function renderProfileFor(role) {
  mockAuthState = {
    user: { id: 1, role, username: 'sam', email: 'sam@example.com', timezone: 'UTC' },
    fetchProfile: jest.fn(),
    logout: jest.fn(),
  };
  return render(<Profile />);
}

const tabButton = (name) => screen.queryByRole('button', { name });

describe('Profile settings by role', () => {
  test('a wellness coach only sees account information', async () => {
    renderProfileFor(ROLES.WELLNESS_COACH);

    expect(await screen.findByText('Personal Information')).toBeInTheDocument();
    expect(screen.getByText('Manage your account information')).toBeInTheDocument();
    expect(tabButton(/sleep schedule/i)).not.toBeInTheDocument();
    expect(tabButton(/preferences/i)).not.toBeInTheDocument();
  });

  test('a normal user keeps the sleep schedule and preferences settings', async () => {
    renderProfileFor(ROLES.USER);

    expect(await screen.findByText('Personal Information')).toBeInTheDocument();
    expect(
      screen.getByText('Manage your account, sleep schedule, and preferences')
    ).toBeInTheDocument();
    expect(tabButton(/sleep schedule/i)).toBeInTheDocument();
    expect(tabButton(/preferences/i)).toBeInTheDocument();
  });
});
