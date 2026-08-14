/**
 * Integration guard: every declared API method must have a production caller.
 *
 * An audit found ten `api.js` methods that existed only as dead client code —
 * the endpoint was built, the wrapper was written, and nothing ever called it,
 * so the feature silently did not exist for users. A unit test on the wrapper
 * itself cannot catch that: it passes whether or not the app uses it.
 *
 * This walks the real source tree instead, so re-orphaning any of these
 * methods fails the build rather than quietly shipping.
 */
const fs = require('fs');
const path = require('path');

const SRC_DIR = path.join(__dirname, '..');
const API_FILE = path.join(SRC_DIR, 'services', 'api.js');

function collectSourceFiles(dir) {
    const out = [];
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
        const full = path.join(dir, entry.name);
        if (entry.isDirectory()) {
            out.push(...collectSourceFiles(full));
            continue;
        }
        if (!/\.(js|jsx)$/.test(entry.name)) continue;
        // Declarations do not count as usage, and neither does a test.
        if (full === API_FILE) continue;
        if (/\.test\.(js|jsx)$/.test(entry.name)) continue;
        out.push(full);
    }
    return out;
}

const PRODUCTION_SOURCES = collectSourceFiles(SRC_DIR).map((file) => ({
    file: path.relative(SRC_DIR, file),
    text: fs.readFileSync(file, 'utf8'),
}));

/** Previously orphaned methods, with the surface that now uses each one. */
const REQUIRED_CALL_SITES = [
    ['userAPI.updateGoals', 'pages/Profile.jsx'],
    ['authAPI.logoutAll', 'store/authStore.js'],
    ['alarmAPI.getAlarmChallengeHistory', 'pages/AlarmManager.jsx'],
    ['recommendationAPI.getSleep', 'pages/Recommendations.jsx'],
    ['recommendationAPI.getWake', 'pages/Recommendations.jsx'],
    ['recommendationAPI.getProductivity', 'pages/Recommendations.jsx'],
    ['analyticsAPI.getSnoozePattern', 'pages/UserDashboard.jsx'],
    ['analyticsAPI.getSleepAdherence', 'pages/UserDashboard.jsx'],
    ['analyticsAPI.getWeeklyTrends', 'pages/UserDashboard.jsx'],
    ['analyticsAPI.postEventsBatch', 'services/analyticsTracker.js'],
    ['systemAPI.getMetrics', 'pages/AdminDashboard.jsx'],
    ['adminAPI.listCoachAssignments', 'components/AdminCoachAssignments.jsx'],
    ['adminAPI.createCoachAssignment', 'components/AdminCoachAssignments.jsx'],
    ['adminAPI.removeCoachAssignment', 'components/AdminCoachAssignments.jsx'],
    ['systemAPI.getStatus', 'components/Layout.jsx'],
    ['systemAPI.getAlerts', 'components/AdminObservability.jsx'],
    ['systemAPI.getLogging', 'components/AdminObservability.jsx'],
    ['alarmAPI.getSnoozeHistory', 'components/analytics/ActivityHealthPanel.jsx'],
    ['alarmAPI.getChallengeLogHealth', 'components/analytics/ActivityHealthPanel.jsx'],
    ['alarmAPI.getLearningProfile', 'pages/Analytics.jsx'],
    ['analyticsAPI.listEvents', 'components/analytics/ActivityHealthPanel.jsx'],
    ['profileAPI.getMe', 'components/profile/HabitScoreCard.jsx'],
    ['profileAPI.getHabitScore', 'components/profile/HabitScoreCard.jsx'],
    ['profileAPI.updateHabits', 'components/profile/HabitScoreCard.jsx'],
    ['userAPI.getPreferences', 'components/profile/HabitScoreCard.jsx'],
    ['adminAPI.getUser', 'components/AdminUserManagement.jsx'],
    ['adminAPI.getUserDetail', 'components/AdminUserManagement.jsx'],
    ['alarmAPI.dismiss', 'store/activeAlarmStore.js'],
    ['alarmAPI.getWakefulness', 'components/analytics/ActivityHealthPanel.jsx'],
    ['analyticsAPI.getBehavioral', 'components/analytics/ActivityHealthPanel.jsx'],
    ['analyticsAPI.getSummary', 'components/analytics/ActivityHealthPanel.jsx'],
    ['analyticsAPI.getWakeConsistency', 'components/analytics/ActivityHealthPanel.jsx'],
    ['analyticsAPI.getSleepPatterns', 'pages/UserDashboard.jsx'],
    ['analyticsAPI.getProductivityCorrelation', 'pages/UserDashboard.jsx'],
    ['coachAPI.getSleepTrends', 'hooks/useCoachDashboard.js'],
    ['coachAPI.getWakeConsistency', 'hooks/useCoachDashboard.js'],
    ['coachAPI.getHabitScore', 'hooks/useCoachDashboard.js'],
    ['authAPI.updateMe', 'pages/Profile.jsx'],
];

