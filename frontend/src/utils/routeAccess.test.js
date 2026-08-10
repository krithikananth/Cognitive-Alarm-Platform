/**
 * Role-based route policy tests — allowed/denied matrix and redirect targets.
 */
import { ROLES, homePathForRole, hasRouteAccess } from './routeAccess';

const ADMIN_ONLY = [ROLES.ADMIN];
const COACH_ONLY = [ROLES.WELLNESS_COACH];

describe('homePathForRole', () => {
  test('maps each role to its landing route', () => {
    expect(homePathForRole(ROLES.ADMIN)).toBe('/admin');
    expect(homePathForRole(ROLES.WELLNESS_COACH)).toBe('/wellness');
    expect(homePathForRole(ROLES.USER)).toBe('/dashboard');
  });

  test('falls back to the user dashboard for missing/unknown roles', () => {
    expect(homePathForRole(undefined)).toBe('/dashboard');
    expect(homePathForRole(null)).toBe('/dashboard');
    expect(homePathForRole('superuser')).toBe('/dashboard');
  });
});

describe('admin-only routes', () => {
  test('only admins are allowed', () => {
    expect(hasRouteAccess(ROLES.ADMIN, ADMIN_ONLY)).toBe(true);
    expect(hasRouteAccess(ROLES.WELLNESS_COACH, ADMIN_ONLY)).toBe(false);
    expect(hasRouteAccess(ROLES.USER, ADMIN_ONLY)).toBe(false);
  });

  test('missing and unknown roles are denied', () => {
    expect(hasRouteAccess(undefined, ADMIN_ONLY)).toBe(false);
    expect(hasRouteAccess(null, ADMIN_ONLY)).toBe(false);
    expect(hasRouteAccess('superuser', ADMIN_ONLY)).toBe(false);
  });
});

describe('wellness-coach-only routes', () => {
  test('only wellness coaches are allowed', () => {
    expect(hasRouteAccess(ROLES.WELLNESS_COACH, COACH_ONLY)).toBe(true);
    expect(hasRouteAccess(ROLES.ADMIN, COACH_ONLY)).toBe(false);
    expect(hasRouteAccess(ROLES.USER, COACH_ONLY)).toBe(false);
  });

  test('missing and unknown roles are denied', () => {
    expect(hasRouteAccess(undefined, COACH_ONLY)).toBe(false);
    expect(hasRouteAccess(null, COACH_ONLY)).toBe(false);
    expect(hasRouteAccess('superuser', COACH_ONLY)).toBe(false);
  });
});

describe('policy guardrails', () => {
  test('an empty or invalid allow-list denies everyone', () => {
    expect(hasRouteAccess(ROLES.ADMIN, [])).toBe(false);
    expect(hasRouteAccess(ROLES.ADMIN, undefined)).toBe(false);
  });
});
