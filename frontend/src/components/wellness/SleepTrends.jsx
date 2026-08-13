/**
 * Sleep Trends — sleep adherence, wake consistency, and schedule adherence for
 * the selected 7/30/90-day window, plus the daily series behind them.
 *
 * Sources: `sleep_schedule_adherence`, `wake_up_consistency`, `sleep_patterns`,
 * `habit_trends`, and `window_trends` from GET /coach/clients/{id}/behavioral.
 * `window_trends` spans exactly the selected window, so the charts move with
 * the period chips. `sleep_patterns` carries measured sessions and always
 * states whether a night was recorded by the client or estimated.
 */
import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import { HiOutlineMoon } from 'react-icons/hi2';
import {
  Area,
  AreaChart,
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
import { CHART_TOOLTIP_STYLE, clientTimezoneOf, fadeUp, trendMeta } from './constants';
import { buildScheduleSeries, buildSleepAdherenceSeries } from './selectors';
import { formatTimeDisplay } from '../../utils/timeFormat';

const MEASURED_SLEEP_DESCRIPTIONS = {
  recorded: 'Sleep sessions the client logged themselves.',
  mixed:
    'Part logged by the client, part estimated from their last app activity before waking — see the nights breakdown.',
  estimated:
    'Estimated from the last app activity before each verified wake — an upper bound, not logged sleep.',
  none: 'No sleep sessions could be measured for this period.',
};

export default function SleepTrends({ behavioral, clientRow, days, error, onRetry }) {
  const sleep = behavioral?.sleep_schedule_adherence;
  const wake = behavioral?.wake_up_consistency;
  const habits = behavioral?.habit_trends;
  const windowTrends = behavioral?.window_trends;
  const patterns = behavioral?.sleep_patterns;
  const timezone = clientTimezoneOf(clientRow);

  const sleepTrend = trendMeta(sleep?.trend);
  const wakeTrend = trendMeta(wake?.trend);
  const scheduleTrend = trendMeta(windowTrends?.trend);
  const durationTrend = trendMeta(patterns?.trend);
  const SleepTrendIcon = sleepTrend.Icon;
  const WakeTrendIcon = wakeTrend.Icon;
  const ScheduleTrendIcon = scheduleTrend.Icon;
  const DurationTrendIcon = durationTrend.Icon;

  const toleranceMinutes = wake?.tolerance_minutes ?? sleep?.tolerance_minutes ?? null;
  const toleranceLabel =
    toleranceMinutes != null ? `±${toleranceMinutes} min` : 'the on-time window';

  const adherenceSeries = useMemo(() => buildSleepAdherenceSeries(habits), [habits]);
  const scheduleSeries = useMemo(() => buildScheduleSeries(windowTrends), [windowTrends]);
  const scheduleRate = windowTrends?.totals?.on_time_rate ?? null;

  const measuredSleepDescription = MEASURED_SLEEP_DESCRIPTIONS[
    patterns?.duration_source
  ] || MEASURED_SLEEP_DESCRIPTIONS.none;

  return (
    <motion.div {...fadeUp} transition={{ delay: 0.16 }} className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlineMoon className="w-5 h-5 text-indigo-400" />
          Sleep Trends
        </h2>
        <span className="text-xs text-slate-400">
          Daily time-series · last {behavioral?.window_days ?? days} days · {timezone}
        </span>
      </div>

      {error && !behavioral ? (
        <PanelError message={error} onRetry={onRetry} />
      ) : (
        <>
          <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-3 mb-5">
            <MetricBlock
              title="Sleep Adherence"
              description={`Days the client woke within ${toleranceLabel} of their preferred wake time.`}
              trend={sleepTrend}
              TrendIcon={SleepTrendIcon}
              rows={[
                [
                  'Adherence rate',
                  sleep?.adherence_rate != null ? `${Math.round(sleep.adherence_rate)}%` : '—',
                  'Adherent days ÷ observed days',
                ],
                [
                  'Adherent days',
                  `${sleep?.adherent_days ?? 0}/${sleep?.observed_days ?? 0}`,
                  'One row per calendar day with a verified wake-up',
                ],
                [
                  'Avg deviation',
                  sleep?.avg_deviation_minutes != null
                    ? `${Math.round(sleep.avg_deviation_minutes)} min`
                    : '—',
                  'Average distance from the preferred wake time',
                ],
                [
                  'Suggested bedtime',
                  sleep?.suggested_bedtime ? formatTimeDisplay(sleep.suggested_bedtime) : '—',
                  'Preferred wake time minus the sleep-duration goal',
                ],
              ]}
            />
            <MetricBlock
              title="Wake Consistency"
              description="How tightly the client's verified wake-ups cluster around the same time."
              trend={wakeTrend}
              TrendIcon={WakeTrendIcon}
              rows={[
                [
                  'Consistency score',
                  wake?.rolling_profile_score != null
                    ? `${Math.round(wake.rolling_profile_score)}/100`
                    : '—',
                  'Rolling wake-consistency score shared with the roster and habit score',
                ],
                [
                  'Wake-time clustering',
                  wake?.consistency_score != null
                    ? `${Math.round(wake.consistency_score)}/100`
                    : '—',
                  'Falls as the spread of wake times widens',
                ],
                [
                  'Verified wakes',
                  wake?.verified_wakes ?? 0,
                  'Dismissals confirmed by a solved challenge',
                ],
                [
                  'Mean wake time',
                  wake?.mean_wake_time ? formatTimeDisplay(wake.mean_wake_time) : '—',
                  'Average of verified wake-up times',
                ],
                [
                  'Spread',
                  wake?.std_wake_minutes != null
                    ? `± ${Math.round(wake.std_wake_minutes)} min`
                    : '—',
                  'Standard deviation of wake times',
                ],
              ]}
            />
            <MetricBlock
              title="Schedule Adherence"
              description={`On-time wake-ups (within ${toleranceLabel}) across the selected ${behavioral?.window_days ?? days
                }-day period.`}
              trend={scheduleTrend}
              TrendIcon={ScheduleTrendIcon}
              rows={[
                [
                  'On-time rate',
                  scheduleRate != null ? `${Math.round(scheduleRate)}%` : '—',
                  'On-time wakes ÷ verified wakes in this period',
                ],
                [
                  'On-time wakes',
                  `${windowTrends?.totals?.on_time_wakes ?? 0}/${windowTrends?.totals?.verified_wakes ?? 0
                  }`,
                  'Counted from daily buckets in the selected period',
                ],
                [
                  'Preferred wake',
                  sleep?.preferred_wake_time ? formatTimeDisplay(sleep.preferred_wake_time) : '—',
                  'Saved on the client profile',
                ],
                [
                  'Sleep goal',
                  sleep?.target_sleep_hours != null ? `${sleep.target_sleep_hours} h` : '—',
                  'Target sleep duration from the client profile',
                ],
              ]}
            />
            <MetricBlock
              title="Measured Sleep"
              description={measuredSleepDescription}
              trend={durationTrend}
              TrendIcon={DurationTrendIcon}
              rows={[
                [
                  'Avg duration',
                  patterns?.avg_sleep_duration_hours != null
                    ? `${patterns.avg_sleep_duration_hours} h`
                    : '—',
                  'Measured from each night’s sleep start and wake',
                ],
                [
                  'Avg bedtime',
                  patterns?.avg_bedtime ? formatTimeDisplay(patterns.avg_bedtime) : '—',
                  'Observed sleep start, not the suggested bedtime',
                ],
                [
                  'Schedule regularity',
                  patterns?.nights_with_duration
                    ? `${Math.round(patterns.schedule_regularity_score)}/100`
                    : '—',
                  'Falls as bedtime and wake times scatter',
                ],
                [
                  'Social jetlag',
                  patterns?.social_jetlag_minutes != null
                    ? `${Math.round(patterns.social_jetlag_minutes)} min`
                    : '—',
                  'Weekend vs weekday mid-sleep shift',
                ],
                [
                  'Nights measured',
                  `${patterns?.nights_with_duration ?? 0}/${patterns?.nights_observed ?? 0}`,
                  `${patterns?.nights_recorded ?? 0} recorded · ${patterns?.nights_estimated ?? 0} estimated`,
                ],
              ]}
            />
          </div>

          <div className="grid lg:grid-cols-2 gap-6">
            <div>
              <h3 className="text-sm font-semibold text-white mb-3">Sleep adherence over time</h3>
              {adherenceSeries.length === 0 ? (
                <EmptyChart message="No data available for this period. A preferred wake time plus verified wake-ups unlock this series." />
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <LineChart data={adherenceSeries}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                      <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} domain={[0, 100]} />
                      <Tooltip {...CHART_TOOLTIP_STYLE} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Line
                        type="monotone"
                        dataKey="sleep_adherence"
                        stroke="#818cf8"
                        strokeWidth={2}
                        name="Sleep adherence"
                        dot={{ r: 3, fill: '#818cf8' }}
                      />
                      <Line
                        type="monotone"
                        dataKey="wake_consistency"
                        stroke="#fbbf24"
                        strokeWidth={2}
                        name="Wake consistency"
                        dot={false}
                      />
                    </LineChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            <div>
              <h3 className="text-sm font-semibold text-white mb-3">
                Schedule adherence (on-time wakes)
              </h3>
              {scheduleSeries.length === 0 ? (
                <EmptyChart message="No data available for this period. On-time wakes against the preferred time populate this chart." />
              ) : (
                <div className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={scheduleSeries}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                      <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} allowDecimals={false} />
                      <Tooltip {...CHART_TOOLTIP_STYLE} />
                      <Legend wrapperStyle={{ fontSize: 11 }} />
                      <Bar dataKey="verified" fill="#38bdf8" radius={[6, 6, 0, 0]} name="Verified wakes" />
                      <Bar dataKey="on_time" fill="#34d399" radius={[6, 6, 0, 0]} name="On-time wakes" />
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              )}
            </div>

            <div className="lg:col-span-2">
              <h3 className="text-sm font-semibold text-white mb-3">Schedule adherence rate</h3>
              {scheduleSeries.length === 0 ? (
                <EmptyChart message="No data available for this period. Each day with a verified wake-up adds a point to this trend." />
              ) : (
                <div className="h-56">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={scheduleSeries}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                      <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} domain={[0, 100]} />
                      <Tooltip {...CHART_TOOLTIP_STYLE} />
                      <Area
                        type="monotone"
                        dataKey="adherence_pct"
                        stroke="#34d399"
                        fill="#34d39926"
                        strokeWidth={2}
                        name="On-time wakes %"
                      />
                    </AreaChart>
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