/**
 * Backend routes this client deliberately does not call, and why.
 *
 * Every entry is either unreachable from axios by design or a second, stricter
 * surface whose canonical twin the app already uses. The overlapping ones are
 * held to their documented contract by backend/tests/test_route_aliases.py, so
 * they cannot quietly drift into being genuinely dead.
 */
const UNCALLED_ROUTES = {
    'GET /': 'service banner, not an app feature',
    'GET /health': 'infrastructure probe',
    'GET /api/v1/auth/oauth/google': 'entered via window.location redirect in pages/Login.jsx',
    'GET /api/v1/auth/oauth/google/callback': 'the provider redirects the browser here',
    'POST /api/v1/auth/token': 'OAuth2 password-form alias used by API clients, not the SPA',
    'POST /api/v1/auth/refresh': 'called by the 401 interceptor with a bare axios instance, which must bypass this client',
    'POST /api/v1/system/client-errors': 'reported with fetch(keepalive) in services/errorReporting.js',
    'GET /api/v1/system/metrics/prometheus': 'scrape target for the monitoring stack',
    'GET /api/v1/users': 'admin listing superseded by /admin/users; same population pinned by test_route_aliases.py',
    'GET /api/v1/alarms/schedule': 'native-client only: the Android app expands occurrences to arm OS-level alarms, while the web app rings from the service-worker push',
    'POST /api/v1/alarms/{alarm_id}/offline-wake': 'native-client only: flushes dismissals the Android app recorded with no connectivity; the browser is never the offline ring surface',
    'PUT /api/v1/profiles/me': 'bulk profile write; every field is reachable through the /users/profile* routes the app uses',
    'PATCH /api/v1/profiles/me/goals': 'typed List[str] variant of PUT /users/profile/goals',
    'PATCH /api/v1/profiles/me/sleep-schedule': 'typed variant of PUT /users/profile/sleep-schedule',
};

/**
 * Every `*API` object exported by api.js, with its declared method names.
 *
 * Parsed from the source rather than imported so the check sees what is
 * actually written in the file, including methods nothing imports.
 */
function declaredApiMethods() {
    const apiText = fs.readFileSync(API_FILE, 'utf8');
    const objects = apiText.matchAll(/export const (\w+API)\s*=\s*\{([\s\S]*?)\n\};/g);
    const declared = [];
    for (const [, objectName, body] of objects) {
        for (const [, method] of body.matchAll(/^ {2}(\w+)\s*:/gm)) {
            declared.push(`${objectName}.${method}`);
        }
    }
    return declared;
}

function callersOf(qualifiedName) {
    return PRODUCTION_SOURCES.filter((source) =>
        source.text.includes(`${qualifiedName}(`)
    ).map((source) => source.file.replace(/\\/g, '/'));
}

describe('API methods are wired into the app', () => {
    test.each(REQUIRED_CALL_SITES)(
        '%s is called from %s',
        (qualifiedName, expectedFile) => {
            const callers = callersOf(qualifiedName);
            expect(callers.length).toBeGreaterThan(0);
            expect(callers).toContain(expectedFile);
        }
    );

    it('declares every method the call sites rely on', () => {
        const apiText = fs.readFileSync(API_FILE, 'utf8');
        for (const [qualifiedName] of REQUIRED_CALL_SITES) {
            const method = qualifiedName.split('.')[1];
            expect(apiText).toContain(`${method}:`);
        }
    });
});

