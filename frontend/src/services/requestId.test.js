/**
 * Correlation ids: generation, safety, and the axios request interceptor.
 */
import {
    REQUEST_ID_HEADER,
    getLastRequestId,
    newRequestId,
    resetRequestId,
    setLastRequestId,
} from './requestId';
import { withCorrelationId } from './api';

/** Must match the backend's sanitizer, which rejects anything else. */
const SERVER_ACCEPTED = /^[A-Za-z0-9._:-]{1,64}$/;

beforeEach(() => {
    resetRequestId();
});

describe('newRequestId', () => {
    it('produces a value the backend will accept', () => {
        expect(newRequestId()).toMatch(SERVER_ACCEPTED);
    });

    it('produces unique values', () => {
        const ids = new Set(Array.from({ length: 500 }, newRequestId));
        expect(ids.size).toBe(500);
    });

    it('works without crypto.randomUUID', () => {
        const original = globalThis.crypto;
        Object.defineProperty(globalThis, 'crypto', {
            value: undefined,
            configurable: true,
        });
        try {
            expect(newRequestId()).toMatch(SERVER_ACCEPTED);
        } finally {
            Object.defineProperty(globalThis, 'crypto', {
                value: original,
                configurable: true,
            });
        }
    });
});

describe('last request id', () => {
    it('mints one when nothing has been sent yet', () => {
        expect(getLastRequestId()).toMatch(SERVER_ACCEPTED);
    });

    it('remembers the most recent value', () => {
        setLastRequestId('trace-1');
        expect(getLastRequestId()).toBe('trace-1');
    });

    it('ignores a value the server would reject', () => {
        setLastRequestId('trace-1');
        setLastRequestId('x'.repeat(65));
        expect(getLastRequestId()).toBe('trace-1');
    });
});

describe('withCorrelationId interceptor', () => {
    it('stamps the header on every request', () => {
        const config = withCorrelationId({});
        expect(config.headers[REQUEST_ID_HEADER]).toMatch(SERVER_ACCEPTED);
    });

    it('records the id so an error report can reference it', () => {
        const config = withCorrelationId({});
        expect(getLastRequestId()).toBe(config.headers[REQUEST_ID_HEADER]);
    });

    it('uses a fresh id per request', () => {
        const first = withCorrelationId({}).headers[REQUEST_ID_HEADER];
        const second = withCorrelationId({}).headers[REQUEST_ID_HEADER];
        expect(first).not.toBe(second);
    });

    it('preserves headers the caller already set', () => {
        const config = withCorrelationId({ headers: { 'X-Custom': 'keep' } });
        expect(config.headers['X-Custom']).toBe('keep');
    });
});
