/**
 * Presentation guards for the sleep-pattern and correlation dashboard panels.
 *
 * These are pure selector/formatter checks — the repo has no component render
 * harness — plus API-surface assertions for the endpoints the panels consume.
 */
import { analyticsAPI, dashboardAPI } from './api';

/** Mirrors SleepPatternsPanel's provenance copy decision. */
function sleepProvenance(sleep) {
    if (!sleep || !sleep.nights_observed) return 'empty';
    if (!sleep.has_recorded_sleep) return 'estimated-only';
    if (sleep.nights_estimated > 0) return 'mixed';
    return 'recorded-only';
}

/** Mirrors the panel's "which nights can be charted" filter. */
function chartableNights(sleep) {
    return (sleep?.nights || []).filter((n) => n.sleep_duration_hours != null);
}

/** Mirrors ProductivityCorrelationsPanel's partitioning. */
function partitionPairs(correlations) {
    const pairs = correlations?.pairs || [];
    return {
        measured: pairs.filter((p) => p.status === 'ok'),
        significant: pairs.filter((p) => p.status === 'ok' && p.significant),
        unmeasured: pairs.filter((p) => p.status !== 'ok'),
    };
}

describe('sleep + correlation API surfaces', () => {
    test('sleep pattern and correlation endpoints are exposed', () => {
        expect(typeof analyticsAPI.getSleepPatterns).toBe('function');
        expect(typeof analyticsAPI.getProductivityCorrelation).toBe('function');
    });

    test('the dashboard productivity endpoint is still the composite source', () => {
        expect(typeof dashboardAPI.getProductivity).toBe('function');
    });

    test('sleep logging reuses the existing analytics ingest endpoint', () => {
        expect(typeof analyticsAPI.postEvent).toBe('function');
    });
});

describe('sleep panel provenance', () => {
    test('no nights renders the empty state', () => {
        expect(sleepProvenance({ nights_observed: 0 })).toBe('empty');
        expect(sleepProvenance(null)).toBe('empty');
    });

    test('estimated-only nights are never shown as recorded', () => {
        const sleep = {
            nights_observed: 4,
            has_recorded_sleep: false,
            nights_recorded: 0,
            nights_estimated: 4,
        };
        expect(sleepProvenance(sleep)).toBe('estimated-only');
    });

    test('mixed sources are reported as mixed', () => {
        const sleep = {
            nights_observed: 4,
            has_recorded_sleep: true,
            nights_recorded: 1,
            nights_estimated: 3,
        };
        expect(sleepProvenance(sleep)).toBe('mixed');
    });

    test('fully recorded history is reported as recorded', () => {
        const sleep = {
            nights_observed: 3,
            has_recorded_sleep: true,
            nights_recorded: 3,
            nights_estimated: 0,
        };
        expect(sleepProvenance(sleep)).toBe('recorded-only');
    });

    test('nights without a duration are excluded from the chart', () => {
        const sleep = {
            nights: [
                { date: '2026-08-10', sleep_duration_hours: 8 },
                { date: '2026-08-09', sleep_duration_hours: null },
                { date: '2026-08-08', sleep_duration_hours: 6.5 },
            ],
        };
        expect(chartableNights(sleep).map((n) => n.date)).toEqual([
            '2026-08-10',
            '2026-08-08',
        ]);
    });
});

describe('correlation panel partitioning', () => {
    const correlations = {
        status: 'ok',
        days_analyzed: 14,
        method: { alpha: 0.05 },
        pairs: [
            { id: 'a', status: 'ok', significant: true, pearson_r: -0.9 },
            { id: 'b', status: 'ok', significant: false, pearson_r: 0.1 },
            { id: 'c', status: 'insufficient_data', significant: false, n: 2, min_pairs: 5 },
            { id: 'd', status: 'no_variance', significant: false, n: 14, min_pairs: 5 },
        ],
    };

    test('splits measured, significant and unmeasurable pairs', () => {
        const { measured, significant, unmeasured } = partitionPairs(correlations);
        expect(measured.map((p) => p.id)).toEqual(['a', 'b']);
        expect(significant.map((p) => p.id)).toEqual(['a']);
        expect(unmeasured.map((p) => p.id)).toEqual(['c', 'd']);
    });

    test('unmeasurable pairs never claim a coefficient', () => {
        const { unmeasured } = partitionPairs(correlations);
        unmeasured.forEach((pair) => {
            expect(pair.pearson_r).toBeUndefined();
            expect(pair.significant).toBe(false);
        });
    });

    test('handles a missing correlations block safely', () => {
        const { measured, significant, unmeasured } = partitionPairs(null);
        expect(measured).toEqual([]);
        expect(significant).toEqual([]);
        expect(unmeasured).toEqual([]);
    });
});
