// login / register / refresh / logout (spec §5, task 4).
import api from './client';

/** `POST /auth/login` — returns `{access_token, refresh_token, token_type, user}`. */
export async function login(email, password) {
    const { data } = await api.post('/auth/login', { email, password });
    return data;
}

/** `POST /auth/register` — returns the created user; it does not issue tokens. */
export async function register({ email, username, password, fullName, timezone }) {
    const { data } = await api.post('/auth/register', {
        email,
        username,
        password,
        ...(fullName ? { full_name: fullName } : {}),
        ...(timezone ? { timezone } : {}),
    });
    return data;
}

/** `GET /auth/me` — also doubles as the session probe on cold start. */
export async function me() {
    const { data } = await api.get('/auth/me');
    return data;
}

/** `POST /auth/logout` — revokes the presented tokens server-side. */
export async function logout() {
    const { data } = await api.post('/auth/logout');
    return data;
}
