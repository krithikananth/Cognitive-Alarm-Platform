/** Alarm sync lifecycle wiring (spec §6.1 "sync triggers", task 6). */
jest.mock('../src/api/client', () => ({
    __esModule: true,
    default: {},
    setSessionExpiredHandler: jest.fn(),
    readErrorDetail: jest.fn((error, fallback) => error?.detail || fallback),
}));

jest.mock('../src/alarm/scheduler', () => ({
    syncSchedule: jest.fn(async () => ({ ok: true })),
    cancelAllAlarms: jest.fn(async () => 0),
}));

const { AppState, Text } = require('react-native');
const { render, waitFor } = require('@testing-library/react-native');

const { cancelAllAlarms, syncSchedule } = require('../src/alarm/scheduler');
const useAuthStore = require('../src/store/authStore').default;
const { AUTH_STATUS } = require('../src/store/authStore');
const useAlarmSync = require('../src/alarm/useAlarmSync').default;

function Harness() {
    useAlarmSync();
    return <Text>harness</Text>;
}

let appStateListener;

beforeEach(() => {
    jest.clearAllMocks();
    syncSchedule.mockResolvedValue({ ok: true });
    cancelAllAlarms.mockResolvedValue(0);
    appStateListener = null;
    jest.spyOn(AppState, 'addEventListener').mockImplementation((event, handler) => {
        if (event === 'change') appStateListener = handler;
        return { remove: jest.fn() };
    });
});

afterEach(() => {
    AppState.addEventListener.mockRestore();
});

it('syncs as soon as the user is authenticated', async () => {
    useAuthStore.setState({ status: AUTH_STATUS.AUTHENTICATED });

    await render(<Harness />);

    await waitFor(() => expect(syncSchedule).toHaveBeenCalledTimes(1));
});

it('does not sync while signed out', async () => {
    useAuthStore.setState({ status: AUTH_STATUS.ANONYMOUS });

    await render(<Harness />);

    expect(syncSchedule).not.toHaveBeenCalled();
});

it('re-syncs when the app returns to the foreground', async () => {
    useAuthStore.setState({ status: AUTH_STATUS.AUTHENTICATED });
    await render(<Harness />);
    await waitFor(() => expect(syncSchedule).toHaveBeenCalledTimes(1));

    appStateListener('active');

    await waitFor(() => expect(syncSchedule).toHaveBeenCalledTimes(2));
});

it('ignores background transitions', async () => {
    useAuthStore.setState({ status: AUTH_STATUS.AUTHENTICATED });
    await render(<Harness />);
    await waitFor(() => expect(syncSchedule).toHaveBeenCalledTimes(1));

    appStateListener('background');
    appStateListener('inactive');

    expect(syncSchedule).toHaveBeenCalledTimes(1);
});

it('disarms the device when the session ends', async () => {
    useAuthStore.setState({ status: AUTH_STATUS.ANONYMOUS });

    await render(<Harness />);

    await waitFor(() => expect(cancelAllAlarms).toHaveBeenCalled());
});
