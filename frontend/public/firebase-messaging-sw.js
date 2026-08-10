/**
 * Firebase Messaging Service Worker.
 *
 * Handles background push notifications when the app tab is not focused.
 * Config is injected via query-string params when the SW is registered
 * (see notificationService.js → buildServiceWorkerUrl).
 *
 * Missing config is a deployment error, not a supported mode: it is reported
 * loudly, and the worker still handles notificationclick so any local
 * notification already on screen stays clickable.
 */

/* eslint-disable no-restricted-globals */

// A push is delivered to the ACTIVE worker only. Without these two lines a
// previously registered (config-less) worker keeps control while the new one
// waits, and every background push is silently dropped.
self.addEventListener('install', () => self.skipWaiting());
self.addEventListener('activate', (event) =>
  event.waitUntil(self.clients.claim())
);

try {
  importScripts(
    'https://www.gstatic.com/firebasejs/10.12.0/firebase-app-compat.js'
  );
  importScripts(
    'https://www.gstatic.com/firebasejs/10.12.0/firebase-messaging-compat.js'
  );
} catch (e) {
  console.error('[SW] Firebase scripts could not be loaded:', e.message);
}

function readConfigFromQuery() {
  try {
    const params = new URL(self.location.href).searchParams;
    const apiKey = params.get('apiKey');
    if (!apiKey || apiKey.startsWith('__')) return null;
    return {
      apiKey,
      authDomain: params.get('authDomain') || undefined,
      projectId: params.get('projectId') || undefined,
      storageBucket: params.get('storageBucket') || undefined,
      messagingSenderId: params.get('messagingSenderId') || undefined,
      appId: params.get('appId') || undefined,
    };
  } catch {
    return null;
  }
}

const firebaseConfig = readConfigFromQuery();
let messagingReady = false;

const isConfigured =
  typeof firebase !== 'undefined' &&
  firebaseConfig &&
  firebaseConfig.apiKey &&
  firebaseConfig.projectId;

if (isConfigured) {
  try {
    firebase.initializeApp(firebaseConfig);
    const messaging = firebase.messaging();
    messagingReady = true;
    console.info('[SW] Firebase messaging ready for', firebaseConfig.projectId);

    messaging.onBackgroundMessage((payload) => {
      // Messages carrying a `notification` block are displayed by the FCM SDK
      // itself; showing our own here would produce two banners.
      if (payload.notification) return;

      const data = payload.data || {};
      const isAlarm = data.notification_type === 'alarm_trigger';
      const notificationTitle = data.title || (isAlarm ? 'Alarm' : 'Cognitive Alarm');
      const notificationOptions = {
        body: data.body || 'You have a new notification',
        icon: '/favicon.svg',
        badge: '/favicon.svg',
        data,
        // Stable tag prevents duplicate banners for the same notification
        tag: data.notification_id || `icap-bg-${Date.now()}`,
        renotify: isAlarm,
        // An alarm must stay on screen until the user acts on it.
        requireInteraction: isAlarm,
        silent: !isAlarm && (data.silent === true || data.silent === 'true' || data.sound === 'silent'),
        vibrate: isAlarm ? [400, 200, 400, 200, 400] : undefined,
        actions: isAlarm
          ? [
            { action: 'open', title: 'Turn it off' },
            { action: 'dismiss', title: 'Later' },
          ]
          : [
            { action: 'open', title: 'Open App' },
            { action: 'dismiss', title: 'Dismiss' },
          ],
      };

      self.registration.showNotification(
        notificationTitle,
        notificationOptions
      );
    });
  } catch (e) {
    console.error('[SW] Firebase messaging setup failed:', e.message);
  }
} else {
  console.error(
    '[SW] Firebase config missing — background push will not be delivered. ' +
    'Check REACT_APP_FIREBASE_* in the frontend build.'
  );
}

self.addEventListener('message', (event) => {
  if (event.data?.type !== 'ICAP_FCM_STATUS_REQUEST') return;

  const response = {
    type: 'ICAP_FCM_STATUS_RESPONSE',
    ready: messagingReady,
    projectId: firebaseConfig?.projectId || null,
  };
  if (event.ports?.[0]) {
    event.ports[0].postMessage(response);
  }
});

self.addEventListener('notificationclick', (event) => {
  // Notifications rendered by the FCM SDK carry FCM_MSG and are handled by the
  // SDK's own click listener — handling them twice can open two windows.
  if (event.notification?.data?.FCM_MSG) return;

  event.notification.close();

  if (event.action === 'dismiss') return;

  const data = event.notification?.data || {};
  // Alarm pushes deep-link straight to the ringing alarm so the existing
  // challenge / verification flow starts as soon as the app is focused.
  const target =
    data.notification_type === 'alarm_trigger' && data.alarm_id
      ? `/alarms?ring=${data.alarm_id}`
      : '/';

  event.waitUntil(
    self.clients
      .matchAll({ type: 'window', includeUncontrolled: true })
      .then((clientList) => {
        for (const client of clientList) {
          if (client.url.includes(self.location.origin) && 'focus' in client) {
            if (target !== '/' && 'navigate' in client) {
              return client.navigate(target).then((c) => (c || client).focus());
            }
            return client.focus();
          }
        }
        if (self.clients.openWindow) {
          return self.clients.openWindow(target);
        }
      })
  );
});
