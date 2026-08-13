/**
 * Browser error tracking.
 *
 * Until now a JavaScript exception went to `console.error` and vanished — no
 * one operating the platform could tell that a page was broken for real users.
 * This module ships those errors to `POST /system/client-errors`, where they
 * are written to the same structured, correlated server log as everything else.
 *
 * Deliberately does NOT use the shared axios client: that instance carries the
 * 401-refresh interceptor which redirects to /login on failure, so reporting an
 * error could log the user out. Plain `fetch` (with `keepalive`, so a report
 * survives the page unloading) avoids that entirely, and every failure path
 * here is swallowed — error reporting must never itself throw.
 */

import { getLastRequestId } from './requestId';

const API_BASE = process.env.REACT_APP_API_URL || 'http://localhost:8000/api/v1';

export const REPORT_URL = `${API_BASE}/system/client-errors`;

/** Mirrors the server-side schema caps so payloads are never rejected. */
const LIMITS = {
    message: 1000,
    name: 120,
    stack: 8000,
    componentStack: 8000,
    url: 500,
    userAgent: 300,
    boundary: 80,
};

/** Identical errors fire in bursts (render loops); collapse them. */
export const DEDUPE_WINDOW_MS = 10000;

/** Hard ceiling per page session, so a crash loop cannot flood the backend. */
export const MAX_REPORTS_PER_SESSION = 25;

const recentFingerprints = new Map();
let reportCount = 0;
let installed = false;
let handlers = null;

function truncate(value, max) {
    if (value === null || value === undefined) return undefined;
    const text = typeof value === 'string' ? value : String(value);
    if (!text) return undefined;
    return text.length > max ? text.slice(0, max) : text;
}

function fingerprint({ name, message, source }) {
    return `${source}|${name || ''}|${(message || '').slice(0, 200)}`;
}

function isDuplicate(key, now) {
    const seenAt = recentFingerprints.get(key);
    if (seenAt !== undefined && now - seenAt < DEDUPE_WINDOW_MS) {
        return true;
    }
    recentFingerprints.set(key, now);
    // Bounded: only entries inside the window can suppress anything.
    recentFingerprints.forEach((at, existing) => {
        if (now - at >= DEDUPE_WINDOW_MS) recentFingerprints.delete(existing);
    });
    return false;
}

function normalize(error, options = {}) {
    const isError = error instanceof Error;
    const message =
        truncate(isError ? error.message : error, LIMITS.message) || 'Unknown error';
    return {
        message,
        name: truncate(isError ? error.name : options.name, LIMITS.name),
        stack: truncate(isError ? error.stack : options.stack, LIMITS.stack),
        component_stack: truncate(options.componentStack, LIMITS.componentStack),
        source: options.source || 'manual',
        severity: options.severity === 'warning' ? 'warning' : 'error',
        url: truncate(
            typeof window !== 'undefined' ? window.location?.href : undefined,
            LIMITS.url
        ),
        user_agent: truncate(
            typeof navigator !== 'undefined' ? navigator.userAgent : undefined,
            LIMITS.userAgent
        ),
        app_version: process.env.REACT_APP_VERSION || undefined,
        boundary: truncate(options.boundary, LIMITS.boundary),
        request_id: getLastRequestId(),
        occurred_at: new Date().toISOString(),
        context: options.context,
    };
}

function transmit(payload) {
    const body = JSON.stringify(payload);
    try {
        if (typeof fetch === 'function') {
            // keepalive lets the report outlive the page that produced it.
            return fetch(REPORT_URL, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body,
                keepalive: true,
                credentials: 'include',
            }).catch(() => undefined);
        }
        if (typeof navigator !== 'undefined' && navigator.sendBeacon) {
            navigator.sendBeacon(REPORT_URL, new Blob([body], { type: 'application/json' }));
        }
    } catch (err) {
        // Reporting must never surface a second error to the user.
    }
    return Promise.resolve(undefined);
}

/**
 * Report one error. Returns the payload that was sent, or `null` when it was
 * suppressed as a duplicate or over the session cap.
 */
export function reportClientError(error, options = {}) {
    try {
        const payload = normalize(error, options);
        const now = Date.now();

        if (isDuplicate(fingerprint(payload), now)) return null;
        if (reportCount >= MAX_REPORTS_PER_SESSION) return null;
        reportCount += 1;

        transmit(payload);
        return payload;
    } catch (err) {
        return null;
    }
}

/** Catch errors that never reach a React boundary. */
export function installGlobalErrorHandlers(target = typeof window !== 'undefined' ? window : null) {
    if (installed || !target || typeof target.addEventListener !== 'function') {
        return false;
    }

    handlers = {
        target,
        onError: (event) => {
            reportClientError(event?.error || event?.message || 'Unhandled error', {
                source: 'window_error',
                context: {
                    file: event?.filename ? String(event.filename) : '',
                    line: String(event?.lineno ?? ''),
                    column: String(event?.colno ?? ''),
                },
            });
        },
        onRejection: (event) => {
            reportClientError(event?.reason || 'Unhandled promise rejection', {
                source: 'unhandled_rejection',
            });
        },
    };

    target.addEventListener('error', handlers.onError);
    target.addEventListener('unhandledrejection', handlers.onRejection);
    installed = true;
    return true;
}

/** Detach handlers and clear counters — used by tests. */
export function resetErrorReporting() {
    if (handlers) {
        handlers.target.removeEventListener('error', handlers.onError);
        handlers.target.removeEventListener('unhandledrejection', handlers.onRejection);
    }
    handlers = null;
    installed = false;
    reportCount = 0;
    recentFingerprints.clear();
}
