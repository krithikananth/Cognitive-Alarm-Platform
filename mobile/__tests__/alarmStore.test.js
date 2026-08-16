/** Alarm store (spec §6.1, task 5): list, CRUD and optimistic toggle/delete. */
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

const alarmApi = require('../src/api/alarms');
const useAlarmStore = require('../src/store/alarmStore').default;
const { setAlarmsChangedHandler } = require('../src/store/alarmStore');

const ALARM = {
    id: 1,
    title: 'Morning',
    alarm_time: '07:00:00',
    alarm_type: 'daily',
    is_active: true,
    next_trigger_at: '2026-08-15T01:30:00Z',
};

const LATER = { ...ALARM, id: 2, title: 'Evening', alarm_time: '21:00:00' };

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

describe('fetchAlarms', () => {
    it('stores the returned page', async () => {
        alarmApi.listAlarms.mockResolvedValue({ alarms: [ALARM], total: 1 });

        await useAlarmStore.getState().fetchAlarms();

        expect(useAlarmStore.getState().alarms).toEqual([ALARM]);
        expect(useAlarmStore.getState().loading).toBe(false);
        expect(useAlarmStore.getState().error).toBeNull();
    });

    it('surfaces a readable error', async () => {
        alarmApi.listAlarms.mockRejectedValue({ detail: 'Server exploded' });

        await useAlarmStore.getState().fetchAlarms();

        expect(useAlarmStore.getState().error).toBe('Server exploded');
        expect(useAlarmStore.getState().loading).toBe(false);
    });

    it('uses the refreshing flag for pull-to-refresh so the list is not blanked', async () => {
        useAlarmStore.setState({ alarms: [ALARM] });
        let observedLoading = null;
        alarmApi.listAlarms.mockImplementation(async () => {
            observedLoading = useAlarmStore.getState().loading;
            return { alarms: [ALARM] };
        });

        await useAlarmStore.getState().fetchAlarms({ refresh: true });

        expect(observedLoading).toBe(false);
        expect(useAlarmStore.getState().refreshing).toBe(false);
    });
});

describe('createAlarm / updateAlarm', () => {
    it('adds the created alarm in time order', async () => {
        useAlarmStore.setState({ alarms: [LATER] });
        alarmApi.createAlarm.mockResolvedValue(ALARM);

        const created = await useAlarmStore.getState().createAlarm({ title: 'Morning' });

        expect(created).toEqual(ALARM);
        expect(useAlarmStore.getState().alarms.map((a) => a.id)).toEqual([1, 2]);
    });

    it('replaces the edited alarm and reports failures without losing the list', async () => {
        useAlarmStore.setState({ alarms: [ALARM] });
        alarmApi.updateAlarm.mockRejectedValue({ detail: 'Invalid time' });

        const result = await useAlarmStore.getState().updateAlarm(1, { title: 'x' });

        expect(result).toBeNull();
        expect(useAlarmStore.getState().saveError).toBe('Invalid time');
        expect(useAlarmStore.getState().alarms).toEqual([ALARM]);
    });
});

describe('optimistic mutations', () => {
    it('toggles immediately and adopts the server row', async () => {
        useAlarmStore.setState({ alarms: [ALARM] });
        let seenDuringRequest = null;
        alarmApi.toggleAlarm.mockImplementation(async () => {
            seenDuringRequest = useAlarmStore.getState().alarms[0].is_active;
            return { ...ALARM, is_active: false, next_trigger_at: null };
        });

        await useAlarmStore.getState().toggleAlarm(1, false);

        expect(seenDuringRequest).toBe(false);
        expect(useAlarmStore.getState().alarms[0].next_trigger_at).toBeNull();
    });

    it('reverts a failed toggle so the UI cannot claim an alarm is off', async () => {
        useAlarmStore.setState({ alarms: [ALARM] });
        alarmApi.toggleAlarm.mockRejectedValue({ detail: 'Offline' });

        const ok = await useAlarmStore.getState().toggleAlarm(1, false);

        expect(ok).toBe(false);
        expect(useAlarmStore.getState().alarms[0].is_active).toBe(true);
        expect(useAlarmStore.getState().error).toBe('Offline');
    });

    it('restores a row when the delete fails', async () => {
        useAlarmStore.setState({ alarms: [ALARM, LATER] });
        alarmApi.deleteAlarm.mockRejectedValue({ detail: 'Nope' });

        const ok = await useAlarmStore.getState().deleteAlarm(1);

        expect(ok).toBe(false);
        expect(useAlarmStore.getState().alarms).toHaveLength(2);
        expect(useAlarmStore.getState().error).toBe('Nope');
    });

    it('keeps the row removed when the delete succeeds', async () => {
        useAlarmStore.setState({ alarms: [ALARM, LATER] });
        alarmApi.deleteAlarm.mockResolvedValue(undefined);

        await useAlarmStore.getState().deleteAlarm(1);

        expect(useAlarmStore.getState().alarms.map((a) => a.id)).toEqual([2]);
    });
});

describe('re-arming the device after a change', () => {
    const onChanged = jest.fn();

    beforeEach(() => {
        onChanged.mockClear();
        setAlarmsChangedHandler(onChanged);
    });

    afterAll(() => setAlarmsChangedHandler(null));

    it.each([
        ['create', async () => {
            alarmApi.createAlarm.mockResolvedValue(ALARM);
            await useAlarmStore.getState().createAlarm({});
        }],
        ['update', async () => {
            alarmApi.updateAlarm.mockResolvedValue(ALARM);
            await useAlarmStore.getState().updateAlarm(1, {});
        }],
        ['delete', async () => {
            alarmApi.deleteAlarm.mockResolvedValue(undefined);
            await useAlarmStore.getState().deleteAlarm(1);
        }],
        ['toggle', async () => {
            alarmApi.toggleAlarm.mockResolvedValue(ALARM);
            await useAlarmStore.getState().toggleAlarm(1, false);
        }],
    ])('notifies after a successful %s', async (_name, mutate) => {
        await mutate();
        expect(onChanged).toHaveBeenCalledTimes(1);
    });

    it('does not notify when the mutation failed', async () => {
        alarmApi.createAlarm.mockRejectedValue({ detail: 'nope' });
        alarmApi.toggleAlarm.mockRejectedValue({ detail: 'nope' });
        useAlarmStore.setState({ alarms: [ALARM] });

        await useAlarmStore.getState().createAlarm({});
        await useAlarmStore.getState().toggleAlarm(1, false);

        expect(onChanged).not.toHaveBeenCalled();
    });

    it('does not fail the save when re-arming throws', async () => {
        setAlarmsChangedHandler(() => {
            throw new Error('notifee unavailable');
        });
        alarmApi.createAlarm.mockResolvedValue(ALARM);

        await expect(useAlarmStore.getState().createAlarm({})).resolves.toEqual(ALARM);
    });
});

