// The refresh call deliberately lives on its own bare axios instance: routing it
// through the shared client would re-enter the 401 interceptor and recurse.
import axios from 'axios';
import Constants from 'expo-constants';

export const API_BASE_URL =
    Constants.expoConfig?.extra?.apiBaseUrl ?? 'http://localhost:8000/api/v1';

export const REQUEST_TIMEOUT_MS = 15000;

const refreshClient = axios.create({
    baseURL: API_BASE_URL,
    headers: { 'Content-Type': 'application/json' },
    timeout: REQUEST_TIMEOUT_MS,
});

export async function requestRefresh(refreshToken) {
    const { data } = await refreshClient.post('/auth/refresh', {
        refresh_token: refreshToken,
    });
    return data;
}

export default refreshClient;
