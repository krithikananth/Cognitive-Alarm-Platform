/**
 * Habit Insights — the client's composite habit score, its weighted
 * components, the improvement delta for the window, and the daily trend.
 *
 * Source: `habit_trends` from GET /coach/clients/{id}/behavioral, which is the
 * canonical habit-score service replayed per day. The roster row supplies the
 * headline score as a fallback while the request is still in flight.
 */
import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import { HiOutlineTrophy } from 'react-icons/hi2';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { EmptyChart, PanelError } from './primitives';
import {
  CHART_TOOLTIP_STYLE,
  DEFAULT_HABIT_WEIGHTS,
  HABIT_COMPONENTS,
  fadeUp,
  trendMeta,
} from './constants';
import { buildHabitSeries } from './selectors';

export default function HabitInsights({ behavioral, clientRow, days, error, onRetry }) {
  const habits = behavioral?.habit_trends;
  const breakdown = habits?.current_breakdown || clientRow?.habit_breakdown || null;
  const weights = habits?.weights || DEFAULT_HABIT_WEIGHTS;
  const trend = trendMeta(habits?.trend);
  const TrendIcon = trend.Icon;

  const series = useMemo(() => buildHabitSeries(habits), [habits]);

  const delta = habits?.trend_detail || null;
  const deltaSupported =
    delta != null &&
    delta.direction !== 'insufficient_data' &&
    (delta.active_days ?? 0) >= 2;

  return (
    <motion.div {...fadeUp} transition={{ delay: 0.14 }} className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlineTrophy className="w-5 h-5 text-emerald-400" />
          Habit Insights
        </h2>
        <span className={`inline-flex items-center gap-1 text-xs ${trend.color}`}>
          <TrendIcon className="w-3.5 h-3.5" />
          {trend.label}
        </span>
      </div>

      {error && !behavioral ? (
        <PanelError message={error} onRetry={onRetry} />
      ) : (
        <div className="grid lg:grid-cols-2 gap-6">
          <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 p-4">
            <div className="flex items-end gap-2 mb-1">
              <span className="text-4xl font-bold gradient-accent bg-clip-text text-transparent">
                {habits?.current_habit_score != null
                  ? Math.round(habits.current_habit_score)
                  : clientRow?.habit_score != null
                    ? Math.round(clientRow.habit_score)
                    : '—'}
              </span>
              <span className="text-slate-400 text-lg mb-1">/ 100</span>
              <span className="text-xs text-slate-500 mb-1.5 ml-auto">
                Avg proxy {habits?.avg_proxy_score ?? 0}
              </span>
            </div>
            <p className="text-xs text-slate-500 mb-3">
              Overall Habit Score · wake consistency{' '}
              {Math.round((weights.wake_up_consistency || 0) * 100)}% + challenge{' '}
              {Math.round((weights.challenge_completion || 0) * 100)}% + snooze reduction{' '}
              {Math.round((weights.snooze_reduction || 0) * 100)}% + sleep adherence{' '}
              {Math.round((weights.sleep_adherence || 0) * 100)}%
            </p>

            {deltaSupported ? (
              <div
                className={`flex items-center gap-2 text-xs mb-4 ${trend.color}`}
                title={`Second half of the window averaged ${delta.recent_avg} vs ${delta.previous_avg} in the first half, across ${delta.active_days} active days.`}
              >
                <TrendIcon className="w-4 h-4" />
                <span className="font-medium">
                  {delta.change > 0 ? '+' : ''}
                  {delta.change} pts
                </span>
                <span className="text-slate-500">
                  vs earlier in the last {delta.window_days} days
                </span>
              </div>
            ) : (
              <p className="text-xs text-slate-500 mb-4">
                Improvement trend needs at least two active days in this period.
              </p>
            )}

            {!breakdown ? (
              <p className="text-xs text-slate-500 py-6 text-center">
                No data available for this period. This client needs a verified wake-up to
                unlock habit component scores.
              </p>
            ) : (
              <div className="space-y-3">
                {HABIT_COMPONENTS.map((row) => {
                  const score = Number(breakdown[row.key] ?? 0);
                  const weight = Math.round((weights[row.key] || 0) * 100);
                  return (
                    <div key={row.key}>
                      <div className="flex items-center justify-between text-xs mb-1">
                        <span className="text-slate-400">
                          {row.label}
                          <span className="text-slate-600 ml-1">({weight}%)</span>
                        </span>
                        <span className="text-slate-200 font-medium">{Math.round(score)}</span>
                      </div>
                      <div className="w-full bg-surface-700 rounded-full h-1.5">
                        <div
                          className={`h-1.5 rounded-full ${row.color} transition-all duration-700`}
                          style={{ width: `${Math.min(100, Math.max(0, score))}%` }}
                        />
                      </div>
                    </div>
                  );
                })}
              </div>
            )}
          </div>

          <div>
            <h3 className="text-sm font-semibold text-white mb-3">
              Habit score trend · last {behavioral?.window_days ?? days} days
            </h3>
            {series.length === 0 ? (
              <EmptyChart message="No data available for this period. Daily alarm dismissals and challenge completions build this series." />
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={series}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                    <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} domain={[0, 100]} />
                    <Tooltip {...CHART_TOOLTIP_STYLE} />
                    <Area
                      type="monotone"
                      dataKey="score"
                      stroke="#a78bfa"
                      fill="#a78bfa33"
                      strokeWidth={2}
                      name="Habit score"
                    />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>
      )}
    </motion.div>
  );
}
