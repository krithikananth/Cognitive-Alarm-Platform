/**
 * Browser error reporting: transport, deduplication, caps and global handlers.
 */
import {
    DEDUPE_WINDOW_MS,
    MAX_REPORTS_PER_SESSION,
    REPORT_URL,
    installGlobalErrorHandlers,
    reportClientError,
    resetErrorReporting,
} from './errorReporting';
import { resetRequestId, setLastRequestId } from './requestId';

function lastBody() {
    const call = global.fetch.mock.calls[global.fetch.mock.calls.length - 1];
    return JSON.parse(call[1].body);
}

beforeEach(() => {
    resetErrorReporting();
    resetRequestId();
    global.fetch = jest.fn(() => Promise.resolve({ ok: true }));
});

afterEach(() => {
    resetErrorReporting();
    jest.useRealTimers();
    delete global.fetch;
});

describe('reportClientError transport', () => {
    it('posts the report to the client-errors endpoint', () => {
        reportClientError(new Error('boom'), { source: 'error_boundary' });

        expect(global.fetch).toHaveBeenCalledTimes(1);
        const [url, options] = global.fetch.mock.calls[0];
        expect(url).toBe(REPORT_URL);
        expect(options.method).toBe('POST');
        expect(options.headers['Content-Type']).toBe('application/json');
        // Survives the page being torn down by the very error being reported.
        expect(options.keepalive).toBe(true);
    });

    it('sends the message, name and stack', () => {
        const error = new Error('Cannot read properties of null');
        error.name = 'TypeError';
        reportClientError(error, { source: 'error_boundary' });

        const body = lastBody();
        expect(body.message).toBe('Cannot read properties of null');
        expect(body.name).toBe('TypeError');
        expect(typeof body.stack).toBe('string');
        expect(body.source).toBe('error_boundary');
    });

    it('accepts a non-Error value', () => {
        reportClientError('plain string failure');
        expect(lastBody().message).toBe('plain string failure');
    });

    it('falls back to a message when the value is empty', () => {
        reportClientError(undefined);
        expect(lastBody().message).toBe('Unknown error');
    });

    it('attaches the component stack and boundary name', () => {
        reportClientError(new Error('render failed'), {
            source: 'error_boundary',
            componentStack: '\n    at UserDashboard',
            boundary: 'route',
        });

        const body = lastBody();
        expect(body.component_stack).toContain('UserDashboard');
        expect(body.boundary).toBe('route');
    });

    it('carries the correlation id of the last API call', () => {
        setLastRequestId('abc123def456');
        reportClientError(new Error('boom'));
        expect(lastBody().request_id).toBe('abc123def456');
    });

    it('mints a correlation id when no API call has happened yet', () => {
        reportClientError(new Error('boom on first paint'));
        expect(lastBody().request_id).toMatch(/^[A-Za-z0-9._:-]{1,64}$/);
    });

    it('honours a warning severity', () => {
        reportClientError(new Error('slow'), { severity: 'warning' });
        expect(lastBody().severity).toBe('warning');
    });

    it('truncates payloads to the limits the server accepts', () => {
        const error = new Error('x'.repeat(5000));
        error.stack = 'y'.repeat(20000);
        reportClientError(error);

        const body = lastBody();
        expect(body.message).toHaveLength(1000);
        expect(body.stack).toHaveLength(8000);
    });

    it('never throws when the network rejects', () => {
        global.fetch = jest.fn(() => Promise.reject(new Error('offline')));
        expect(() => reportClientError(new Error('boom'))).not.toThrow();
    });

    it('never throws when fetch is unavailable', () => {
        delete global.fetch;
        expect(() => reportClientError(new Error('boom'))).not.toThrow();
    });
});

describe('flood protection', () => {
    it('collapses identical errors inside the dedupe window', () => {
        reportClientError(new Error('same failure'));
        const suppressed = reportClientError(new Error('same failure'));

        expect(suppressed).toBeNull();
        expect(global.fetch).toHaveBeenCalledTimes(1);
    });

    it('lets a different error through', () => {
        reportClientError(new Error('first'));
        reportClientError(new Error('second'));
        expect(global.fetch).toHaveBeenCalledTimes(2);
    });

    it('reports the same error again once the window has passed', () => {
        const spy = jest.spyOn(Date, 'now');
        spy.mockReturnValue(1_000_000);
        reportClientError(new Error('recurring'));

        spy.mockReturnValue(1_000_000 + DEDUPE_WINDOW_MS + 1);
        reportClientError(new Error('recurring'));

        expect(global.fetch).toHaveBeenCalledTimes(2);
        spy.mockRestore();
    });

    it('caps the number of reports per session', () => {
        for (let i = 0; i < MAX_REPORTS_PER_SESSION + 10; i += 1) {
            reportClientError(new Error(`distinct failure ${i}`));
        }
        expect(global.fetch).toHaveBeenCalledTimes(MAX_REPORTS_PER_SESSION);
    });
});

describe('global handlers', () => {
    it('reports an uncaught window error', () => {
        installGlobalErrorHandlers(window);

        const event = new Event('error');
        event.error = new Error('uncaught explosion');
        event.filename = 'main.js';
        event.lineno = 42;
        window.dispatchEvent(event);

        const body = lastBody();
        expect(body.message).toBe('uncaught explosion');
        expect(body.source).toBe('window_error');
        expect(body.context.file).toBe('main.js');
        expect(body.context.line).toBe('42');
    });

    it('reports an unhandled promise rejection', () => {
        installGlobalErrorHandlers(window);

        const event = new Event('unhandledrejection');
        event.reason = new Error('promise blew up');
        window.dispatchEvent(event);

        const body = lastBody();
        expect(body.message).toBe('promise blew up');
        expect(body.source).toBe('unhandled_rejection');
    });

    it('installs only once', () => {
        expect(installGlobalErrorHandlers(window)).toBe(true);
        expect(installGlobalErrorHandlers(window)).toBe(false);
    });

    it('does not double-report after a repeat install attempt', () => {
        installGlobalErrorHandlers(window);
        installGlobalErrorHandlers(window);

        const event = new Event('error');
        event.error = new Error('single report please');
        window.dispatchEvent(event);

        expect(global.fetch).toHaveBeenCalledTimes(1);
    });
});
