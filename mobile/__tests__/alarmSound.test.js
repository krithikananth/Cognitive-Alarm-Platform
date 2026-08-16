/** Alarm tone asset -> android res/raw copy (spec §6.1). */
const fs = require('fs');
const os = require('os');
const path = require('path');

const appJson = require('../app.json');
const appConfig = require('../app.config');
const withAlarmSound = require('../plugins/withAlarmSound');

const {
    RAW_RESOURCE_FILENAME,
    RAW_RESOURCE_RELATIVE_DIR,
    SOURCE_RELATIVE_PATH,
} = withAlarmSound;

const MOBILE_ROOT = path.join(__dirname, '..');

/** Run the plugin's android dangerous mod against a throwaway project tree. */
async function runMod({ projectRoot, platformProjectRoot }) {
    const config = withAlarmSound({ name: 'icap', slug: 'icap' });
    const mod = config.mods.android.dangerous;
    return mod({
        ...config,
        modRequest: {
            projectRoot,
            platformProjectRoot,
            platform: 'android',
            modName: 'dangerous',
        },
        modResults: {},
    });
}

function makeTempProject({ withAsset }) {
    const projectRoot = fs.mkdtempSync(path.join(os.tmpdir(), 'icap-alarm-sound-'));
    const platformProjectRoot = path.join(projectRoot, 'android');
    fs.mkdirSync(platformProjectRoot, { recursive: true });
    if (withAsset) {
        fs.mkdirSync(path.join(projectRoot, 'assets'), { recursive: true });
        fs.writeFileSync(path.join(projectRoot, SOURCE_RELATIVE_PATH), 'fake-audio');
    }
    return { projectRoot, platformProjectRoot };
}

describe('the committed asset', () => {
    it('exists, so a prebuild cannot fall back to the default chirp', () => {
        expect(fs.existsSync(path.join(MOBILE_ROOT, SOURCE_RELATIVE_PATH))).toBe(true);
    });

    it('is named for the raw resource the channel asks for', () => {
        // Android raw resource names allow only [a-z0-9_]; `channel.js` uses 'alarm'.
        expect(RAW_RESOURCE_FILENAME).toBe('alarm.mp3');
        expect(path.parse(RAW_RESOURCE_FILENAME).name).toMatch(/^[a-z][a-z0-9_]*$/);
    });
});

describe('plugin registration', () => {
    it('runs on every prebuild', () => {
        const resolved = appConfig({ config: appJson.expo });
        expect(resolved.plugins).toContain('./plugins/withAlarmSound');
    });
});

describe('withAlarmSound', () => {
    let temp;

    afterEach(() => {
        if (temp) fs.rmSync(temp.projectRoot, { recursive: true, force: true });
        temp = null;
    });

    it('copies the tone into res/raw, creating the folder', async () => {
        temp = makeTempProject({ withAsset: true });

        await runMod(temp);

        const copied = path.join(
            temp.platformProjectRoot,
            RAW_RESOURCE_RELATIVE_DIR,
            RAW_RESOURCE_FILENAME
        );
        expect(fs.existsSync(copied)).toBe(true);
        expect(fs.readFileSync(copied, 'utf8')).toBe('fake-audio');
    });

    it('overwrites a stale copy from an earlier prebuild', async () => {
        temp = makeTempProject({ withAsset: true });
        const rawDir = path.join(temp.platformProjectRoot, RAW_RESOURCE_RELATIVE_DIR);
        fs.mkdirSync(rawDir, { recursive: true });
        fs.writeFileSync(path.join(rawDir, RAW_RESOURCE_FILENAME), 'previous-tone');

        await runMod(temp);

        expect(fs.readFileSync(path.join(rawDir, RAW_RESOURCE_FILENAME), 'utf8')).toBe(
            'fake-audio'
        );
    });

    it('fails the build when the asset is missing rather than shipping a silent alarm', async () => {
        temp = makeTempProject({ withAsset: false });

        await expect(runMod(temp)).rejects.toThrow(/missing .*alarm\.mp3/);
    });
});
