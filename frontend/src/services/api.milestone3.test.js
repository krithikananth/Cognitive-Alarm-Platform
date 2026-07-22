/**
 * Milestone 3 frontend API client smoke tests.
 * Verifies difficulty prefs, habit-score stats, recommendations, and analytics
 * client surfaces exist without hitting the network.
 */
import {
  userAPI,
  recommendationAPI,
  analyticsAPI,
} from './api';

describe('Milestone 3 API client surfaces', () => {
  test('difficulty preference endpoints are exposed', () => {
    expect(typeof userAPI.getPreferences).toBe('function');
    expect(typeof userAPI.updatePreferences).toBe('function');
  });

  test('habit-score stats endpoint is exposed', () => {
    expect(typeof userAPI.getStats).toBe('function');
  });

  test('recommendation card endpoints are exposed', () => {
    expect(typeof recommendationAPI.getAll).toBe('function');
    expect(typeof recommendationAPI.getDaily).toBe('function');
    expect(typeof recommendationAPI.getSleep).toBe('function');
    expect(typeof recommendationAPI.getWake).toBe('function');
    expect(typeof recommendationAPI.getProductivity).toBe('function');
  });

  test('behavioral analytics + ingestion endpoints are exposed', () => {
    expect(typeof analyticsAPI.getBehavioral).toBe('function');
    expect(typeof analyticsAPI.getSnoozePattern).toBe('function');
    expect(typeof analyticsAPI.getWakeConsistency).toBe('function');
    expect(typeof analyticsAPI.postEvent).toBe('function');
    expect(typeof analyticsAPI.postEventsBatch).toBe('function');
  });
});
