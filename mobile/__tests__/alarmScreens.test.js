/** Alarm list + editor screens (spec §2, task 5). */
// RNTL v14 made `render` and every `fireEvent` async — they must be awaited or
// the queries come back on an unresolved promise.
jest.mock('../src/api/client', () => ({
    __esModule: true,
    default: {},
    setSessionExpiredHandler: jest.fn(),
    readErrorDetail: jest.fn((error, fallback) => error?.detail || fallback),
}));

jest.mock('../src/api/alarms', () => ({
    listAlarms: jest.fn(),
    createAlarm: jest.fn(),
    updateAlarm: jest.fn(),
    deleteAlarm: jest.fn(),
    toggleAlarm: jest.fn(),
}));

const { fireEvent, render, waitFor } = require('@testing-library/react-native');

const alarmApi = require('../src/api/alarms');
const useAlarmStore = require('../src/store/alarmStore').default;
const AlarmListScreen = require('../src/screens/AlarmListScreen').default;
const AlarmEditScreen = require('../src/screens/AlarmEditScreen').default;

const ALARM = {
    id: 11,
    title: 'Morning Alarm',
    description: null,
    label: null,
    alarm_time: '07:00:00',
    alarm_type: 'daily',
    days_of_week: null,
    one_time_date: null,
    is_active: true,
    snooze_limit: 3,
    snooze_interval_minutes: 5,
    challenge_type: 'math',
    challenge_count: 1,
    challenge_difficulty: 'medium',
    volume: 80,
    vibrate: true,
    next_trigger_at: '2026-08-15T01:30:00Z',
};

function makeNavigation(overrides = {}) {
    return {
        navigate: jest.fn(),
        goBack: jest.fn(),
        setOptions: jest.fn(),
        addListener: jest.fn(() => jest.fn()),
        ...overrides,
    };
}

const renderEditor = (params = {}, navigation = makeNavigation()) =>
    render(<AlarmEditScreen navigation={navigation} route={{ params }} />);

beforeEach(() => {
    jest.clearAllMocks();
    useAlarmStore.setState({
        alarms: [],
        loading: false,
        refreshing: false,
        error: null,
        saving: false,
        saveError: null,
    });
});

describe('AlarmListScreen', () => {
    it('loads and renders the alarms with their next ring', async () => {
        alarmApi.listAlarms.mockResolvedValue({ alarms: [ALARM] });

        const { getByText, getByTestId } = await render(
            <AlarmListScreen navigation={makeNavigation()} />
        );

        await waitFor(() => expect(getByText('Morning Alarm')).toBeTruthy());
        expect(getByText('7:00 AM')).toBeTruthy();
        expect(getByText('Every day')).toBeTruthy();
        expect(getByTestId('alarm-next-11').props.children).toContain('Next ring');
    });

    it('shows the empty state when the user has no alarms', async () => {
        alarmApi.listAlarms.mockResolvedValue({ alarms: [] });

        const { getByTestId } = await render(
            <AlarmListScreen navigation={makeNavigation()} />
        );

        await waitFor(() => expect(getByTestId('alarm-list-empty')).toBeTruthy());
    });

    it('surfaces a load failure with a retry', async () => {
        alarmApi.listAlarms.mockRejectedValue({ detail: 'Cannot reach the server.' });

        const { getByText } = await render(
            <AlarmListScreen navigation={makeNavigation()} />
        );

        await waitFor(() => expect(getByText('Cannot reach the server.')).toBeTruthy());

        alarmApi.listAlarms.mockResolvedValue({ alarms: [ALARM] });
        await fireEvent.press(getByText('Try again'));

        await waitFor(() => expect(getByText('Morning Alarm')).toBeTruthy());
    });

    it('disarms an alarm through the toggle', async () => {
        alarmApi.listAlarms.mockResolvedValue({ alarms: [ALARM] });
        alarmApi.toggleAlarm.mockResolvedValue({
            ...ALARM,
            is_active: false,
            next_trigger_at: null,
        });

        const { getByTestId, getByText } = await render(
            <AlarmListScreen navigation={makeNavigation()} />
        );
        await waitFor(() => expect(getByTestId('alarm-toggle-11')).toBeTruthy());

        await fireEvent(getByTestId('alarm-toggle-11'), 'valueChange', false);

        await waitFor(() => expect(alarmApi.toggleAlarm).toHaveBeenCalledWith(11, false));
        await waitFor(() => expect(getByText('Off')).toBeTruthy());
    });

    it('opens the editor for an existing alarm', async () => {
        alarmApi.listAlarms.mockResolvedValue({ alarms: [ALARM] });
        const navigation = makeNavigation();

        const { getByTestId } = await render(<AlarmListScreen navigation={navigation} />);
        await waitFor(() => expect(getByTestId('alarm-edit-11')).toBeTruthy());

        await fireEvent.press(getByTestId('alarm-edit-11'));

        expect(navigation.navigate).toHaveBeenCalledWith('AlarmEdit', { alarm: ALARM });
    });
});

