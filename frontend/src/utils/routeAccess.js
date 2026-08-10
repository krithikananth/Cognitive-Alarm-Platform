/**
 * Centralized role constants and route access policy.
 *
 * Client-side checks keep users out of pages they can never use; the backend
 * role dependencies remain the actual security boundary.
 */

/** Role values mirror the backend UserRole enum (lowercase strings). */
export const ROLES = {
  USER: 'user',
  WELLNESS_COACH: 'wellness_coach',
  ADMIN: 'admin',
};

/** Path an unauthorized (but authenticated) user is sent to. */
export const ACCESS_DENIED_PATH = '/access-denied';

/** Landing route for a role: admins to the panel, coaches to their roster. */
export function homePathForRole(role) {
  if (role === ROLES.ADMIN) return '/admin';
  if (role === ROLES.WELLNESS_COACH) return '/wellness';
  return '/dashboard';
}

/** True when `role` is one of `allowedRoles`. Missing/unknown roles are denied. */
export function hasRouteAccess(role, allowedRoles) {
  if (!Array.isArray(allowedRoles) || allowedRoles.length === 0) return false;
  return allowedRoles.includes(role);
}
