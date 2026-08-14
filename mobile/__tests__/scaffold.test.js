const appJson = require('../app.json');
const appConfig = require('../app.config');

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

describe('cleartext exception', () => {
  const evaluate = (apiUrl) => {
    const previous = process.env.EXPO_PUBLIC_API_URL;
    if (apiUrl === undefined) delete process.env.EXPO_PUBLIC_API_URL;
    else process.env.EXPO_PUBLIC_API_URL = apiUrl;
    try {
      return appConfig({ config: appJson.expo });
    } finally {
      if (previous === undefined) delete process.env.EXPO_PUBLIC_API_URL;
      else process.env.EXPO_PUBLIC_API_URL = previous;
    }
  };

  const buildProperties = (resolved) =>
    resolved.plugins.find(
      (plugin) => Array.isArray(plugin) && plugin[0] === 'expo-build-properties'
    );

  it('is enabled for a plain-HTTP dev backend', () => {
    const plugin = buildProperties(evaluate('http://192.168.1.10:8000/api/v1'));
    expect(plugin[1].android.usesCleartextTraffic).toBe(true);
  });

  it('turns itself off once the app points at https', () => {
    const plugin = buildProperties(evaluate('https://icap.example.com/api/v1'));
    expect(plugin[1].android.usesCleartextTraffic).toBe(false);
  });

  it('always configures the plugin explicitly rather than by omission', () => {
    // A bare "expo-build-properties" string would silently inherit Android's
    // default, making the setting invisible at review time.
    expect(evaluate(undefined).plugins).not.toContain('expo-build-properties');
  });
});

describe('alarm channel', () => {
  it('matches the channel id the backend FCM config will target', () => {
    expect(ALARM_CHANNEL_ID).toBe('icap-alarm');
  });
});
