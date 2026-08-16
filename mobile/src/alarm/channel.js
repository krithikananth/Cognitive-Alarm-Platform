// Notifee notification channel (spec §6.1, task 6). The id is a shared contract with the
// backend Android FCM config (spec §4.2).
import notifee, { AndroidImportance, AndroidVisibility } from '@notifee/react-native';

export const ALARM_CHANNEL_ID = 'icap-alarm';

// Raw resource name (assets/alarm.mp3 -> res/raw/alarm). Android silently falls back to
// the default tone when the resource is missing, which is far too quiet for an alarm.
export const ALARM_SOUND_NAME = 'alarm';

export const ALARM_VIBRATION_PATTERN = [300, 500, 300, 500];

/**
 * Create (or update) the alarm channel.
 *
 * Android freezes a channel's importance and sound at creation time, so this is
 * idempotent rather than authoritative: changing them later needs a new channel id.
 */
export async function ensureAlarmChannel() {
    return notifee.createChannel({
        id: ALARM_CHANNEL_ID,
        name: 'Alarms',
        description: 'Wake-up alarms that require a challenge to dismiss',
        importance: AndroidImportance.HIGH,
        visibility: AndroidVisibility.PUBLIC,
        sound: ALARM_SOUND_NAME,
        vibration: true,
        vibrationPattern: ALARM_VIBRATION_PATTERN,
        // An alarm the user asked for must still ring in Do Not Disturb.
        bypassDnd: true,
    });
}