describe('the whole API client surface is reachable', () => {
    // The hard-coded list above pins *where* known-fragile methods are used.
    // This covers everything else, so a newly added wrapper cannot ship dead.
    it('has a production caller for every declared method', () => {
        const orphans = declaredApiMethods().filter(
            (qualifiedName) => callersOf(qualifiedName).length === 0
        );
        expect(orphans).toEqual([]);
    });

    it('checks a realistic number of methods', () => {
        // Guards the parser itself: a regex that silently matched nothing
        // would make the orphan check above vacuously pass.
        expect(declaredApiMethods().length).toBeGreaterThan(90);
    });
});

describe('every backend route is accounted for', () => {
    // The reverse direction: the checks above prove no client method is dead,
    // this proves no *endpoint* is. Without it a route can ship with no way to
    // reach it from the product, which is exactly how the coach-assignment
    // feature stayed invisible despite its API being complete.
    const SNAPSHOT = path.join(
        SRC_DIR, '..', '..', 'backend', 'tests', 'api_contract_snapshot.json'
    );

    function backendRoutes() {
        const { routes } = JSON.parse(fs.readFileSync(SNAPSHOT, 'utf8'));
        return Object.keys(routes);
    }

    /** Route templates the client calls, normalised to the backend's form. */
    function calledRoutes() {
        const apiText = fs.readFileSync(API_FILE, 'utf8');
        const called = new Set();
        const calls = apiText.matchAll(
            /api\.(get|post|put|patch|delete)\(\s*[`'"]([^`'"]+)[`'"]/g
        );
        for (const [, method, rawPath] of calls) {
            let route = `/api/v1${rawPath}`.replace(/\$\{[^}]*\}/g, '{}');
            if (route.length > 1 && route.endsWith('/')) route = route.slice(0, -1);
            called.add(`${method.toUpperCase()} ${route}`);
        }
        return called;
    }

    const normalise = (route) => {
        const [method, rawPath] = route.split(' ');
        let p = rawPath.replace(/\{[^}]*\}/g, '{}');
        if (p.length > 1 && p.endsWith('/')) p = p.slice(0, -1);
        return `${method} ${p}`;
    };

    it('has a client method for every route that is not explicitly exempt', () => {
        const called = calledRoutes();
        const exempt = new Set(Object.keys(UNCALLED_ROUTES).map(normalise));
        const unreachable = backendRoutes()
            .map(normalise)
            .filter((route) => !called.has(route) && !exempt.has(route));
        expect(unreachable).toEqual([]);
    });

    it('has no stale exemptions', () => {
        // An exemption for a route that no longer exists hides the next gap.
        const known = new Set(backendRoutes().map(normalise));
        const stale = Object.keys(UNCALLED_ROUTES)
            .map(normalise)
            .filter((route) => !known.has(route));
        expect(stale).toEqual([]);
    });

    it('justifies every exemption', () => {
        const unexplained = Object.entries(UNCALLED_ROUTES)
            .filter(([, reason]) => !reason || reason.trim().length < 15)
            .map(([route]) => route);
        expect(unexplained).toEqual([]);
    });

    it('reads a realistic number of backend routes', () => {
        expect(backendRoutes().length).toBeGreaterThan(100);
    });
});

describe('orphaned coach panels are gone', () => {
    const REMOVED = [
        'components/wellness/PersonalizedCoaching.jsx',
        'components/wellness/ProductivityAnalytics.jsx',
        'components/wellness/CoachingPanels.jsx',
        'components/wellness/DailyPlan.jsx',
    ];

    test.each(REMOVED)('%s no longer exists', (relative) => {
        expect(fs.existsSync(path.join(SRC_DIR, relative))).toBe(false);
    });

    it('leaves no dangling imports behind', () => {
        const names = ['PersonalizedCoaching', 'ProductivityAnalytics', 'CoachingPanels', 'DailyPlan'];
        const offenders = PRODUCTION_SOURCES.filter((source) =>
            names.some((name) => source.text.includes(`from './${name}'`)
                || source.text.includes(`wellness/${name}'`))
        );
        expect(offenders.map((o) => o.file)).toEqual([]);
    });
});
