/**
 * Accounts created by backend/scripts/e2e_backend.py.
 *
 * Keep both files in step: the seeder owns the data, this module is only the
 * spec-side view of it.
 */
const PASSWORD = 'E2ePass123!';

const ACCOUNTS = {
    user: {
        email: 'e2e.user@example.com',
        username: 'e2euser',
        fullName: 'Eva Everyday',
        password: PASSWORD,
        home: '/dashboard',
    },
    coach: {
        email: 'e2e.coach@example.com',
        username: 'e2ecoach',
        fullName: 'Cody Coach',
        password: PASSWORD,
        home: '/wellness',
    },
    admin: {
        email: 'e2e.admin@example.com',
        username: 'e2eadmin',
        fullName: 'Ada Admin',
        password: PASSWORD,
        home: '/admin',
    },
    // Owned exclusively by the password-reset journey, which changes its password.
    resetter: {
        email: 'e2e.reset@example.com',
        username: 'e2ereset',
        fullName: 'Rita Reset',
        password: PASSWORD,
        newPassword: 'E2eReset456!',
        home: '/dashboard',
    },
    // Owned exclusively by the admin journey, which deactivates and restores it.
    unverified: {
        email: 'e2e.unverified@example.com',
        username: 'e2eunverified',
        fullName: 'Uma Unverified',
        password: PASSWORD,
    },
    // Owned exclusively by the verified-wake journey. Seeded with no history,
    // so its dashboard starts in the empty state.
    waker: {
        email: 'e2e.waker@example.com',
        username: 'e2ewaker',
        fullName: 'Wes Waker',
        password: PASSWORD,
        home: '/dashboard',
    },
};

const SEEDED_ALARM_TITLE = 'Seeded Morning Alarm';
const VERIFIED_WAKE_ALARM_TITLE = 'Verified Wake Alarm';

/** A registration email that cannot collide with a previous run. */
function uniqueEmail(prefix = 'signup') {
    return `e2e.${prefix}.${Date.now()}@example.com`;
}

module.exports = {
    ACCOUNTS,
    PASSWORD,
    SEEDED_ALARM_TITLE,
    VERIFIED_WAKE_ALARM_TITLE,
    uniqueEmail,
};
