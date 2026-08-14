// Encrypted token storage (spec §5, AD-3). React Native has no cookie jar, so the
// bearer pair lives in SecureStore rather than the HttpOnly cookies the web app uses.
import * as SecureStore from 'expo-secure-store';

export const ACCESS_TOKEN_KEY = 'icap_access';
export const REFRESH_TOKEN_KEY = 'icap_refresh';

export async function getAccessToken() {
    return SecureStore.getItemAsync(ACCESS_TOKEN_KEY);
}

export async function getRefreshToken() {
    return SecureStore.getItemAsync(REFRESH_TOKEN_KEY);
}

/**
 * Persist a token pair from a login or refresh response.
 *
 * `/auth/refresh` rotates both tokens and revokes the access token it replaces,
 * so storing only the access token would leave the device holding a dead refresh
 * token and force a silent logout on the next expiry.
 */
export async function saveTokens({ access_token: accessToken, refresh_token: refreshToken }) {
    if (!accessToken) {
        throw new Error('Cannot store an empty access token');
    }
    await SecureStore.setItemAsync(ACCESS_TOKEN_KEY, accessToken);
    if (refreshToken) {
        await SecureStore.setItemAsync(REFRESH_TOKEN_KEY, refreshToken);
    }
}

export async function clearTokens() {
    await Promise.all([
        SecureStore.deleteItemAsync(ACCESS_TOKEN_KEY),
        SecureStore.deleteItemAsync(REFRESH_TOKEN_KEY),
    ]);
}
