const appJson = require('../app.json');

const { ALARM_CHANNEL_ID } = require('../src/alarm/channel');

// Permissions the alarm engine cannot work without (spec §7).
const REQUIRED_PERMISSIONS = [
  'android.permission.SCHEDULE_EXACT_ALARM',
  'android.permission.USE_EXACT_ALARM',
  'android.permission.POST_NOTIFICATIONS',
  'android.permission.USE_FULL_SCREEN_INTENT',
  'android.permission.WAKE_LOCK',
  'android.permission.RECEIVE_BOOT_COMPLETED',
  'android.permission.FOREGROUND_SERVICE',
  'android.permission.FOREGROUND_SERVICE_MEDIA_PLAYBACK',
  'android.permission.VIBRATE',
  'android.permission.REQUEST_IGNORE_BATTERY_OPTIMIZATIONS',
];

describe('expo config', () => {
  it('declares every android permission the alarm engine depends on', () => {
    expect(appJson.expo.android.permissions).toEqual(
      expect.arrayContaining(REQUIRED_PERMISSIONS)
    );
  });

  it('is android-only with a deep-link scheme for the full-screen intent', () => {
    expect(appJson.expo.platforms).toEqual(['android']);
    expect(appJson.expo.scheme).toBe('icapalarm');
  });

  it('registers the dev-client plugin required by AD-1', () => {
    expect(appJson.expo.plugins).toContain('expo-dev-client');
  });
});

describe('alarm channel', () => {
  it('matches the channel id the backend FCM config will target', () => {
    expect(ALARM_CHANNEL_ID).toBe('icap-alarm');
  });
});
