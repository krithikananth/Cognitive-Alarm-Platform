// syncSchedule(): diff server occurrences against notifee trigger notifications
// using deterministic `alarm-{id}-{epoch}` ids (spec §6.1, task 6).
import notifee, {
    AlarmType,
    AndroidCategory,
    AndroidImportance,
    AndroidVisibility,
    TriggerType,
} from '@notifee/react-native';

import { fetchSchedule } from '../api/alarms';
import { setAlarmsChangedHandler } from '../store/alarmStore';
import { ALARM_CHANNEL_ID, ALARM_VIBRATION_PATTERN, ensureAlarmChannel } from './channel';

export const SCHEDULE_HORIZON_DAYS = 7;
export const NOTIFICATION_ID_PREFIX = 'alarm-';
export const RING_ACTION_ID = 'ring';

/**
 * Deterministic id for one ring instant.
 *
 * Because the id is derived from the alarm and the exact instant, re-running a
 * sync recognises what is already armed instead of stacking duplicates.
 */
export function occurrenceId(alarmId, triggerAt) {
    const epoch = triggerAt instanceof Date ? triggerAt.getTime() : new Date(triggerAt).getTime();
    return `${NOTIFICATION_ID_PREFIX}${alarmId}-${epoch}`;
}

export function isAlarmNotificationId(id) {
    return typeof id === 'string' && id.startsWith(NOTIFICATION_ID_PREFIX);
}

// Notifee ships `data` through the same string-only channel FCM uses, so a raw
// number or boolean would arrive as an unpredictable type on the ring screen.
function asData(occurrence) {
    return {
        alarmId: String(occurrence.alarm_id),
        triggerAt: String(occurrence.trigger_at),
        title: String(occurrence.title ?? 'Alarm'),
        challengeType: String(occurrence.challenge_type ?? 'random'),
        challengeCount: String(occurrence.challenge_count ?? 1),
        challengeDifficulty: String(occurrence.challenge_difficulty ?? 'medium'),
        snoozeLimit: String(occurrence.snooze_limit ?? 0),
        snoozeIntervalMinutes: String(occurrence.snooze_interval_minutes ?? 5),
        volume: String(occurrence.volume ?? 80),
        vibrate: String(Boolean(occurrence.vibrate)),
    };
}

export function buildNotification(occurrence) {
    return {
        id: occurrenceId(occurrence.alarm_id, occurrence.trigger_at),
        title: occurrence.title || 'Alarm',
        body: 'Solve the challenge to dismiss.',
        android: {
            channelId: ALARM_CHANNEL_ID,
            category: AndroidCategory.ALARM,
            importance: AndroidImportance.HIGH,
            visibility: AndroidVisibility.PUBLIC,
            // Takes over the lock screen rather than showing a heads-up card the
            // user can flick away without waking up.
            fullScreenAction: { id: RING_ACTION_ID, launchActivity: 'default' },
            pressAction: { id: RING_ACTION_ID, launchActivity: 'default' },
            ongoing: true,
            autoCancel: false,
            loopSound: true,
            vibrationPattern: occurrence.vibrate ? ALARM_VIBRATION_PATTERN : undefined,
        },
        data: asData(occurrence),
    };
}

export function buildTrigger(timestamp) {
    return {
        type: TriggerType.TIMESTAMP,
        timestamp,
        // SET_ALARM_CLOCK is the only AlarmManager mode exempt from Doze batching
        // and app-standby buckets. `allowWhileIdle` is deprecated in Notifee 9 and
        // is weaker: the OS may still delay it by minutes.
        alarmManager: { type: AlarmType.SET_ALARM_CLOCK },
    };
}

async function armedAlarmIds() {
    const existing = (await notifee.getTriggerNotifications()) ?? [];
    const ids = new Set();
    for (const entry of existing) {
        const id = entry?.notification?.id;
        if (isAlarmNotificationId(id)) ids.add(id);
    }
    return ids;
}

/**
 * Bring the device's armed alarms in line with the server's expansion.
 *
 * Returns a summary rather than throwing so callers (foreground sync, post-CRUD
 * sync, the future health banner) can report state without a try/catch each.
 */
export async function syncSchedule({
    horizonDays = SCHEDULE_HORIZON_DAYS,
    now = Date.now(),
} = {}) {
    let schedule;
    try {
        schedule = await fetchSchedule({ days: horizonDays });
    } catch (error) {
        // Deliberately no cancellation here. Treating an unreachable server as
        // "no alarms" would silently disarm the device on a network blip — the
        // one failure this app must never have.
        return { ok: false, created: 0, cancelled: 0, kept: 0, total: 0, error };
    }

    await ensureAlarmChannel();

    const desired = new Map();
    for (const occurrence of schedule?.occurrences ?? []) {
        const timestamp = new Date(occurrence?.trigger_at).getTime();
        // An instant in the past cannot be armed; AlarmManager would fire it at once.
        if (!Number.isFinite(timestamp) || timestamp <= now) continue;
        desired.set(occurrenceId(occurrence.alarm_id, occurrence.trigger_at), {
            occurrence,
            timestamp,
        });
    }

    const armed = await armedAlarmIds();

    // Only ids this module owns are eligible for cancellation, so a future
    // reminder or FCM notification is never collateral damage.
    const stale = [...armed].filter((id) => !desired.has(id));
    if (stale.length) {
        await notifee.cancelTriggerNotifications(stale);
    }

    let created = 0;
    for (const [id, { occurrence, timestamp }] of desired) {
        if (armed.has(id)) continue;
        await notifee.createTriggerNotification(
            buildNotification(occurrence),
            buildTrigger(timestamp)
        );
        created += 1;
    }

    return {
        ok: true,
        created,
        cancelled: stale.length,
        kept: desired.size - created,
        total: desired.size,
    };
}

/** Disarm everything this module scheduled — used on logout. */
export async function cancelAllAlarms() {
    const armed = await armedAlarmIds();
    if (armed.size) {
        await notifee.cancelTriggerNotifications([...armed]);
    }
    return armed.size;
}

// Any alarm mutation changes the expansion, so the device re-syncs immediately
// instead of waiting for the next foreground.
setAlarmsChangedHandler(() => {
    syncSchedule();
});

