// Alarm CRUD + GET /alarms/schedule + ring lifecycle calls (spec §4.1/§6, tasks 5-7).
import api from './client';

// The collection routes are mounted with a trailing slash; omitting it costs a
// 307 redirect that axios replays without the Authorization header on some hosts.
const COLLECTION = '/alarms/';

/** `GET /alarms/` — one page of the user's alarms. */
export async function listAlarms({ page = 1, perPage = 100, isActive } = {}) {
    const { data } = await api.get(COLLECTION, {
        params: {
            page,
            per_page: perPage,
            ...(isActive === undefined ? {} : { is_active: isActive }),
        },
    });
    return data;
}

/** `POST /alarms/` — returns the created alarm with its `next_trigger_at`. */
export async function createAlarm(payload) {
    const { data } = await api.post(COLLECTION, payload);
    return data;
}

/** `PUT /alarms/{id}` — partial update; only send the fields that changed. */
export async function updateAlarm(alarmId, payload) {
    const { data } = await api.put(`/alarms/${alarmId}`, payload);
    return data;
}

/** `DELETE /alarms/{id}` — 204, no body. */
export async function deleteAlarm(alarmId) {
    await api.delete(`/alarms/${alarmId}`);
}

/** `PATCH /alarms/{id}/toggle` — arming recomputes `next_trigger_at` server-side. */
export async function toggleAlarm(alarmId, isActive) {
    const { data } = await api.patch(`/alarms/${alarmId}/toggle`, {
        is_active: isActive,
    });
    return data;
}

/**
 * `GET /alarms/schedule` — every ring instant over the horizon.
 *
 * Distinct from `/alarms/upcoming`, which returns one stored `next_trigger_at`
 * per alarm. The expansion is what lets the device arm an OS-level alarm per
 * occurrence without re-implementing the recurrence rules (spec AD-4).
 */
export async function fetchSchedule({ days = 7 } = {}) {
    const { data } = await api.get('/alarms/schedule', { params: { days } });
    return data;
}

/**
 * `GET /alarms/{id}/challenge` — the next puzzle for a ringing alarm.
 *
 * The payload never carries `answer`; the session lives server-side, so the
 * device cannot be tricked into revealing it (spec §6.3).
 */
export async function fetchChallenge(alarmId) {
    const { data } = await api.get(`/alarms/${alarmId}/challenge`);
    return data;
}

/**
 * `POST /alarms/{id}/verify` — submit an answer.
 *
 * Three outcomes: 200 `step_complete` (more steps to go), 200 `dismissed`
 * (wake verified, alarm auto-dismissed), or 400 for a wrong answer or a
 * timeout — which axios raises, so callers must treat 400 as flow control
 * rather than as a failure.
 */
export async function verifyChallenge(alarmId, payload) {
    const { data } = await api.post(`/alarms/${alarmId}/verify`, payload);
    return data;
}

/** `POST /alarms/{id}/snooze` — 400 once `total_snoozes` reaches `snooze_limit`. */
export async function snoozeAlarm(alarmId) {
    const { data } = await api.post(`/alarms/${alarmId}/snooze`);
    return data;
}

/** `POST /alarms/{id}/fail-wake` — abandon the cycle; records an unverified wake. */
export async function failWake(alarmId) {
    const { data } = await api.post(`/alarms/${alarmId}/fail-wake`);
    return data;
}

