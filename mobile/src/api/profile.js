// User profile + timezone sync (spec §5, task 10).
import api from './client';

/** `PUT /users/profile` — accepts `full_name`, `username` and `timezone`. */
export async function updateProfile(fields) {
    const { data } = await api.put('/users/profile', fields);
    return data;
}

/** Push the device timezone up so server-side trigger times match the phone. */
export async function syncTimezone(timezone) {
    return updateProfile({ timezone });
}
