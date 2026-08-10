/**
 * Regression guards for `readErrorDetail`.
 *
 * Export requests use `responseType: 'blob'`, so a failed download delivers the
 * JSON error body as a Blob. Reading `err.response.data.detail` on a Blob
 * yields `undefined`, which is why every failed export used to surface the
 * generic "Export failed" instead of the reason the server gave.
 */
import { readErrorDetail } from './api';

// jsdom 16 (bundled with react-scripts 5) ships Blob without `.text()`, which
// browsers have had for years. Polyfill it via FileReader so these tests
// exercise the parsing logic rather than the missing-method fallback.
beforeAll(() => {
    if (typeof Blob.prototype.text !== 'function') {
        Blob.prototype.text = function readAsText() {
            return new Promise((resolve, reject) => {
                const reader = new FileReader();
                reader.onload = () => resolve(reader.result);
                reader.onerror = () => reject(reader.error);
                reader.readAsText(this);
            });
        };
    }
});

/** Build an axios-shaped error whose body is a Blob, as blob downloads do. */
function blobError(body, type = 'application/json') {
    return { response: { data: new Blob([body], { type }) } };
}

describe('readErrorDetail', () => {
    test('returns a plain JSON detail string', async () => {
        const err = { response: { data: { detail: 'Select both start and end dates' } } };

        await expect(readErrorDetail(err, 'fallback')).resolves.toBe(
            'Select both start and end dates',
        );
    });

    test('reads the detail back out of a Blob error body', async () => {
        const err = blobError(JSON.stringify({ detail: 'Report window is too large' }));

        await expect(readErrorDetail(err, 'Export failed')).resolves.toBe(
            'Report window is too large',
        );
    });

    test('reads a FastAPI validation array out of a Blob body', async () => {
        const err = blobError(
            JSON.stringify({ detail: [{ msg: 'end_date must not precede start_date' }] }),
        );

        await expect(readErrorDetail(err, 'Export failed')).resolves.toBe(
            'end_date must not precede start_date',
        );
    });

    test('unwraps a FastAPI validation array from a plain body', async () => {
        const err = { response: { data: { detail: [{ msg: 'field required' }] } } };

        await expect(readErrorDetail(err, 'fallback')).resolves.toBe('field required');
    });

    test('falls back when the Blob is not a JSON error body', async () => {
        const err = blobError('%PDF-1.4 binary payload', 'application/pdf');

        await expect(readErrorDetail(err, 'Export failed')).resolves.toBe('Export failed');
    });

    test('falls back when there is no response at all', async () => {
        await expect(readErrorDetail(new Error('Network Error'), 'Export failed')).resolves.toBe(
            'Export failed',
        );
    });
});
