/**
 * Activity & data health.
 *
 * Consumes the per-signal analytics endpoints directly rather than reading
 * them out of an aggregate, so each signal is attributable to the route that
 * produced it.
 */
import React, { useCallback, useEffect, useState } from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineArrowPath,
  HiOutlineBolt,
  HiOutlineCheckCircle,
  HiOutlineExclamationTriangle,
} from 'react-icons/hi2';
import { alarmAPI, analyticsAPI, readErrorDetail } from '../../services/api';

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

const WINDOW_DAYS = 30;
const RECENT_LIMIT = 5;

function Tile({ label, value, hint }) {
  return (
    <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 px-3 py-2.5">
      <p className="text-[11px] uppercase tracking-wider text-slate-500 mb-1">{label}</p>
      <p className="text-lg font-semibold text-white">{value}</p>
      {hint ? <p className="text-[11px] text-slate-500 mt-0.5">{hint}</p> : null}
    </div>
  );
}

function when(value) {
  if (!value) return '—';
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? '—' : parsed.toLocaleString();
}

function num(value, fallback = '—') {
  return value == null || Number.isNaN(Number(value)) ? fallback : Math.round(Number(value));
}

export default function ActivityHealthPanel() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [summary, behavioral, wakeConsistency, wakefulness, snoozes, events, logHealth] =
        await Promise.all([
          analyticsAPI.getSummary(),
          analyticsAPI.getBehavioral(WINDOW_DAYS),
          analyticsAPI.getWakeConsistency(WINDOW_DAYS),
          alarmAPI.getWakefulness(),
          alarmAPI.getSnoozeHistory({ limit: RECENT_LIMIT }),
          analyticsAPI.listEvents({ page: 1, per_page: RECENT_LIMIT }),
          alarmAPI.getChallengeLogHealth(),
        ]);
      setData({
        summary: summary.data,
        behavioral: behavioral.data,
        wakeConsistency: wakeConsistency.data,
        wakefulness: wakefulness.data,
        snoozes: snoozes.data,
        events: events.data,
        logHealth: logHealth.data,
      });
      setError(null);
    } catch (err) {
      setError((await readErrorDetail(err, '')) || 'Failed to load activity data');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !data) {
    return (
      <motion.div {...fadeUp} className="card">
        <div className="flex items-center justify-center py-10" role="status" aria-live="polite">
          <div className="w-6 h-6 border-2 border-accent-500 border-t-transparent rounded-full animate-spin" />
          <span className="sr-only">Loading activity</span>
        </div>
      </motion.div>
    );
  }

  if (error && !data) {
    return (
      <motion.div {...fadeUp} className="card">
        <p className="text-sm text-red-300" role="alert">{error}</p>
        <button
          type="button"
          onClick={load}
          className="mt-3 text-sm text-primary-400 hover:text-primary-300"
        >
          Try again
        </button>
      </motion.div>
    );
  }

  const { summary, behavioral, wakeConsistency, wakefulness, snoozes, events, logHealth } = data;
  const clean = logHealth?.is_clean && logHealth?.queryable;

  return (
    <motion.div {...fadeUp} transition={{ delay: 0.24 }} className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlineBolt className="w-5 h-5 text-accent-400" />
          Activity &amp; data health
        </h2>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border border-surface-600 text-slate-300 hover:text-white hover:border-surface-500 disabled:opacity-50"
        >
          <HiOutlineArrowPath className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Tile
          label="Events recorded"
          value={num(summary?.total_events, 0)}
          hint={`${Object.keys(summary?.by_event_type || {}).length} event types`}
        />
        <Tile
          label="Wake consistency"
          value={`${num(wakeConsistency?.rolling_profile_score, 0)}`}
          hint={`${num(wakeConsistency?.verified_wakes, 0)} verified wakes`}
        />
        <Tile
          label="Wakefulness"
          value={wakefulness?.level || '—'}
          hint={wakefulness?.score != null ? `score ${num(wakefulness.score)}` : 'no reading yet'}
        />
        <Tile
          label="Snoozes logged"
          value={num(snoozes?.total, 0)}
          hint={`last ${WINDOW_DAYS} days tracked`}
        />
      </div>

      {behavioral?.period_days ? (
        <p className="text-xs text-slate-500 mb-4">
          Behavioural window: {behavioral.period_days} days.
        </p>
      ) : null}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-5">
        {/* ── Recent snoozes ── */}
        <div>
          <h3 className="text-sm font-semibold text-white mb-2">Recent snoozes</h3>
          {(snoozes?.events || []).length === 0 ? (
            <p className="text-sm text-slate-500">No snoozes recorded.</p>
          ) : (
            <ul className="space-y-1.5">
              {snoozes.events.map((event) => (
                <li
                  key={event.id}
                  className="flex items-center justify-between gap-3 text-sm rounded-lg border border-surface-700/40 px-3 py-2"
                >
                  <span className="text-slate-300">
                    Snooze {event.snooze_number}
                    {event.snooze_limit_at_event
                      ? ` of ${event.snooze_limit_at_event}`
                      : ''}
                  </span>
                  <span className="text-xs text-slate-500">{when(event.created_at)}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* ── Recent events ── */}
        <div>
          <h3 className="text-sm font-semibold text-white mb-2">Recent tracked events</h3>
          {(events?.events || []).length === 0 ? (
            <p className="text-sm text-slate-500">No events recorded yet.</p>
          ) : (
            <ul className="space-y-1.5">
              {events.events.map((event) => (
                <li
                  key={event.id}
                  className="flex items-center justify-between gap-3 text-sm rounded-lg border border-surface-700/40 px-3 py-2"
                >
                  <span className="text-slate-300 truncate">{event.event_type}</span>
                  <span className="text-xs text-slate-500 flex-shrink-0">
                    {when(event.created_at)}
                  </span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>

      {/* ── Attempt-log integrity ── */}
      <div
        className={`mt-5 flex items-start gap-2 rounded-xl border px-3 py-2.5 text-sm ${clean
            ? 'border-emerald-500/25 bg-emerald-500/10 text-emerald-300'
            : 'border-amber-500/25 bg-amber-500/10 text-amber-200'
          }`}
      >
        {clean ? (
          <HiOutlineCheckCircle className="w-4 h-4 mt-0.5 flex-shrink-0" />
        ) : (
          <HiOutlineExclamationTriangle className="w-4 h-4 mt-0.5 flex-shrink-0" />
        )}
        <span>
          {clean
            ? `Attempt log is clean — ${num(logHealth?.total_attempts, 0)} attempts queryable.`
            : `Attempt log has ${num(logHealth?.issue_count, 0)} issue(s) across ${num(
              logHealth?.total_attempts,
              0
            )} attempts.`}
        </span>
      </div>
    </motion.div>
  );
}
