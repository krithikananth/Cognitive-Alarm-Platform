/**
 * Firebase Cloud Messaging + local notification integration.
 *
 * Handles:
 * - Firebase app initialization
 * - Browser notification permission request
 * - FCM token retrieval and registration with the backend
 * - Foreground message handling
 * - Local notification scheduling (Web Notifications / iOS PWA / Android browser)
 * - Sync of upcoming pending reminders for local scheduling (deduped by id)
 *
 * Local scheduling is a deliberate complement to FCM, not a substitute: it
 * covers the window while the tab is open even if a push is delayed. Missing
 * Firebase configuration is treated as a setup error, not a supported mode.
 */

import { notificationAPI } from './api';

// ── Firebase config (set via environment variables) ────────────────
const FIREBASE_CONFIG = {
  apiKey: process.env.REACT_APP_FIREBASE_API_KEY,
  authDomain: process.env.REACT_APP_FIREBASE_AUTH_DOMAIN,
  projectId: process.env.REACT_APP_FIREBASE_PROJECT_ID,
  storageBucket: process.env.REACT_APP_FIREBASE_STORAGE_BUCKET,
  messagingSenderId: process.env.REACT_APP_FIREBASE_MESSAGING_SENDER_ID,
  appId: process.env.REACT_APP_FIREBASE_APP_ID,
};

const VAPID_KEY = process.env.REACT_APP_FIREBASE_VAPID_KEY;

// ── State ──────────────────────────────────────────────────────────

let firebaseApp = null;
let messaging = null;
let currentToken = null;
let serviceWorkerRegistration = null;
/** Shared in-flight init so concurrent callers await the same result. */
let initPromise = null;
/** Shared worker bootstrap so startup and permission flows cannot race. */
let serviceWorkerPromise = null;
/** Shared in-flight permission/token flow (Strict Mode double-mount safe). */
let permissionPromise = null;

/** @type {Map<number|string, number>} notification_id → timeoutId */
const localScheduleTimers = new Map();

// ── Helpers ────────────────────────────────────────────────────────

function isFirebaseConfigured() {
  return !!(FIREBASE_CONFIG.apiKey && FIREBASE_CONFIG.projectId);
}

function isNotificationSupported() {
  return 'Notification' in window && 'serviceWorker' in navigator;
}

/**
 * Build SW URL with Firebase config as query params so the public
 * service worker can initialize without a custom CRA build step.
 */
function buildServiceWorkerUrl() {
  if (!isFirebaseConfigured()) {
    return '/firebase-messaging-sw.js';
  }
  const params = new URLSearchParams({
    apiKey: FIREBASE_CONFIG.apiKey || '',
    authDomain: FIREBASE_CONFIG.authDomain || '',
    projectId: FIREBASE_CONFIG.projectId || '',
    storageBucket: FIREBASE_CONFIG.storageBucket || '',
    messagingSenderId: FIREBASE_CONFIG.messagingSenderId || '',
    appId: FIREBASE_CONFIG.appId || '',
  });
  return `/firebase-messaging-sw.js?${params.toString()}`;
}

/**
 * Register the messaging service worker and hand back a registration whose
 * worker is actually ACTIVE.
 *
 * Registrations left over from an earlier build — including the config-less
 * `/firebase-cloud-messaging-push-scope` one the FCM SDK creates by itself —
 * keep receiving the push events for their own subscription, so they are
 * removed before the current worker is registered.
 */
