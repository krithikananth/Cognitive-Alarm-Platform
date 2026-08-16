const fs = require('fs');
const path = require('path');

const { withDangerousMod } = require('expo/config-plugins');

// The Notifee channel references the alarm tone as the raw resource `alarm`
// (src/alarm/channel.js). Prebuild regenerates android/ from scratch, so without
// this copy a `--clean` run silently drops the file and Android falls back to the
// default notification chirp — an alarm nobody wakes up to.
const SOURCE_RELATIVE_PATH = path.join('assets', 'alarm.mp3');
const RAW_RESOURCE_RELATIVE_DIR = path.join('app', 'src', 'main', 'res', 'raw');
const RAW_RESOURCE_FILENAME = 'alarm.mp3';

module.exports = function withAlarmSound(config) {
    return withDangerousMod(config, [
        'android',
        async (modConfig) => {
            const { projectRoot, platformProjectRoot } = modConfig.modRequest;
            const source = path.join(projectRoot, SOURCE_RELATIVE_PATH);

            if (!fs.existsSync(source)) {
                // Failing loudly here is the point: a skipped copy only shows up as a
                // too-quiet alarm on a real phone, long after the build passed.
                throw new Error(
                    `withAlarmSound: missing ${SOURCE_RELATIVE_PATH}. Add a looping alarm tone ` +
                    'there before running prebuild (see assets/README.md).'
                );
            }

            const rawDir = path.join(platformProjectRoot, RAW_RESOURCE_RELATIVE_DIR);
            fs.mkdirSync(rawDir, { recursive: true });
            fs.copyFileSync(source, path.join(rawDir, RAW_RESOURCE_FILENAME));

            return modConfig;
        },
    ]);
};

module.exports.SOURCE_RELATIVE_PATH = SOURCE_RELATIVE_PATH;
module.exports.RAW_RESOURCE_RELATIVE_DIR = RAW_RESOURCE_RELATIVE_DIR;
module.exports.RAW_RESOURCE_FILENAME = RAW_RESOURCE_FILENAME;
