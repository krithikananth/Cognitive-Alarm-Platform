const { withProjectBuildGradle } = require('expo/config-plugins');

// Notifee ships app.notifee:core as an AAR in a Maven repo inside node_modules and
// registers that repo on its own Gradle project. Gradle resolves a configuration
// using the *consuming* project's repositories, so :app never sees it and the
// build fails with "Could not find any matches for app.notifee:core:+".
const NOTIFEE_REPO =
  'maven { url "$rootDir/../node_modules/@notifee/react-native/android/libs" }';

const ALLPROJECTS_REPOSITORIES = /allprojects\s*\{\s*repositories\s*\{/;

module.exports = function withNotifeeRepository(config) {
  return withProjectBuildGradle(config, (gradleConfig) => {
    const { language, contents } = gradleConfig.modResults;

    if (language !== 'groovy') {
      throw new Error(
        `withNotifeeRepository expects a Groovy build.gradle, received "${language}".`
      );
    }
    if (contents.includes(NOTIFEE_REPO)) {
      return gradleConfig;
    }
    if (!ALLPROJECTS_REPOSITORIES.test(contents)) {
      throw new Error(
        'withNotifeeRepository could not find the allprojects repositories block.'
      );
    }

    gradleConfig.modResults.contents = contents.replace(
      ALLPROJECTS_REPOSITORIES,
      (match) => `${match}\n    ${NOTIFEE_REPO}`
    );
    return gradleConfig;
  });
};