async function ensureServiceWorkerRegistration() {
  if (serviceWorkerRegistration?.active) return serviceWorkerRegistration;
  if (serviceWorkerPromise) return serviceWorkerPromise;

  serviceWorkerPromise = (async () => {
    const swUrl = buildServiceWorkerUrl();
    const expectedScriptUrl = new URL(swUrl, window.location.origin).href;
    const expectedScope = new URL('/', window.location.origin).href;
    console.info('[Notifications] Registering Firebase service worker:', {
      scope: expectedScope,
      projectId: FIREBASE_CONFIG.projectId,
    });

    const existing = await navigator.serviceWorker.getRegistrations();
    for (const registration of existing) {
      const scriptUrls = [
        registration.active?.scriptURL,
        registration.waiting?.scriptURL,
        registration.installing?.scriptURL,
      ].filter(Boolean);
      const isFirebaseWorker = scriptUrls.some((scriptUrl) =>
        new URL(scriptUrl).pathname.endsWith('/firebase-messaging-sw.js')
      );
      const isExpectedRegistration =
        registration.scope === expectedScope &&
        scriptUrls.includes(expectedScriptUrl);

      if (isFirebaseWorker && !isExpectedRegistration) {
        console.info(
          '[Notifications] Removing stale Firebase service worker:',
          { scope: registration.scope, scriptUrls }
        );
        const removed = await registration.unregister();
        if (!removed) {
          throw new Error(
            `Could not unregister stale Firebase worker at ${registration.scope}`
          );
        }
      }
    }

    const registration = await navigator.serviceWorker.register(swUrl, {
      scope: '/',
      updateViaCache: 'none',
    });
    await registration.update();
    await waitForActiveWorker(registration, expectedScriptUrl);
    await verifyServiceWorkerConfiguration(registration);

    serviceWorkerRegistration = registration;
    console.info('[Notifications] Firebase service worker active:', {
      scope: registration.scope,
      scriptURL: registration.active?.scriptURL,
    });
    return registration;
  })().catch((err) => {
    serviceWorkerPromise = null;
    serviceWorkerRegistration = null;
    console.error('[Notifications] Firebase service worker setup failed:', err);
    throw err;
  });

  return serviceWorkerPromise;
}

function verifyServiceWorkerConfiguration(registration) {
  if (!registration.active) {
    return Promise.reject(new Error('Firebase service worker is not active.'));
  }

  return new Promise((resolve, reject) => {
    const channel = new MessageChannel();
    const timer = setTimeout(() => {
      channel.port1.close();
      reject(new Error('Firebase service worker status check timed out.'));
    }, 5000);

    channel.port1.onmessage = ({ data }) => {
      clearTimeout(timer);
      channel.port1.close();
      if (
        data?.type !== 'ICAP_FCM_STATUS_RESPONSE' ||
        !data.ready ||
        data.projectId !== FIREBASE_CONFIG.projectId
      ) {
        reject(
          new Error(
            `Firebase worker configuration mismatch (expected ${FIREBASE_CONFIG.projectId}, ` +
            `received ${data?.projectId || 'none'}, ready: ${Boolean(data?.ready)}).`
          )
        );
        return;
      }

      console.log('[SW] Firebase messaging ready for', data.projectId);
      resolve();
    };

    registration.active.postMessage(
      { type: 'ICAP_FCM_STATUS_REQUEST' },
      [channel.port2]
    );
  });
}

function waitForActiveWorker(registration, expectedScriptUrl) {
  const pendingWorker = registration.installing || registration.waiting;
  if (!pendingWorker && registration.active?.scriptURL === expectedScriptUrl) {
    return Promise.resolve();
  }

  const worker = pendingWorker || registration.active;
  if (!worker) {
    return Promise.reject(new Error('Service worker registration has no worker.'));
  }

  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      reject(new Error(`Service worker activation timed out (state: ${worker.state}).`));
    }, 10000);
    worker.addEventListener('statechange', () => {
      if (worker.state === 'activated') {
        clearTimeout(timer);
        resolve();
      } else if (worker.state === 'redundant') {
        clearTimeout(timer);
        reject(new Error('Service worker became redundant before activation.'));
      }
    });
  });
}

// ── Firebase Initialization ────────────────────────────────────────

async function initializeFirebase() {
  if (messaging) return true;
  if (initPromise) return initPromise;

  if (!isFirebaseConfigured()) {
    console.error(
      '[Notifications] Firebase is not configured — push notifications are ' +
      'disabled. Set REACT_APP_FIREBASE_* in frontend/.env (see .env.example) ' +
      'and rebuild.'
    );
    return false;
  }

  if (!isNotificationSupported()) {
    console.info('[Notifications] Browser does not support notifications.');
    return false;
  }

  initPromise = (async () => {
    try {
      const { initializeApp, getApps, getApp } = await import('firebase/app');
      const { getMessaging } = await import('firebase/messaging');

      // Reuse an existing app (HMR / Strict Mode) instead of failing on duplicate-app.
      firebaseApp = getApps().length ? getApp() : initializeApp(FIREBASE_CONFIG);
      messaging = getMessaging(firebaseApp);
      console.info('[Notifications] Firebase Messaging initialized:', {
        projectId: FIREBASE_CONFIG.projectId,
        messagingSenderId: FIREBASE_CONFIG.messagingSenderId,
      });
      return true;
    } catch (err) {
      console.error('[Notifications] Firebase initialization failed:', err);
      initPromise = null; // allow a later retry
      return false;
    }
  })();

  return initPromise;
}

/**
 * Initialize Firebase Messaging and its worker without requesting permission.
 * This runs on every app entry route so worker setup is observable before login.
 */
