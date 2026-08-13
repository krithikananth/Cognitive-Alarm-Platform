const path = require('path');
const { defineConfig, devices } = require('@playwright/test');

const REPO_ROOT = path.resolve(__dirname, '..');
const BACKEND_DIR = path.join(REPO_ROOT, 'backend');
const WORK_DIR = path.join(BACKEND_DIR, '.e2e');

const BACKEND_PORT = process.env.E2E_BACKEND_PORT || '8100';
const FRONTEND_PORT = process.env.E2E_FRONTEND_PORT || '3100';

// Both servers must answer on the SAME hostname: the session cookies are
// SameSite=Lax, and `localhost` and `127.0.0.1` count as different sites, so
// mixing them would silently drop every authenticated request.
const BACKEND_ORIGIN = `http://localhost:${BACKEND_PORT}`;
const FRONTEND_ORIGIN = `http://localhost:${FRONTEND_PORT}`;

const backendEnv = {
    ...process.env,
    DATABASE_URL: `sqlite:///${path.join(WORK_DIR, 'e2e.db').replace(/\\/g, '/')}`,
    ENVIRONMENT: 'development',
    E2E_BACKEND_PORT: BACKEND_PORT,
    // pydantic-settings JSON-decodes list fields before the app's own validator
    // runs, so a bare origin string would abort start-up.
    CORS_ORIGINS: JSON.stringify([FRONTEND_ORIGIN]),
    FRONTEND_URL: FRONTEND_ORIGIN,
    // The suite reads verification / reset links out of this log directory,
    // which is how it stands in for a real mailbox.
    LOG_TO_FILE: 'true',
    LOG_DIR: path.join(WORK_DIR, 'logs'),
    LOG_LEVEL: 'INFO',
    LOG_FORMAT: 'json',
    // Background senders and outbound AI calls would make assertions racy.
    ALARM_DISPATCH_ENABLED: 'false',
    AI_CHALLENGE_ENABLED: 'false',
    RATE_LIMIT_ENABLED: 'false',
    REDIS_ENABLED: 'false',
};

module.exports = defineConfig({
    testDir: './e2e/specs',
    outputDir: './e2e/.artifacts',
    // Journeys share one backend database, so they run one at a time.
    workers: 1,
    fullyParallel: false,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 1 : 0,
    timeout: 90_000,
    expect: { timeout: 15_000 },
    reporter: [['list'], ['html', { outputFolder: './e2e/.report', open: 'never' }]],

    use: {
        baseURL: FRONTEND_ORIGIN,
        trace: 'retain-on-failure',
        screenshot: 'only-on-failure',
        video: 'off',
        actionTimeout: 20_000,
        navigationTimeout: 45_000,
    },

    projects: [
        {
            name: 'chromium',
            use: {
                ...devices['Desktop Chrome'],
                viewport: { width: 1440, height: 900 },
                // The alarm modal starts an AudioContext the moment it opens.
                launchOptions: { args: ['--autoplay-policy=no-user-gesture-required'] },
            },
        },
    ],

    webServer: [
        {
            command: 'python scripts/e2e_backend.py',
            cwd: BACKEND_DIR,
            url: `${BACKEND_ORIGIN}/health`,
            env: backendEnv,
            reuseExistingServer: false,
            timeout: 180_000,
            // The backend logs every request as JSON; echoing it would bury the
            // test report. Failures still surface on stderr.
            stdout: 'ignore',
            stderr: 'pipe',
        },
        {
            command: 'npm start',
            cwd: __dirname,
            url: FRONTEND_ORIGIN,
            env: {
                ...process.env,
                PORT: FRONTEND_PORT,
                BROWSER: 'none',
                REACT_APP_API_URL: `${BACKEND_ORIGIN}/api/v1`,
                // A dev-server overlay would swallow clicks meant for the app.
                FAST_REFRESH: 'false',
            },
            reuseExistingServer: false,
            timeout: 300_000,
            stdout: 'ignore',
            stderr: 'pipe',
        },
    ],
});
