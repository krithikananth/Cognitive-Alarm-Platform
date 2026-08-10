/**
 * Behaviour Insights — snooze, wake, and sleep patterns for one client.
 *
 * Source: GET /coach/clients/{id}/behavioral (BehavioralAnalyticsService),
 * the same payload that backs the client's own analytics page.
 *
 * The on-time tolerance is read from the payload rather than hard-coded, so
 * changing the backend threshold updates the copy automatically.
 */
import React, { useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { HiOutlineBellAlert } from 'react-icons/hi2';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { EmptyChart, MetricBlock, PanelError } from './primitives';
import { CHART_TOOLTIP_STYLE, fadeUp, formatDayLabel, trendMeta } from './constants';
import { formatTimeDisplay } from '../../utils/timeFormat';

export default function BehaviourInsights({ behavioral, days, error, onRetry }) {
  const [trendView, setTrendView] = useState('monthly');

  const snooze = behavioral?.snooze_pattern;
  const wake = behavioral?.wake_up_consistency;
  const sleep = behavioral?.sleep_schedule_adherence;

  const snoozeTrend = useMemo(() => {
    const base = trendMeta(snooze?.trend);
    // Zero snoozes alongside verified wakes is a real result, not missing data.
    if (
      snooze?.trend === 'insufficient_data' &&
      (snooze?.total_snoozes ?? 0) === 0 &&
      (wake?.verified_wakes ?? 0) > 0
    ) {
      return { ...base, label: 'No snoozes', color: 'text-emerald-400' };
    }
    return base;
  }, [snooze, wake]);
  const wakeTrend = trendMeta(wake?.trend);
  const sleepTrend = trendMeta(sleep?.trend);
  const SnoozeTrendIcon = snoozeTrend.Icon;
  const WakeTrendIcon = wakeTrend.Icon;
  const SleepTrendIcon = sleepTrend.Icon;

  const toleranceMinutes = wake?.tolerance_minutes ?? sleep?.tolerance_minutes ?? null;
  const toleranceLabel =
    toleranceMinutes != null ? `±${toleranceMinutes} min` : 'the on-time window';

  const weekdaySnoozeData = useMemo(
    () => (snooze?.by_weekday || []).map((row) => ({ day: row.weekday, snoozes: row.count })),
    [snooze]
  );

  const periodSeries = useMemo(() => {
    const block =
      trendView === 'weekly' ? behavioral?.weekly_trends : behavioral?.monthly_trends;
    return (block?.series || []).map((row) => ({
      ...row,
      label: trendView === 'weekly' ? row.weekday : formatDayLabel(row.date),
    }));
  }, [behavioral, trendView]);

  return (
    <motion.div
      id="coach-analytics"
      {...fadeUp}
      transition={{ delay: 0.12 }}
      className="card scroll-mt-6"
    >
      <div className="flex flex-wrap items-start justify-between gap-3 mb-4">
        <div>
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <HiOutlineBellAlert className="w-5 h-5 text-sky-400" />
            Behaviour Insights
          </h2>
          <p className="text-xs text-slate-500 mt-1 max-w-2xl">
            Snooze, wake, and sleep patterns calculated from this client’s recorded alarm,
            snooze, and verified wake-up events. Trends compare the last 7 days with the 7
            days before.
          </p>
        </div>
        <span className="text-xs text-slate-400 flex-shrink-0">
          Last {behavioral?.window_days ?? days} days
        </span>
      </div>

      {error && !behavioral ? (
        <PanelError message={error} onRetry={onRetry} />
      ) : (
        <>
          {(behavioral?.insights || []).length > 0 && (
            <div className="rounded-xl border border-surface-700/40 bg-surface-900/40 p-4 mb-5 space-y-2">
              {behavioral.insights.slice(0, 5).map((insight, i) => (
                <p key={i} className="text-sm text-slate-300 leading-relaxed">
                  {insight}
                </p>
              ))}
            </div>
          )}

          <div className="grid md:grid-cols-3 gap-4 mb-5">
            <MetricBlock
              title="Snooze Pattern"
              description="How often this client snoozes before getting up, from recorded snooze events."
              trend={snoozeTrend}
              TrendIcon={SnoozeTrendIcon}
              rows={[
                [
                  'Total snoozes',
                  snooze?.total_snoozes ?? 0,
                  'Snooze events recorded in the selected period',
                ],
                [
                  'Avg per wake-up',
                  snooze?.avg_snoozes_per_wake ?? 0,
                  'Mean number of snoozes before a verified wake-up',
                ],
                [
                  'Hit snooze limit',
                  `${snooze?.limit_hit_rate ?? 0}%`,
                  'Share of snoozes that reached the alarm’s snooze limit',
                ],
                ['Peak day', snooze?.peak_weekday || '—', 'Weekday with the most snoozes'],
                [
                  'Peak hour',
                  snooze?.peak_hour != null ? `${snooze.peak_hour}:00` : '—',
                  'Hour of day with the most snoozes',
                ],
              ]}
            />
            <MetricBlock
              title="Wake Consistency"
              description={`How tightly verified wake-ups cluster around the same time, and how often they land within ${toleranceLabel} of the client’s intended wake time.`}
              trend={wakeTrend}
              TrendIcon={WakeTrendIcon}
              rows={[
                [
                  'Consistency score',
                  wake?.rolling_profile_score != null
                    ? Math.round(wake.rolling_profile_score)
                    : '—',
                  'Rolling 0–100 score that rises with each on-time verified wake and falls after a missed or late one — the same score shown on the roster',
                ],
                [
                  'Wake-time clustering',
                  wake?.consistency_score != null ? Math.round(wake.consistency_score) : '—',
                  'How tightly wake times cluster in this period: identical times score 100, an hour of spread scores near 0',
                ],
                [
                  'Verified wakes',
                  wake?.verified_wakes ?? 0,
                  'Wake-ups confirmed through challenge verification',
                ],
                [
                  'Average wake time',
                  wake?.mean_wake_time ? formatTimeDisplay(wake.mean_wake_time) : '—',
                  'Mean of all verified wake-up times',
                ],
                [
                  'Wake time spread',
                  wake?.std_wake_minutes != null ? `±${wake.std_wake_minutes} min` : '—',
                  'Standard deviation of verified wake times — smaller is more consistent',
                ],
                [
                  'On-time rate',
                  `${wake?.on_time_rate ?? 0}%`,
                  `Verified wakes within ${toleranceLabel} of the preferred wake time`,
                ],
              ]}
            />
            <MetricBlock
              title="Sleep Schedule"
              description="Adherence to the wake time and sleep-duration goal saved in the client’s profile."
              trend={sleepTrend}
              TrendIcon={SleepTrendIcon}
              rows={[
                [
                  'Preferred wake',
                  sleep?.preferred_wake_time ? formatTimeDisplay(sleep.preferred_wake_time) : '—',
                  'Wake-up time configured by the client',
                ],
                [
                  'Target sleep',
                  sleep?.target_sleep_hours != null ? `${sleep.target_sleep_hours}h` : '—',
                  'Sleep duration goal from the client’s profile',
                ],
                [
                  'Suggested bed',
                  sleep?.suggested_bedtime ? formatTimeDisplay(sleep.suggested_bedtime) : '—',
                  'Preferred wake time minus the target sleep duration',
                ],
                [
                  'Adherence',
                  sleep?.adherence_rate != null ? `${Math.round(sleep.adherence_rate)}%` : '—',
                  `Share of observed days waking within ${toleranceLabel} of the preferred time`,
                ],
                [
                  'Adherent days',
                  `${sleep?.adherent_days ?? 0}/${sleep?.observed_days ?? 0}`,
                  'Adherent days out of days with at least one verified wake-up',
                ],
                [
                  'Avg deviation',
                  sleep?.avg_deviation_minutes != null ? `${sleep.avg_deviation_minutes}m` : '—',
                  'Average gap between actual and preferred wake time',
                ],
              ]}
            />
          </div>

          <div className="grid lg:grid-cols-2 gap-6">
            <div>
              <h3 className="text-sm font-semibold text-white mb-3">Snoozes by weekday</h3>
              {weekdaySnoozeData.every((d) => d.snoozes === 0) ? (
                <EmptyChart message="No snooze data available for this period. When this client snoozes an alarm, weekday patterns will appear here." />
              ) : (
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={weekdaySnoozeData}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="day" stroke="#94a3b8" tick={{ fontSize: 12 }} />
                      <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} allowDecimals={false} />
                      <Tooltip {...CHART_TOOLTIP_STYLE} />
                      <Bar dataKey="snoozes" fill="#38bdf8" radius={[8, 8, 0, 0]} name="Snoozes" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
            <div>
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold text-white">
                  {trendView === 'monthly' ? 'Monthly' : 'Weekly'} wake &amp; snooze trends
                </h3>
                <div className="flex gap-2">
                  {['weekly', 'monthly'].map((view) => (
                    <button
                      key={view}
                      type="button"
                      onClick={() => setTrendView(view)}
                      className={`text-xs px-3 py-1.5 rounded-lg border transition capitalize ${trendView === view
                        ? 'bg-sky-500/20 text-sky-200 border-sky-500/40'
                        : 'bg-surface-800 text-slate-400 border-surface-700/50 hover:text-white'
                        }`}
                    >
                      {view}
                    </button>
                  ))}
                </div>
              </div>
              {periodSeries.every((d) => !d.verified_wakes && !d.snoozes) ? (
                <EmptyChart message="No data available for this period. A verified wake-up unlocks weekly and monthly charts." />
              ) : (
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={periodSeries}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="label" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                      <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} allowDecimals={false} />
                      <Tooltip {...CHART_TOOLTIP_STYLE} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Line type="monotone" dataKey="verified_wakes" stroke="#34d399" strokeWidth={2} name="Wakes" dot={false} />
                      <Line type="monotone" dataKey="snoozes" stroke="#38bdf8" strokeWidth={2} name="Snoozes" dot={false} />
                      <Line type="monotone" dataKey="on_time_wakes" stroke="#fbbf24" strokeWidth={2} name="On time" dot={false} />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>
          </div>
        </>
      )}
    </motion.div>
  );
}
