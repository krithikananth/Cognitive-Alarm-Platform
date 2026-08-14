// Device timezone detection + sync to PUT /users/profile (spec §5, task 4).

/**
 * The device's IANA timezone, falling back to UTC.
 *
 * Alarm times are stored as wall-clock in the profile timezone, so a wrong value
 * here does not merely mislabel a time — it rings the alarm at the wrong moment.
 * UTC matches the backend profile default.
 */
export function deviceTimezone() {
    try {
        return Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
    } catch {
        return 'UTC';
    }
}
