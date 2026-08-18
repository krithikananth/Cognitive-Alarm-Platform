// Notifee foreground + background event handlers, all converging on RingScreen
// (spec §6.2, task 7).
import { useEffect } from 'react';
import notifee, { EventType } from '@notifee/react-native';

import useRingStore, { setRingEffectsHandler } from '../store/ringStore';
import { isAlarmNotificationId, syncSchedule } from './scheduler';

// Events that mean "this alarm is going off now". DELIVERED covers the app
// already being open; PRESS/ACTION_PRESS cover the full-screen intent and the
// notification tap.
const RING_EVENT_TYPES = new Set([
    EventType.DELIVERED,
    EventType.PRESS,
    EventType.ACTION_PRESS,
]);

const toNumber = (value, fallback) => {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
};

/**
 * Rebuild ring parameters from a notification.
 *
 * Notifee ships `data` through the same string-only channel as FCM, so every
 * value arrives as text and has to be parsed back (see `asData` in scheduler.js).
 */
export function ringPayloadFromNotification(notification) {
    const data = notification?.data ?? {};
    const alarmId = toNumber(data.alarmId, 0);
    if (!alarmId || alarmId <= 0) return null;

    return {
        alarmId,
        notificationId: notification?.id ?? null,
        title: String(data.title || notification?.title || 'Alarm'),
        triggerAt: data.triggerAt ?? null,
        snoozeLimit: Math.max(0, toNumber(data.snoozeLimit, 0)),
        snoozeIntervalMinutes: Math.max(1, toNumber(data.snoozeIntervalMinutes, 5)),
    };
}

export function startRingFromNotification(notification) {
    if (!isAlarmNotificationId(notification?.id)) return false;
    const payload = ringPayloadFromNotification(notification);
    if (!payload) return false;
    return useRingStore.getState().startRing(payload);
}

export function handleNotifeeEvent({ type, detail } = {}) {
    if (!RING_EVENT_TYPES.has(type)) return false;
    return startRingFromNotification(detail?.notification);
}

/**
 * Registered at module scope in index.js, before React starts.
 *
 * Notifee drops events with no background handler, and the ring must not be
 * silently swallowed while the app is backgrounded. The notification itself is
 * deliberately left alone here: `launchActivity` brings the app up and
 * `getInitialNotification` resumes the ring in the UI context.
 */
export function registerRingBackgroundHandler() {
    notifee.onBackgroundEvent(async ({ type, detail }) => {
        if (!RING_EVENT_TYPES.has(type)) return;
        if (!isAlarmNotificationId(detail?.notification?.id)) return;
    });
}

/** Foreground events + the cold-start notification that launched the app. */
export default function useRingEvents() {
    useEffect(() => {
        const unsubscribe = notifee.onForegroundEvent(handleNotifeeEvent);

        let cancelled = false;
        Promise.resolve(notifee.getInitialNotification())
            .then((initial) => {
                // The alarm that launched the app via full-screen intent is only
                // visible here — no foreground event is emitted for it.
                if (!cancelled) startRingFromNotification(initial?.notification);
            })
            .catch(() => {
                // A missing initial notification is the normal case, not a fault.
            });

        return () => {
            cancelled = true;
            unsubscribe?.();
        };
    }, []);
}

setRingEffectsHandler({
    // Cancelling the notification is what actually stops the looping alarm tone.
    stop: async (notificationId) => {
        if (notificationId) await notifee.cancelNotification(notificationId);
        try {
            await notifee.stopForegroundService();
        } catch {
            // Throws when no foreground service is running, which is common.
        }
    },
    resync: () => syncSchedule(),
});
