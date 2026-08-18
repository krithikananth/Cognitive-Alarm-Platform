/** RingScreen (spec §6.3, task 7). RNTL v14: `render` and `fireEvent` are async. */
jest.mock('../src/api/client', () => ({
    __esModule: true,
    default: {},
    setSessionExpiredHandler: jest.fn(),
    readErrorDetail: jest.fn((error, fallback) => error?.response?.data?.detail || fallback),
}));

jest.mock('../src/api/alarms', () => ({
    fetchChallenge: jest.fn(),
    verifyChallenge: jest.fn(),
    snoozeAlarm: jest.fn(),
    failWake: jest.fn(),
}));

jest.mock('expo-keep-awake', () => ({ useKeepAwake: jest.fn() }));

const { Alert } = require('react-native');
const { act, fireEvent, render, waitFor } = require('@testing-library/react-native');

const alarmApi = require('../src/api/alarms');
const useRingStore = require('../src/store/ringStore').default;
const { RING_STATUS, setRingEffectsHandler } = require('../src/store/ringStore');
const RingScreen = require('../src/screens/RingScreen').default;

const CHALLENGE = {
    type: 'math',
    prompt: '7 + 8 = ?',
    options: ['13', '15', '17', '21'],
    difficulty: 'medium',
    time_limit_seconds: 30,
    current_step: 1,
    total_steps: 1,
};

beforeEach(() => {
    jest.clearAllMocks();
    setRingEffectsHandler({ stop: jest.fn(async () => { }), resync: jest.fn(async () => { }) });
    useRingStore.getState().stopRing();
    alarmApi.fetchChallenge.mockResolvedValue(CHALLENGE);
});

/** Put the store in the ringing state the navigator would have mounted for. */
async function ringing(overrides = {}) {
    useRingStore.getState().startRing({
        alarmId: 11,
        notificationId: 'alarm-11-1755390600000',
        title: 'Morning Alarm',
        snoozeLimit: 3,
        snoozeIntervalMinutes: 5,
        ...overrides,
    });
    await waitFor(() => expect(useRingStore.getState().status).toBe(RING_STATUS.CHALLENGE));
}

describe('challenge rendering', () => {
    it('shows the prompt, the options and the alarm title', async () => {
        await ringing();
        const screen = await render(<RingScreen />);

        expect(await screen.findByTestId('ring-prompt')).toHaveTextContent('7 + 8 = ?');
        expect(screen.getByText('Morning Alarm')).toBeTruthy();
        expect(screen.getByTestId('ring-option-1')).toHaveTextContent('15');
    });

    it('falls back to a text field when the challenge has no options', async () => {
        alarmApi.fetchChallenge.mockResolvedValue({ ...CHALLENGE, options: null });
        await ringing();
        const screen = await render(<RingScreen />);

        expect(await screen.findByTestId('ring-answer')).toBeTruthy();
        expect(screen.queryByTestId('ring-option-0')).toBeNull();
    });

    it('cannot submit until an answer is chosen', async () => {
        await ringing();
        const screen = await render(<RingScreen />);

        const submit = await screen.findByTestId('ring-submit');
        expect(submit.props.accessibilityState.disabled).toBe(true);

        await fireEvent.press(screen.getByTestId('ring-option-1'));
        expect(screen.getByTestId('ring-submit').props.accessibilityState.disabled).toBe(false);
    });
});

describe('submitting', () => {
    it('sends the selected option', async () => {
        alarmApi.verifyChallenge.mockResolvedValue({ is_dismissed: true, message: 'Wake-up verified!' });
        await ringing();
        const screen = await render(<RingScreen />);

        await fireEvent.press(await screen.findByTestId('ring-option-1'));
        await fireEvent.press(screen.getByTestId('ring-submit'));

        await waitFor(() =>
            expect(alarmApi.verifyChallenge).toHaveBeenCalledWith(
                11,
                expect.objectContaining({ user_answer: '15' })
            )
        );
    });

    it('shows the rejection and keeps the user on the ring', async () => {
        alarmApi.verifyChallenge.mockRejectedValue({
            response: { status: 400, data: { detail: 'Incorrect answer. Try again.' } },
        });
        await ringing();
        const screen = await render(<RingScreen />);

        await fireEvent.press(await screen.findByTestId('ring-option-0'));
        await fireEvent.press(screen.getByTestId('ring-submit'));

        expect(await screen.findByTestId('ring-feedback')).toHaveTextContent(
            'Incorrect answer. Try again.'
        );
        expect(screen.getByTestId('ring-screen')).toBeTruthy();
    });

    it('switches to the verified summary once the alarm is dismissed', async () => {
        alarmApi.verifyChallenge.mockResolvedValue({
            is_dismissed: true,
            message: 'Wake-up verified! Alarm dismissed.',
            wakefulness: { level: 'alert' },
            success_streak: 4,
        });
        await ringing();
        const screen = await render(<RingScreen />);

        await fireEvent.press(await screen.findByTestId('ring-option-1'));
        await fireEvent.press(screen.getByTestId('ring-submit'));

        expect(await screen.findByTestId('ring-summary')).toBeTruthy();
        expect(screen.getByText('Wake verified')).toBeTruthy();
        expect(screen.getByTestId('ring-wakefulness')).toHaveTextContent(/alert/);
    });
});

describe('snooze and give up', () => {
    it('labels the remaining snoozes', async () => {
        await ringing();
        const screen = await render(<RingScreen />);

        expect(await screen.findByTestId('ring-snooze')).toHaveTextContent('Snooze (3 left)');
    });

    it('disables snooze for an alarm that allows none', async () => {
        await ringing({ snoozeLimit: 0 });
        const screen = await render(<RingScreen />);

        const snooze = await screen.findByTestId('ring-snooze');
        expect(snooze).toHaveTextContent('No snoozes left');
        expect(snooze.props.accessibilityState.disabled).toBe(true);
    });

    it('asks for confirmation before abandoning the wake', async () => {
        const alert = jest.spyOn(Alert, 'alert').mockImplementation(() => { });
        await ringing();
        const screen = await render(<RingScreen />);

        await fireEvent.press(await screen.findByTestId('ring-give-up'));

        expect(alert).toHaveBeenCalled();
        // Confirmation matters: the destructive action records an unverified
        // wake and breaks the streak.
        expect(alarmApi.failWake).not.toHaveBeenCalled();
        alert.mockRestore();
    });
});

describe('countdown', () => {
    it('renders the remaining time from the server limit', async () => {
        await ringing();
        const screen = await render(<RingScreen />);

        expect(await screen.findByTestId('ring-countdown')).toHaveTextContent('00:30');
    });

    it('lets the server rule on a timeout instead of judging it locally', async () => {
        jest.useFakeTimers();
        try {
            alarmApi.verifyChallenge.mockRejectedValue({
                response: { status: 400, data: { detail: "Time's up!" } },
            });
            await ringing();
            const screen = await render(<RingScreen />);
            await screen.findByTestId('ring-countdown');

            await act(async () => {
                useRingStore.setState({ issuedAt: Date.now() - 31000 });
                jest.advanceTimersByTime(1000);
            });

            await waitFor(() => expect(alarmApi.verifyChallenge).toHaveBeenCalled());
        } finally {
            jest.useRealTimers();
        }
    });
});
