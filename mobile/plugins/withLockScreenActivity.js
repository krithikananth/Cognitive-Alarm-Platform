const { AndroidConfig, withAndroidManifest } = require('expo/config-plugins');

const { getMainActivityOrThrow } = AndroidConfig.Manifest;

// Notifee's full-screen intent launches MainActivity. Without these two attributes
// Android puts it *behind* the keyguard, so the ring screen is invisible until the
// phone is unlocked by hand — which defeats the whole alarm (spec §7, DoD 1-3).
// They apply to the single RN activity, so the app can surface over the lock screen
// generally; that is the accepted trade-off for an alarm clock.
const LOCK_SCREEN_ATTRIBUTES = {
    'android:showWhenLocked': 'true',
    'android:turnScreenOn': 'true',
};

function applyLockScreenAttributes(androidManifest) {
    const mainActivity = getMainActivityOrThrow(androidManifest);

    Object.assign(mainActivity.$, LOCK_SCREEN_ATTRIBUTES);

    return androidManifest;
}

module.exports = function withLockScreenActivity(config) {
    return withAndroidManifest(config, (manifestConfig) => {
        applyLockScreenAttributes(manifestConfig.modResults);
        return manifestConfig;
    });
};

module.exports.applyLockScreenAttributes = applyLockScreenAttributes;
module.exports.LOCK_SCREEN_ATTRIBUTES = LOCK_SCREEN_ATTRIBUTES;
