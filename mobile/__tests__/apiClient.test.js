/**
 * API client contract (spec §5).
 *
 * The refresh path is exercised through the real axios interceptor with a stubbed
 * adapter rather than by calling an exported helper, because the bug this guards
 * against — concurrent 401s each spending the refresh token — only exists in the
 * interceptor wiring.
 */
import axios from 'axios';

jest.mock('expo-constants', () => ({
    expoConfig: { extra: { apiBaseUrl: 'http://localhost:8000/api/v1' } },
}));

// jest.mock factories may only close over `mock`-prefixed names.
const mockStore = new Map();
jest.mock('expo-secure-store', () => ({
    getItemAsync: jest.fn(async (key) => (mockStore.has(key) ? mockStore.get(key) : null)),
    setItemAsync: jest.fn(async (key, value) => {
        mockStore.set(key, value);
    }),
    deleteItemAsync: jest.fn(async (key) => {
        mockStore.delete(key);
    }),
}));

jest.mock('../src/api/refreshClient', () => ({
    API_BASE_URL: 'http://localhost:8000/api/v1',
    REQUEST_TIMEOUT_MS: 15000,
    requestRefresh: jest.fn(),
}));

const {
    ACCESS_TOKEN_KEY,
    REFRESH_TOKEN_KEY,
    getAccessToken,
} = require('../src/api/tokens');

/** Build the rejection axios produces for an HTTP error status. */
function httpError(status, config, data = {}) {
    return new axios.AxiosError(
        `Request failed with status code ${status}`,
        'ERR_BAD_REQUEST',
        config,
        null,
        { status, data, headers: {}, config }
    );
}

/** Yield to the event loop until `predicate` holds. */
async function until(predicate, tries = 50) {
    for (let i = 0; i < tries; i += 1) {
        if (predicate()) return;
        await new Promise((resolve) => setImmediate(resolve));
    }
    throw new Error('Condition was never met');
}

let api;
let adapter;
let requestRefresh;
let readErrorDetail;
let setSessionExpiredHandler;

beforeEach(() => {
    // The client holds the in-flight refresh promise at module scope, so a test
    // that leaves one pending would hang every test after it.
    jest.resetModules();
    mockStore.clear();
    mockStore.set(ACCESS_TOKEN_KEY, 'stale-access');
    mockStore.set(REFRESH_TOKEN_KEY, 'refresh-1');

    ({ requestRefresh } = require('../src/api/refreshClient'));
    requestRefresh.mockReset();

    const client = require('../src/api/client');
    api = client.default;
    readErrorDetail = client.readErrorDetail;
    setSessionExpiredHandler = client.setSessionExpiredHandler;

    adapter = jest.fn();
    api.defaults.adapter = adapter;
});

describe('bearer auth', () => {
    it('attaches the stored access token', async () => {
        adapter.mockImplementation(async (config) => ({
            status: 200,
            data: { ok: true },
            headers: {},
            config,
        }));

        await api.get('/alarms/');

        expect(adapter.mock.calls[0][0].headers.Authorization).toBe('Bearer stale-access');
    });

    it('sends no Authorization header when signed out', async () => {
        mockStore.clear();
        adapter.mockImplementation(async (config) => ({
            status: 200,
            data: {},
            headers: {},
            config,
        }));

        await api.post('/auth/login', { email: 'a@b.c', password: 'x' });

        expect(adapter.mock.calls[0][0].headers.Authorization).toBeUndefined();
    });
});