export async function initializeNotificationRuntime() {
  console.info('[Notifications] Starting Firebase Messaging runtime:', {
    projectId: FIREBASE_CONFIG.projectId || null,
    configPresent: isFirebaseConfigured(),
    vapidKeyPresent: Boolean(VAPID_KEY),
    permission: isNotificationSupported() ? Notification.permission : 'unsupported',
  });

  const firebaseReady = await initializeFirebase();
  if (!firebaseReady) return null;

  try {
    return await ensureServiceWorkerRegistration();
  } catch {
    return null;
  }
}

// ── Permission & Token ─────────────────────────────────────────────

/**
 * Request notification permission and obtain FCM token.
 * Also syncs upcoming pending notifications for local scheduling.
 *
 * Concurrent callers (e.g. React Strict Mode remount) share one in-flight
 * attempt so a losing race cannot log "local only" while FCM is still starting.
 *
 * @returns {Promise<string|null>} FCM token or null if unavailable.
 */
export async function requestNotificationPermission() {
  if (currentToken) {
    return currentToken;
  }
  if (permissionPromise) {
    return permissionPromise;
  }

  permissionPromise = (async () => {
    try {
      return await obtainNotificationPermissionAndToken();
    } finally {
      // Allow retry only when no token was obtained.
      if (!currentToken) {
        permissionPromise = null;
      }
    }
  })();

  return permissionPromise;
}

async function obtainNotificationPermissionAndToken() {
  if (!isNotificationSupported()) {
    console.info('[Notifications] Notifications not supported in this browser.');
    return null;
  }

  console.info('[Notifications] Notification permission before request:', Notification.permission);
  let permission;
  try {
    permission = Notification.permission === 'granted'
      ? 'granted'
      : await Notification.requestPermission();
  } catch (err) {
    console.error('[Notifications] Notification permission request failed:', err);
    return null;
  }
  console.info('[Notifications] Notification permission result:', permission);
  if (permission !== 'granted') {
    console.error(
      `[Notifications] Push permission is ${permission}; no FCM token will be requested.`
    );
    return null;
  }

  const firebaseReady = await initializeFirebase();

  if (firebaseReady && messaging) {
    try {
      const { getToken } = await import('firebase/messaging');

      if (!VAPID_KEY) {
        console.error(
          '[Notifications] REACT_APP_FIREBASE_VAPID_KEY is missing — Firebase ' +
          'cannot issue a registration token. Copy the Web Push certificate ' +
          'key pair from Firebase console → Cloud Messaging.'
        );
        await syncLocalPendingNotifications();
        return null;
      }

      const registration = await ensureServiceWorkerRegistration();
      console.info('[Notifications] Requesting FCM token with registered worker.');
      const token = await getToken(messaging, {
        vapidKey: VAPID_KEY,
        serviceWorkerRegistration: registration,
      });

      if (token) {
        currentToken = token;
        console.info('[Notifications] FCM token obtained.');
        await registerTokenWithBackend(token);
        await syncLocalPendingNotifications();
        return token;
      }

      console.error(
        '[Notifications] Firebase returned no registration token; this device ' +
        'will not receive push notifications.'
      );
    } catch (err) {
      console.error(
        '[Notifications] FCM token retrieval / service worker registration failed:',
        err
      );
    }
  }

  // Permission is granted, so still schedule reminders locally for this tab.
  await syncLocalPendingNotifications();
  return null;
}

async function registerTokenWithBackend(token) {
  try {
    await notificationAPI.registerToken({
      fcm_token: token,
      device_type: detectDeviceType(),
      device_name: navigator.userAgent.substring(0, 100),
    });
    console.info('[Notifications] FCM token registered with backend.');
  } catch (err) {
    // Without a stored token the backend cannot target this device at all,
    // so this is an error rather than a cosmetic warning.
    console.error(
      '[Notifications] Failed to register device token with backend:',
      err?.response?.data?.detail || err.message
    );
  }
}

function detectDeviceType() {
  const ua = navigator.userAgent.toLowerCase();
  if (/iphone|ipad|ipod/.test(ua)) return 'ios';
  if (/android/.test(ua)) return 'android';
  return 'web';
}

// ── Foreground Message Handling ─────────────────────────────────────

