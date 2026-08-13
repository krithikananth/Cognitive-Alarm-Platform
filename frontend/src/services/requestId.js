/**
 * Correlation ids for the browser.
 *
 * The same value is sent as `X-Request-ID` on every API call and attached to
 * any error report, so a user saying "it broke" can be traced to the exact
 * server-side log records without asking them for anything but a code.
 */

/** Header the backend reads and echoes. */
export const REQUEST_ID_HEADER = 'X-Request-ID';

/** Backend rejects anything longer, or outside [A-Za-z0-9._:-]. */
const MAX_LENGTH = 64;

let lastRequestId = null;

/** RFC4122-ish hex id; falls back to Math.random on very old browsers. */
export function newRequestId() {
    const cryptoObj = typeof globalThis !== 'undefined' ? globalThis.crypto : undefined;
    if (cryptoObj && typeof cryptoObj.randomUUID === 'function') {
        return cryptoObj.randomUUID().replace(/-/g, '');
    }
    if (cryptoObj && typeof cryptoObj.getRandomValues === 'function') {
        const bytes = cryptoObj.getRandomValues(new Uint8Array(16));
        return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
    }
    let out = '';
    while (out.length < 32) {
        out += Math.random().toString(16).slice(2);
    }
    return out.slice(0, 32);
}

export function setLastRequestId(value) {
    if (typeof value === 'string' && value && value.length <= MAX_LENGTH) {
        lastRequestId = value;
    }
    return lastRequestId;
}

/**
 * Id of the most recent API call, used to tie a crash to the request that
 * preceded it. Mints one when nothing has been sent yet (e.g. a render error
 * on first paint).
 */
export function getLastRequestId() {
    if (!lastRequestId) {
        lastRequestId = newRequestId();
    }
    return lastRequestId;
}

export function resetRequestId() {
    lastRequestId = null;
}
