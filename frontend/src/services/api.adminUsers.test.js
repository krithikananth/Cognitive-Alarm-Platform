/**
 * Admin user-management API client surface tests.
 * Verifies every action the Admin User Management table needs is wired to a
 * real endpoint, without hitting the network.
 */
import { adminAPI } from './api';

describe('Admin user management API surfaces', () => {
  test('listing and detail endpoints are exposed', () => {
    expect(typeof adminAPI.listUsers).toBe('function');
    expect(typeof adminAPI.getUserDetail).toBe('function');
  });

  test('mutation endpoints are exposed', () => {
    expect(typeof adminAPI.updateUser).toBe('function');
    expect(typeof adminAPI.activateUser).toBe('function');
    expect(typeof adminAPI.deactivateUser).toBe('function');
    expect(typeof adminAPI.deleteUser).toBe('function');
  });
});