export async function onForegroundMessage(callback) {
  const firebaseReady = await initializeFirebase();
  if (!firebaseReady || !messaging) return null;

  try {
    const { onMessage } = await import('firebase/messaging');
    const unsubscribe = onMessage(messaging, (payload) => {
      callback(payload);

      if (Notification.permission === 'granted') {
        const { title, body } = payload.notification || {};
        if (title) {
          showLocalNotification(title, body || '', {
            ...(payload.data || {}),
            notification_id:
              payload.data?.notification_id || `fcm-${Date.now()}`,
          });
        }
      }
    });
    return unsubscribe;
  } catch (err) {
    console.error('[Notifications] Foreground listener setup failed:', err);
    return null;
  }
}

// ── Local Notification Fallback ────────────────────────────────────

export function showLocalNotification(title, body, data = {}) {
  if (!isNotificationSupported() || Notification.permission !== 'granted') {
    console.info('[Notifications] Cannot show local notification — no permission.');
    return;
  }

  try {
    const tag = String(data?.notification_id || `icap-${Date.now()}`);
    const isAlarm = data?.notification_type === 'alarm_trigger';
    const silent = !isAlarm
      && (data?.silent === true || data?.silent === 'true'
        || data?.sound === 'silent');
    const notification = new Notification(title, {
      body,
      icon: '/favicon.svg',
      badge: '/favicon.svg',
      data,
      tag, // same tag replaces prior → zero duplicate banners
      renotify: isAlarm,
      // An alarm banner stays until the user acts; reminders self-dismiss.
      requireInteraction: isAlarm,
      silent,
    });

    notification.onclick = () => {
      window.focus();
      notification.close();
      if (isAlarm && data?.alarm_id) {
        window.location.assign(`/alarms?ring=${data.alarm_id}`);
      }
    };

    if (!isAlarm) {
      setTimeout(() => notification.close(), 10000);
    }
  } catch (err) {
    console.warn('[Notifications] Local notification failed:', err.message);
  }
}

export function scheduleLocalNotification(title, body, scheduledAt, data = {}) {
  if (!isNotificationSupported()) return null;

  const targetTime = scheduledAt instanceof Date ? scheduledAt : new Date(scheduledAt);
  const delayMs = targetTime.getTime() - Date.now();
  const id = data?.notification_id;

  // Replace any existing timer for the same notification id (dedup)
  if (id != null && localScheduleTimers.has(id)) {
    clearTimeout(localScheduleTimers.get(id));
    localScheduleTimers.delete(id);
  }

  if (delayMs <= 0) {
    showLocalNotification(title, body, data);
    return null;
  }

  if (delayMs > 24 * 60 * 60 * 1000) {
    return null;
  }

  const timeoutId = setTimeout(() => {
    if (id != null) localScheduleTimers.delete(id);
    showLocalNotification(title, body, data);
  }, delayMs);

  if (id != null) {
    localScheduleTimers.set(id, timeoutId);
  }

  return timeoutId;
}

/**
 * Fetch upcoming pending notifications from the backend and schedule
 * them locally. Safe to call repeatedly — timers are keyed by id.
 */
export async function syncLocalPendingNotifications() {
  if (!isNotificationSupported() || Notification.permission !== 'granted') {
    return 0;
  }

  try {
    const { data } = await notificationAPI.getPending({ within_hours: 24 });
    const items = data?.notifications || [];
    const seen = new Set();

    for (const n of items) {
      if (!n?.id || !n.scheduled_at) continue;
      seen.add(n.id);
      scheduleLocalNotification(n.title, n.body, n.scheduled_at, {
        ...(n.data || {}),
        notification_id: n.id,
        notification_type: n.notification_type,
      });
    }

    // Clear timers for notifications no longer pending
    for (const [id, timer] of localScheduleTimers.entries()) {
      if (!seen.has(id)) {
        clearTimeout(timer);
        localScheduleTimers.delete(id);
      }
    }

    return items.length;
  } catch (err) {
    console.error('[Notifications] Pending reminder sync failed:', err);
    return 0;
  }
}

export function clearLocalSchedules() {
  for (const timer of localScheduleTimers.values()) {
    clearTimeout(timer);
  }
  localScheduleTimers.clear();
}

// ── Cleanup ────────────────────────────────────────────────────────

export async function unregisterNotifications() {
  clearLocalSchedules();
  if (currentToken) {
    try {
      await notificationAPI.removeToken(currentToken);
    } catch (err) {
      console.warn('[Notifications] Failed to unregister token:', err.message);
    }
    currentToken = null;
  }
}

export function getNotificationPermission() {
  if (!isNotificationSupported()) return 'unsupported';
  return Notification.permission;
}

export function isPushAvailable() {
  return !!(currentToken && messaging);
}
