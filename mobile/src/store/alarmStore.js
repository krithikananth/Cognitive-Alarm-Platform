// Zustand alarm store: alarm list + cached schedule (spec §6.1, task 5).
import { create } from 'zustand';

import * as alarmApi from '../api/alarms';
import { readErrorDetail } from '../api/client';

/** Keep the list in the server's order (by time of day) after a local edit. */
function sortByTime(alarms) {
    return alarms
        .slice()
        .sort((a, b) => String(a.alarm_time).localeCompare(String(b.alarm_time)));
}

let onAlarmsChanged = () => { };

/**
 * Registered by the alarm scheduler so a mutation re-arms the device.
 *
 * Injected rather than imported so the store never pulls in the Notifee native
 * module — which would make every store test require an Android runtime.
 */
export function setAlarmsChangedHandler(handler) {
    onAlarmsChanged = typeof handler === 'function' ? handler : () => { };
}

function notifyAlarmsChanged() {
    try {
        onAlarmsChanged();
    } catch {
        // A scheduling failure is surfaced by the scheduler's own summary; it must
        // not turn a successful save into an error the user sees.
    }
}

export const useAlarmStore = create((set, get) => ({
    alarms: [],
    loading: false,
    refreshing: false,
    error: null,
    saving: false,
    saveError: null,

    clearSaveError: () => set({ saveError: null }),

    fetchAlarms: async ({ refresh = false } = {}) => {
        set(refresh ? { refreshing: true } : { loading: true, error: null });
        try {
            const data = await alarmApi.listAlarms();
            set({
                alarms: Array.isArray(data?.alarms) ? data.alarms : [],
                loading: false,
                refreshing: false,
                error: null,
            });
            return true;
        } catch (error) {
            set({
                loading: false,
                refreshing: false,
                error: readErrorDetail(error, 'Could not load your alarms.'),
            });
            return false;
        }
    },

    createAlarm: async (payload) => {
        set({ saving: true, saveError: null });
        try {
            const alarm = await alarmApi.createAlarm(payload);
            set((state) => ({
                alarms: sortByTime([...state.alarms, alarm]),
                saving: false,
            }));
            notifyAlarmsChanged();
            return alarm;
        } catch (error) {
            set({
                saving: false,
                saveError: readErrorDetail(error, 'Could not save the alarm.'),
            });
            return null;
        }
    },

    updateAlarm: async (alarmId, payload) => {
        set({ saving: true, saveError: null });
        try {
            const alarm = await alarmApi.updateAlarm(alarmId, payload);
            set((state) => ({
                alarms: sortByTime(
                    state.alarms.map((item) => (item.id === alarmId ? alarm : item))
                ),
                saving: false,
            }));
            notifyAlarmsChanged();
            return alarm;
        } catch (error) {
            set({
                saving: false,
                saveError: readErrorDetail(error, 'Could not save the alarm.'),
            });
            return null;
        }
    },

    deleteAlarm: async (alarmId) => {
        const previous = get().alarms;
        set({ alarms: previous.filter((item) => item.id !== alarmId), error: null });
        try {
            await alarmApi.deleteAlarm(alarmId);
            notifyAlarmsChanged();
            return true;
        } catch (error) {
            // Put the row back: a list that silently loses an alarm the server
            // still holds would leave the user believing it will not ring.
            set({
                alarms: previous,
                error: readErrorDetail(error, 'Could not delete the alarm.'),
            });
            return false;
        }
    },

    toggleAlarm: async (alarmId, isActive) => {
        const previous = get().alarms;
        set({
            alarms: previous.map((item) =>
                item.id === alarmId ? { ...item, is_active: isActive } : item
            ),
            error: null,
        });
        try {
            const alarm = await alarmApi.toggleAlarm(alarmId, isActive);
            // Adopt the server row — arming recalculates `next_trigger_at`.
            set((state) => ({
                alarms: state.alarms.map((item) => (item.id === alarmId ? alarm : item)),
            }));
            notifyAlarmsChanged();
            return true;
        } catch (error) {
            set({
                alarms: previous,
                error: readErrorDetail(error, 'Could not update the alarm.'),
            });
            return false;
        }
    },
}));

export default useAlarmStore;

