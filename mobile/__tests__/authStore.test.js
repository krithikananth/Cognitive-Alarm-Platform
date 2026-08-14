/** Auth store behaviour (spec §5): token persistence, timezone sync, logout. */
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

jest.mock('../src/api/client', () => ({
    __esModule: true,
    default: {},
    setSessionExpiredHandler: jest.fn(),
    readErrorDetail: jest.fn((error, fallback) => error?.detail || fallback),
}));

jest.mock('../src/api/auth', () => ({
    login: jest.fn(),
    register: jest.fn(),
    me: jest.fn(),
    logout: jest.fn(),
}));

jest.mock('../src/api/profile', () => ({
    syncTimezone: jest.fn(),
    updateProfile: jest.fn(),
}));

jest.mock('../src/utils/timezone', () => ({
    deviceTimezone: jest.fn(() => 'Asia/Kolkata'),
}));

const authApi = require('../src/api/auth');
const { syncTimezone } = require('../src/api/profile');
const { ACCESS_TOKEN_KEY, REFRESH_TOKEN_KEY } = require('../src/api/tokens');
const useAuthStore = require('../src/store/authStore').default;
const { AUTH_STATUS } = require('../src/store/authStore');

const SESSION = {
    access_token: 'access-1',
    refresh_token: 'refresh-1',
    token_type: 'bearer',
    user: { id: 7, email: 'a@b.c', username: 'sleepy', role: 'user' },
};

beforeEach(() => {
    mockStore.clear();
    jest.clearAllMocks();
    syncTimezone.mockResolvedValue({});
    useAuthStore.setState({
        status: AUTH_STATUS.UNKNOWN,
        user: null,
        error: null,
        submitting: false,
    });
});

describe('login', () => {
    it('stores both tokens and the user', async () => {
        authApi.login.mockResolvedValue(SESSION);

        const ok = await useAuthStore.getState().login('a@b.c', 'Passw0rd');

        expect(ok).toBe(true);
        expect(mockStore.get(ACCESS_TOKEN_KEY)).toBe('access-1');
        expect(mockStore.get(REFRESH_TOKEN_KEY)).toBe('refresh-1');
        expect(useAuthStore.getState().status).toBe(AUTH_STATUS.AUTHENTICATED);
        expect(useAuthStore.getState().user.id).toBe(7);
    });

    it('syncs the device timezone', async () => {
        authApi.login.mockResolvedValue(SESSION);

        await useAuthStore.getState().login('a@b.c', 'Passw0rd');

        expect(syncTimezone).toHaveBeenCalledWith('Asia/Kolkata');
    });

    it('keeps the session when the timezone sync fails', async () => {
        // A profile write must never be able to undo a successful sign-in.
        authApi.login.mockResolvedValue(SESSION);
        syncTimezone.mockRejectedValue(new Error('offline'));

        const ok = await useAuthStore.getState().login('a@b.c', 'Passw0rd');

        expect(ok).toBe(true);
        expect(useAuthStore.getState().status).toBe(AUTH_STATUS.AUTHENTICATED);
    });

    it('surfaces the server message and stores no tokens on failure', async () => {
        authApi.login.mockRejectedValue({ detail: 'Invalid email or password' });

        const ok = await useAuthStore.getState().login('a@b.c', 'wrong');

        expect(ok).toBe(false);
        expect(useAuthStore.getState().error).toBe('Invalid email or password');
        expect(useAuthStore.getState().status).toBe(AUTH_STATUS.UNKNOWN);
        expect(mockStore.size).toBe(0);
        expect(useAuthStore.getState().submitting).toBe(false);
    });
});

describe('register', () => {
    it('signs in after creating the account', async () => {
        // /auth/register returns a user, not tokens, so the store must follow up.
        authApi.register.mockResolvedValue({ id: 7 });
        authApi.login.mockResolvedValue(SESSION);

        const ok = await useAuthStore.getState().register({
            email: 'a@b.c',
            username: 'sleepy',
            password: 'Passw0rd',
        });

        expect(ok).toBe(true);
        expect(authApi.login).toHaveBeenCalledWith('a@b.c', 'Passw0rd');
        expect(useAuthStore.getState().status).toBe(AUTH_STATUS.AUTHENTICATED);
    });

    it('does not attempt a login when registration is rejected', async () => {
        authApi.register.mockRejectedValue({ detail: 'Email already registered' });

        const ok = await useAuthStore.getState().register({
            email: 'a@b.c',
            username: 'sleepy',
            password: 'Passw0rd',
        });

        expect(ok).toBe(false);
        expect(authApi.login).not.toHaveBeenCalled();
        expect(useAuthStore.getState().error).toBe('Email already registered');
    });
});

describe('restore', () => {
    it('reports anonymous when nothing is stored', async () => {
        await useAuthStore.getState().restore();

        expect(useAuthStore.getState().status).toBe(AUTH_STATUS.ANONYMOUS);
        expect(authApi.me).not.toHaveBeenCalled();
    });

    it('revives a stored session', async () => {
        mockStore.set(ACCESS_TOKEN_KEY, 'access-1');
        authApi.me.mockResolvedValue(SESSION.user);

        await useAuthStore.getState().restore();

        expect(useAuthStore.getState().status).toBe(AUTH_STATUS.AUTHENTICATED);
    });

    it('discards tokens the server no longer accepts', async () => {
        mockStore.set(ACCESS_TOKEN_KEY, 'access-1');
        mockStore.set(REFRESH_TOKEN_KEY, 'refresh-1');
        authApi.me.mockRejectedValue(new Error('401'));

        await useAuthStore.getState().restore();

        expect(useAuthStore.getState().status).toBe(AUTH_STATUS.ANONYMOUS);
        expect(mockStore.size).toBe(0);
    });
});

describe('logout', () => {
    it('clears tokens and state', async () => {
        mockStore.set(ACCESS_TOKEN_KEY, 'access-1');
        mockStore.set(REFRESH_TOKEN_KEY, 'refresh-1');
        authApi.logout.mockResolvedValue({});
        useAuthStore.setState({ status: AUTH_STATUS.AUTHENTICATED, user: SESSION.user });

        await useAuthStore.getState().logout();

        expect(mockStore.size).toBe(0);
        expect(useAuthStore.getState().status).toBe(AUTH_STATUS.ANONYMOUS);
        expect(useAuthStore.getState().user).toBeNull();
    });

    it('signs out locally even when the server is unreachable', async () => {
        mockStore.set(ACCESS_TOKEN_KEY, 'access-1');
        authApi.logout.mockRejectedValue(new Error('Network Error'));
        useAuthStore.setState({ status: AUTH_STATUS.AUTHENTICATED, user: SESSION.user });

        await useAuthStore.getState().logout();

        expect(mockStore.size).toBe(0);
        expect(useAuthStore.getState().status).toBe(AUTH_STATUS.ANONYMOUS);
    });
});

describe('expired session', () => {
    it('drops to anonymous with an explanation', () => {
        useAuthStore.setState({ status: AUTH_STATUS.AUTHENTICATED, user: SESSION.user });

        useAuthStore.getState().handleSessionExpired();

        expect(useAuthStore.getState().status).toBe(AUTH_STATUS.ANONYMOUS);
        expect(useAuthStore.getState().error).toMatch(/expired/i);
    });
});
