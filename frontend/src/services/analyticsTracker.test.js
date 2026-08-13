/**
 * Analytics event batching.
 *
 * The tracker used to make one POST per event, which meant a single wake cycle
 * fired three separate requests within the same instant. Events raised inside
 * one window are now coalesced into POST /analytics/events/batch, while a
 * window that produced exactly one event still uses the single-event endpoint.
 */
jest.mock('./api', () => ({
    __esModule: true,
    analyticsAPI: {
        postEvent: jest.fn(),
        postEventsBatch: jest.fn(),
    },
}));

import { analyticsAPI } from './api';
import {
    BATCH_WINDOW_MS,
    flushAnalyticsQueue,
    trackAnalyticsEvent,
} from './analyticsTracker';

// Unique per test: the module keeps a session-lifetime set of accepted keys,
// so reusing a key across tests would be silently deduped.
let keySeed = 0;
const nextKey = () => `k${Date.now()}-${keySeed++}`;

beforeEach(() => {
    // CRA's Jest preset sets resetMocks:true, which strips implementations given
    // inside a jest.mock factory.
    analyticsAPI.postEvent.mockResolvedValue({ data: { accepted: 1 } });
    analyticsAPI.postEventsBatch.mockResolvedValue({ data: { accepted: 2 } });
    jest.useFakeTimers();
});

afterEach(() => {
    jest.useRealTimers();
});

describe('event batching', () => {
    it('sends a lone event through the single-event endpoint', async () => {
        const sent = trackAnalyticsEvent({
            eventType: 'alarm.dismissed',
            entityType: 'alarm',
            entityId: 7,
            dedupeKey: nextKey(),
        });

        jest.advanceTimersByTime(BATCH_WINDOW_MS);
        await expect(sent).resolves.toBe(true);

        expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1);
        expect(analyticsAPI.postEvent).toHaveBeenCalledWith({
            event_type: 'alarm.dismissed',
            event_data: {},
            entity_type: 'alarm',
            entity_id: 7,
        });
        expect(analyticsAPI.postEventsBatch).not.toHaveBeenCalled();
    });

    it('coalesces a wake cycle into one batch request', async () => {
        const results = Promise.all([
            trackAnalyticsEvent({
                eventType: 'challenge.completed',
                entityId: 7,
                dedupeKey: nextKey(),
            }),
            trackAnalyticsEvent({
                eventType: 'wake.verified',
                entityId: 7,
                dedupeKey: nextKey(),
            }),
            trackAnalyticsEvent({
                eventType: 'alarm.dismissed',
                entityId: 7,
                dedupeKey: nextKey(),
            }),
        ]);

        jest.advanceTimersByTime(BATCH_WINDOW_MS);
        await expect(results).resolves.toEqual([true, true, true]);

        expect(analyticsAPI.postEventsBatch).toHaveBeenCalledTimes(1);
        expect(analyticsAPI.postEvent).not.toHaveBeenCalled();

        const [events] = analyticsAPI.postEventsBatch.mock.calls[0];
        expect(events.map((e) => e.event_type)).toEqual([
            'challenge.completed',
            'wake.verified',
            'alarm.dismissed',
        ]);
    });

    it('does not queue the same logical action twice', async () => {
        const dedupeKey = nextKey();
        const first = trackAnalyticsEvent({ eventType: 'alarm.snoozed', dedupeKey });
        const second = trackAnalyticsEvent({ eventType: 'alarm.snoozed', dedupeKey });

        jest.advanceTimersByTime(BATCH_WINDOW_MS);
        await expect(first).resolves.toBe(true);
        await expect(second).resolves.toBe(false);

        expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1);
        expect(analyticsAPI.postEventsBatch).not.toHaveBeenCalled();
    });

    it('flushes queued events when the page goes away', async () => {
        const sent = trackAnalyticsEvent({
            eventType: 'alarm.missed',
            dedupeKey: nextKey(),
        });

        window.dispatchEvent(new Event('pagehide'));
        await expect(sent).resolves.toBe(true);

        // Delivered without ever reaching the timer.
        expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1);
        jest.advanceTimersByTime(BATCH_WINDOW_MS * 4);
        expect(analyticsAPI.postEvent).toHaveBeenCalledTimes(1);
    });

    it('never rejects when ingestion fails', async () => {
        analyticsAPI.postEvent.mockRejectedValue(new Error('network down'));
        const warn = jest.spyOn(console, 'warn').mockImplementation(() => { });

        const sent = trackAnalyticsEvent({
            eventType: 'alarm.abandoned',
            dedupeKey: nextKey(),
        });

        jest.advanceTimersByTime(BATCH_WINDOW_MS);
        await expect(sent).resolves.toBe(false);
        warn.mockRestore();
    });

    it('flushing an empty queue is a no-op', async () => {
        await expect(flushAnalyticsQueue()).resolves.toBe(true);
        expect(analyticsAPI.postEvent).not.toHaveBeenCalled();
        expect(analyticsAPI.postEventsBatch).not.toHaveBeenCalled();
    });
});
