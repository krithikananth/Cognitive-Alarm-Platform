/**
 * Timezone rendering tests — coach views must use the client's stored zone.
 */
import { formatInTimeZone } from './timeFormat';

const INSTANT = '2026-08-08T02:30:00+00:00';

describe('formatInTimeZone', () => {
  test('renders an instant in the client stored timezone, not UTC', () => {
    const options = { hour: '2-digit', minute: '2-digit', hour12: false };

    const utc = formatInTimeZone(INSTANT, 'UTC', options);
    const tokyo = formatInTimeZone(INSTANT, 'Asia/Tokyo', options);
    const newYork = formatInTimeZone(INSTANT, 'America/New_York', options);

    expect(utc).toBe('02:30');
    expect(tokyo).toBe('11:30');
    expect(newYork).toBe('22:30');
  });

  test('falls back to UTC for an unknown timezone instead of throwing', () => {
    const options = { hour: '2-digit', minute: '2-digit', hour12: false };
    expect(formatInTimeZone(INSTANT, 'Not/AZone', options)).toBe('02:30');
  });

  test('defaults to UTC when the client has no stored timezone', () => {
    const options = { hour: '2-digit', minute: '2-digit', hour12: false };
    expect(formatInTimeZone(INSTANT, null, options)).toBe('02:30');
  });

  test('returns null for missing or unparsable values', () => {
    expect(formatInTimeZone(null, 'UTC')).toBeNull();
    expect(formatInTimeZone(undefined, 'UTC')).toBeNull();
    expect(formatInTimeZone('', 'UTC')).toBeNull();
    expect(formatInTimeZone('not-a-date', 'UTC')).toBeNull();
  });
});