describe('single-flight refresh', () => {
    it('refreshes once and replays the original request', async () => {
        adapter.mockImplementation(async (config) => {
            if (config.headers.Authorization === 'Bearer stale-access') {
                throw httpError(401, config);
            }
            return { status: 200, data: { ok: true }, headers: {}, config };
        });
        requestRefresh.mockResolvedValue({
            access_token: 'fresh-access',
            refresh_token: 'refresh-2',
        });

        const response = await api.get('/alarms/');

        expect(response.data).toEqual({ ok: true });
        expect(requestRefresh).toHaveBeenCalledTimes(1);
        expect(await getAccessToken()).toBe('fresh-access');
    });

    it('shares one refresh across concurrent 401s', async () => {
        // The load-bearing case: without the shared promise each rotation revokes
        // the token the previous one just issued, logging the user out mid-session.
        adapter.mockImplementation(async (config) => {
            if (config.headers.Authorization === 'Bearer stale-access') {
                throw httpError(401, config);
            }
            return { status: 200, data: { url: config.url }, headers: {}, config };
        });
        let resolveRefresh;
        requestRefresh.mockImplementation(
            () =>
                new Promise((resolve) => {
                    resolveRefresh = () =>
                        resolve({ access_token: 'fresh-access', refresh_token: 'refresh-2' });
                })
        );

        const pending = Promise.all([
            api.get('/alarms/'),
            api.get('/users/profile'),
            api.get('/auth/me'),
        ]);
        await until(() => requestRefresh.mock.calls.length > 0);
        resolveRefresh();
        const responses = await pending;

        expect(requestRefresh).toHaveBeenCalledTimes(1);
        expect(responses.map((r) => r.data.url)).toEqual([
            '/alarms/',
            '/users/profile',
            '/auth/me',
        ]);
    });

    it('rotates the refresh token, not just the access token', async () => {
        adapter.mockImplementation(async (config) => {
            if (config.headers.Authorization === 'Bearer stale-access') {
                throw httpError(401, config);
            }
            return { status: 200, data: {}, headers: {}, config };
        });
        requestRefresh.mockResolvedValue({
            access_token: 'fresh-access',
            refresh_token: 'refresh-2',
        });

        await api.get('/alarms/');

        expect(mockStore.get(REFRESH_TOKEN_KEY)).toBe('refresh-2');
    });

    it('clears the session when the refresh itself fails', async () => {
        adapter.mockImplementation(async (config) => {
            throw httpError(401, config);
        });
        requestRefresh.mockRejectedValue(new Error('revoked'));
        const onExpired = jest.fn();
        setSessionExpiredHandler(onExpired);

        await expect(api.get('/alarms/')).rejects.toBeTruthy();

        expect(onExpired).toHaveBeenCalledTimes(1);
        expect(mockStore.has(ACCESS_TOKEN_KEY)).toBe(false);
        expect(mockStore.has(REFRESH_TOKEN_KEY)).toBe(false);
    });

    it('does not retry a rejected login', async () => {
        // A 401 from /auth/login is a wrong password, not an expired session.
        adapter.mockImplementation(async (config) => {
            throw httpError(401, config, { detail: 'Invalid email or password' });
        });

        await expect(
            api.post('/auth/login', { email: 'a@b.c', password: 'nope' })
        ).rejects.toBeTruthy();

        expect(requestRefresh).not.toHaveBeenCalled();
        expect(adapter).toHaveBeenCalledTimes(1);
    });

    it('gives up after a single retry', async () => {
        adapter.mockImplementation(async (config) => {
            throw httpError(401, config);
        });
        requestRefresh.mockResolvedValue({
            access_token: 'fresh-access',
            refresh_token: 'refresh-2',
        });

        await expect(api.get('/alarms/')).rejects.toBeTruthy();

        expect(adapter).toHaveBeenCalledTimes(2);
    });
});

describe('readErrorDetail', () => {
    it('reads a plain HTTPException detail', () => {
        const error = { response: { status: 401, data: { detail: 'Invalid email or password' } } };
        expect(readErrorDetail(error)).toBe('Invalid email or password');
    });

    it('flattens a 422 validation list instead of rendering [object Object]', () => {
        const error = {
            response: {
                status: 422,
                data: {
                    detail: [
                        { msg: 'Password must contain at least one uppercase letter' },
                        { msg: 'String should match pattern' },
                    ],
                },
            },
        };
        expect(readErrorDetail(error)).toBe(
            'Password must contain at least one uppercase letter\nString should match pattern'
        );
    });

    it('surfaces the lockout wait from Retry-After', () => {
        const error = {
            response: { status: 429, data: {}, headers: { 'retry-after': '42' } },
        };
        expect(readErrorDetail(error)).toBe('Too many attempts. Try again in 42 seconds.');
    });

    it('explains an unreachable server', () => {
        expect(readErrorDetail({ message: 'Network Error' })).toMatch(/Cannot reach the server/);
    });

    it('falls back when the server sends nothing useful', () => {
        expect(readErrorDetail({ response: { status: 500, data: {} } }, 'Fallback.')).toBe('Fallback.');
    });
});
