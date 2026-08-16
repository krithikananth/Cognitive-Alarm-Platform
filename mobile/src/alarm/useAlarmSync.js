// Keeps the device's armed alarms in step with the server across the app
// lifecycle (spec §6.1 "sync triggers", task 6).
import { useEffect } from 'react';
import { AppState } from 'react-native';

import useAuthStore, { AUTH_STATUS } from '../store/authStore';
import { cancelAllAlarms, syncSchedule } from './scheduler';

/**
 * Sync on sign-in and whenever the app returns to the foreground, and disarm
 * everything once the session ends.
 *
 * Foreground is the cheapest reliable moment to reconcile: the schedule may have
 * changed on the web app, and a 7-day horizon shortens every day it is not refreshed.
 */
export default function useAlarmSync() {
    const status = useAuthStore((state) => state.status);

    useEffect(() => {
        if (status !== AUTH_STATUS.AUTHENTICATED) return undefined;

        syncSchedule();
        const subscription = AppState.addEventListener('change', (nextState) => {
            if (nextState === 'active') syncSchedule();
        });
        return () => subscription.remove();
    }, [status]);

    useEffect(() => {
        // A signed-out device must not keep ringing for the previous account.
        if (status === AUTH_STATUS.ANONYMOUS) cancelAllAlarms();
    }, [status]);
}