describe('AlarmEditScreen', () => {
    it('creates an alarm from the form values', async () => {
        alarmApi.createAlarm.mockResolvedValue({ ...ALARM, id: 99 });
        const navigation = makeNavigation();

        const { getByTestId } = await renderEditor({}, navigation);

        await fireEvent.changeText(getByTestId('alarm-title'), 'Gym');
        await fireEvent.changeText(getByTestId('alarm-hour'), '6');
        await fireEvent.changeText(getByTestId('alarm-minute'), '15');
        await fireEvent.press(getByTestId('alarm-challenge-logic'));
        await fireEvent.press(getByTestId('alarm-save'));

        await waitFor(() => expect(alarmApi.createAlarm).toHaveBeenCalled());
        expect(alarmApi.createAlarm).toHaveBeenCalledWith(
            expect.objectContaining({
                title: 'Gym',
                alarm_time: '06:15:00',
                alarm_type: 'daily',
                challenge_type: 'logic',
                days_of_week: null,
            })
        );
        expect(navigation.goBack).toHaveBeenCalled();
    });

    it('prefills an existing alarm and sends the edit', async () => {
        alarmApi.updateAlarm.mockResolvedValue(ALARM);
        const navigation = makeNavigation();

        const { getByTestId } = await renderEditor({ alarm: ALARM }, navigation);

        expect(getByTestId('alarm-title').props.value).toBe('Morning Alarm');
        expect(getByTestId('alarm-hour').props.value).toBe('7');

        await fireEvent.press(getByTestId('alarm-save'));

        await waitFor(() => expect(alarmApi.updateAlarm).toHaveBeenCalled());
        expect(alarmApi.updateAlarm.mock.calls[0][0]).toBe(11);
    });

    it('rejects an out-of-range hour before calling the API', async () => {
        const { getByTestId, getByText } = await renderEditor();

        await fireEvent.changeText(getByTestId('alarm-hour'), '19');
        await fireEvent.press(getByTestId('alarm-save'));

        expect(getByText('Hour must be 1-12.')).toBeTruthy();
        expect(alarmApi.createAlarm).not.toHaveBeenCalled();
    });

    it('drops days the new pattern can never ring on', async () => {
        alarmApi.createAlarm.mockResolvedValue(ALARM);

        const { getByTestId } = await renderEditor();

        await fireEvent.press(getByTestId('alarm-day-0')); // Mon
        await fireEvent.press(getByTestId('alarm-day-5')); // Sat
        await fireEvent.press(getByTestId('alarm-type-weekend'));
        await fireEvent.press(getByTestId('alarm-save'));

        await waitFor(() => expect(alarmApi.createAlarm).toHaveBeenCalled());
        expect(alarmApi.createAlarm).toHaveBeenCalledWith(
            expect.objectContaining({ alarm_type: 'weekend', days_of_week: [5] })
        );
    });

    it('swaps the day picker for a date field on one-time alarms', async () => {
        const { getByTestId, queryByTestId } = await renderEditor();

        await fireEvent.press(getByTestId('alarm-type-one_time'));

        expect(queryByTestId('alarm-day-0')).toBeNull();
        expect(getByTestId('alarm-one-time-date')).toBeTruthy();
    });

    it('validates the one-time date format', async () => {
        const { getByTestId, getByText } = await renderEditor();

        await fireEvent.press(getByTestId('alarm-type-one_time'));
        await fireEvent.changeText(getByTestId('alarm-one-time-date'), '20-08-2026');
        await fireEvent.press(getByTestId('alarm-save'));

        expect(getByText('Use YYYY-MM-DD.')).toBeTruthy();
        expect(alarmApi.createAlarm).not.toHaveBeenCalled();
    });

    it('keeps the user on the form when saving fails', async () => {
        alarmApi.createAlarm.mockRejectedValue({ detail: 'Alarm limit reached' });
        const navigation = makeNavigation();

        const { getByTestId, getByText } = await renderEditor({}, navigation);

        await fireEvent.press(getByTestId('alarm-save'));

        await waitFor(() => expect(getByText('Alarm limit reached')).toBeTruthy());
        expect(navigation.goBack).not.toHaveBeenCalled();
    });

    it('steps bounded values without ever emitting an empty number', async () => {
        const { getByTestId } = await renderEditor();

        await fireEvent.press(getByTestId('alarm-volume-decrement'));
        expect(getByTestId('alarm-volume-value').props.children).toEqual([75, '%']);

        // Already at the minimum, so the control must refuse to go lower.
        await fireEvent.press(getByTestId('alarm-challenge-count-decrement'));
        expect(getByTestId('alarm-challenge-count-value').props.children).toEqual([1, '']);
    });
});
