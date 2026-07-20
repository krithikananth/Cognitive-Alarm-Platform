/**
 * Fire-and-forget client analytics for alarm / challenge lifecycle events.
 *
 * Uses existing POST /analytics/events only. Failures are logged and never
 * thrown to callers so user actions are never blocked.
 */
import { analyticsAPI } from './api';

/** Canonical event types aligned with backend AnalyticsEventType (+ client gaps). */
export const AnalyticsEventType = {
  ALARM_SNOOZED: 'alarm.snoozed',
  ALARM_DISMISSED: 'alarm.dismissed',
  ALARM_MISSED: 'alarm.missed',
  CHALLENGE_COMPLETED: 'challenge.completed',
  CHALLENGE_FAILED: 'challenge.failed',
  WAKE_VERIFIED: 'wake.verified',
};

const SENT_STORAGE_KEY = 'icap_analytics_sent_keys';
const MAX_SENT_KEYS = 200;

/** Keys currently in-flight (prevents concurrent duplicate POSTs). */
const inFlightKeys = new Set();

/** Keys successfully accepted this session (memory + sessionStorage). */
const sentKeys = new Set(_loadSentKeys());

function _loadSentKeys() {
  try {
    const raw = sessionStorage.getItem(SENT_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed.slice(-MAX_SENT_KEYS) : [];
  } catch {
    return [];
  }
}

function _persistSentKey(key) {
  sentKeys.add(key);
  try {
    const next = [...sentKeys].slice(-MAX_SENT_KEYS);
    sessionStorage.setItem(SENT_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Private mode / quota — memory dedupe still applies.
  }
}

/**
 * Build a stable dedupe key for an event instance.
 * @param {string} eventType
 * @param {string|number|null|undefined} dedupeKey
 */
function buildDedupeKey(eventType, dedupeKey) {
  return `${eventType}::${dedupeKey ?? 'once'}`;
}

/**
 * Post one analytics event. Never throws; returns whether a request was sent.
 *
 * @param {object} options
 * @param {string} options.eventType
 * @param {string} [options.entityType]
 * @param {number|null} [options.entityId]
 * @param {object} [options.eventData]
 * @param {string|Date} [options.occurredAt]
 * @param {string|number} [options.dedupeKey] Unique per logical action (required for dedupe)
 * @returns {Promise<boolean>}
 */
export async function trackAnalyticsEvent({
  eventType,
  entityType = null,
  entityId = null,
  eventData = {},
  occurredAt = null,
  dedupeKey = null,
} = {}) {
  if (!eventType) return false;

  const key = buildDedupeKey(eventType, dedupeKey);
  if (sentKeys.has(key) || inFlightKeys.has(key)) {
    return false;
  }

  inFlightKeys.add(key);

  const payload = {
    event_type: eventType,
    event_data: eventData && typeof eventData === 'object' ? eventData : {},
  };
  if (entityType) payload.entity_type = entityType;
  if (entityId != null && Number.isFinite(Number(entityId)) && Number(entityId) >= 1) {
    payload.entity_id = Number(entityId);
  }
  if (occurredAt) {
    payload.occurred_at =
      occurredAt instanceof Date ? occurredAt.toISOString() : String(occurredAt);
  }

  try {
    await analyticsAPI.postEvent(payload);
    _persistSentKey(key);
    return true;
  } catch (err) {
    // Swallow — analytics must never affect UX
    const detail = err?.response?.data?.detail || err?.message || 'unknown error';
    console.warn(`[analytics] Failed to post ${eventType}:`, detail);
    return false;
  } finally {
    inFlightKeys.delete(key);
  }
}

/** Fire-and-forget wrapper: schedules track without awaiting. */
export function trackAnalyticsEventFireAndForget(options) {
  Promise.resolve()
    .then(() => trackAnalyticsEvent(options))
    .catch(() => {});
}

// ─── Domain helpers ───────────────────────────────────────────────

export function trackAlarmSnoozed(alarmId, eventData = {}, dedupeKey) {
  trackAnalyticsEventFireAndForget({
    eventType: AnalyticsEventType.ALARM_SNOOZED,
    entityType: 'alarm',
    entityId: alarmId,
    eventData,
    dedupeKey: dedupeKey ?? `${alarmId}:snooze:${eventData.snooze_count ?? 'n'}`,
  });
}

export function trackAlarmDismissed(alarmId, eventData = {}, dedupeKey) {
  trackAnalyticsEventFireAndForget({
    eventType: AnalyticsEventType.ALARM_DISMISSED,
    entityType: 'alarm',
    entityId: alarmId,
    eventData,
    dedupeKey: dedupeKey ?? `${alarmId}:dismiss:${eventData.trigger_at ?? Date.now()}`,
  });
}

export function trackChallengeCompleted(alarmId, eventData = {}, dedupeKey) {
  trackAnalyticsEventFireAndForget({
    eventType: AnalyticsEventType.CHALLENGE_COMPLETED,
    entityType: 'alarm',
    entityId: alarmId,
    eventData: { ...eventData, is_correct: true },
    dedupeKey:
      dedupeKey ??
      `${alarmId}:challenge_ok:${eventData.challenge_step ?? 's'}:${eventData.attempt_nonce ?? ''}`,
  });
}

export function trackChallengeFailed(alarmId, eventData = {}, dedupeKey) {
  trackAnalyticsEventFireAndForget({
    eventType: AnalyticsEventType.CHALLENGE_FAILED,
    entityType: 'alarm',
    entityId: alarmId,
    eventData: { ...eventData, is_correct: false },
    dedupeKey:
      dedupeKey ??
      `${alarmId}:challenge_fail:${eventData.challenge_step ?? 's'}:${eventData.attempt_nonce ?? ''}`,
  });
}

export function trackWakeVerified(alarmId, eventData = {}, dedupeKey) {
  trackAnalyticsEventFireAndForget({
    eventType: AnalyticsEventType.WAKE_VERIFIED,
    entityType: 'alarm',
    entityId: alarmId,
    eventData,
    dedupeKey: dedupeKey ?? `${alarmId}:wake:${eventData.trigger_at ?? Date.now()}`,
  });
}

export function trackAlarmMissed(alarmId, eventData = {}, dedupeKey) {
  trackAnalyticsEventFireAndForget({
    eventType: AnalyticsEventType.ALARM_MISSED,
    entityType: 'alarm',
    entityId: alarmId,
    eventData,
    dedupeKey:
      dedupeKey ?? `${alarmId}:missed:${eventData.next_trigger_at ?? eventData.trigger_at ?? 'n'}`,
  });
}
