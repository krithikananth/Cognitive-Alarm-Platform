const fs = require('fs');
const path = require('path');

// Overlays app.json with values that can only be decided at evaluation time.
module.exports = ({ config }) => {
  const googleServices = path.join(__dirname, 'google-services.json');
  const hasGoogleServices = fs.existsSync(googleServices);

  return {
    ...config,
    android: {
      ...config.android,
      // @react-native-firebase/app fails prebuild when this points at a missing file,
      // so FCM (AD-5 backup path) only wires up once the file is dropped in.
      ...(hasGoogleServices ? { googleServicesFile: './google-services.json' } : {}),
    },
    plugins: hasGoogleServices
      ? config.plugins
      : config.plugins.filter((p) => !String(p).startsWith('@react-native-firebase/')),
    extra: {
      ...config.extra,
      apiBaseUrl: process.env.EXPO_PUBLIC_API_URL || config.extra.apiBaseUrl,
    },
  };
};
