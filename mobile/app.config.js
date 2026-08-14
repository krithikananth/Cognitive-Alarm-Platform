const fs = require('fs');
const path = require('path');

// Android 9+ blocks plain HTTP, which the `adb reverse` LAN workflow depends on.
// Keying the exception off the scheme means it switches itself off the moment the
// app points at an https origin, instead of riding along into a release build.
const withCleartext = (plugins, allowCleartext) =>
  plugins.map((plugin) =>
    plugin === 'expo-build-properties'
      ? [
        'expo-build-properties',
        { android: { usesCleartextTraffic: allowCleartext } },
      ]
      : plugin
  );

// Overlays app.json with values that can only be decided at evaluation time.
module.exports = ({ config }) => {
  const googleServices = path.join(__dirname, 'google-services.json');
  const hasGoogleServices = fs.existsSync(googleServices);
  const apiBaseUrl = process.env.EXPO_PUBLIC_API_URL || config.extra.apiBaseUrl;

  const plugins = hasGoogleServices
    ? config.plugins
    : config.plugins.filter((p) => !String(p).startsWith('@react-native-firebase/'));

  return {
    ...config,
    android: {
      ...config.android,
      // @react-native-firebase/app fails prebuild when this points at a missing file,
      // so FCM (AD-5 backup path) only wires up once the file is dropped in.
      ...(hasGoogleServices ? { googleServicesFile: './google-services.json' } : {}),
    },
    plugins: [
      ...withCleartext(plugins, apiBaseUrl.startsWith('http://')),
      './plugins/withNotifeeRepository',
    ],
    extra: {
      ...config.extra,
      apiBaseUrl,
    },
  };
};
