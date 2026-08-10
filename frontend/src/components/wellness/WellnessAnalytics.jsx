/**
 * Wellness Analytics — the roll-up view: one headline figure per wellness
 * dimension plus the four habit components charted together over the window.
 *
 * Every figure is read from an already-fetched payload; nothing is recomputed
 * in the browser beyond rounding.
 */
import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineBellAlert,
  HiOutlineChartBar,
  HiOutlineMoon,
  HiOutlinePuzzlePiece,
  HiOutlineSun,
  HiOutlineTrophy,
} from 'react-icons/hi2';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { EmptyChart, MiniStat, PanelError } from './primitives';
import { CHART_TOOLTIP_STYLE, fadeUp } from './constants';
import { buildHabitSeries } from './selectors';
import { formatHabitScore } from '../../utils/habitScore';

export default function WellnessAnalytics({
  behavioral,
  challenge,
  clientName,
  error,
  onRetry,
}) {
  const snooze = behavioral?.snooze_pattern;
  const wake = behavioral?.wake_up_consistency;
  const sleep = behavioral?.sleep_schedule_adherence;
  const habits = behavioral?.habit_trends;

  const series = useMemo(() => buildHabitSeries(habits), [habits]);

  return (
    <motion.div {...fadeUp} transition={{ delay: 0.26 }} className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlineChartBar className="w-5 h-5 text-violet-400" />
          Wellness Analytics
        </h2>
        <span className="text-xs text-slate-400">{clientName}</span>
      </div>

      {error && !behavioral ? (
        <PanelError message={error} onRetry={onRetry} />
      ) : (
        <>
          <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3 mb-5">
            <MiniStat icon={HiOutlineBellAlert} label="Snoozes" value={snooze?.total_snoozes ?? 0} />
            <MiniStat
              icon={HiOutlineSun}
              label="Wake consistency"
              value={
                wake?.rolling_profile_score != null
                  ? Math.round(wake.rolling_profile_score)
                  : '—'
              }
            />
            <MiniStat
              icon={HiOutlineMoon}
              label="Schedule adherence"
              value={sleep?.adherence_rate != null ? `${Math.round(sleep.adherence_rate)}%` : '—'}
            />
            <MiniStat
              icon={HiOutlinePuzzlePiece}
              label="Challenge accuracy"
              value={challenge?.total_attempts ? `${Math.round(challenge.accuracy)}%` : '—'}
            />
            <MiniStat
              icon={HiOutlineTrophy}
              label="Habit score"
              value={formatHabitScore(habits?.current_habit_score)}
            />
          </div>

          {series.length === 0 ? (
            <EmptyChart message="No data available for this period. A few morning routines unlock component trends." />
          ) : (
            <div className="h-72">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={series}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} domain={[0, 100]} />
                  <Tooltip {...CHART_TOOLTIP_STYLE} />
                  <Legend wrapperStyle={{ fontSize: 11 }} />
                  <Line type="monotone" dataKey="score" stroke="#a78bfa" strokeWidth={2} name="Habit" dot={false} />
                  <Line type="monotone" dataKey="sleep" stroke="#818cf8" strokeWidth={2} name="Sleep" dot={false} />
                  <Line type="monotone" dataKey="wake" stroke="#fbbf24" strokeWidth={2} name="Wake" dot={false} />
                  <Line type="monotone" dataKey="challenge" stroke="#c084fc" strokeWidth={2} name="Challenge" dot={false} />
                  <Line type="monotone" dataKey="snooze" stroke="#38bdf8" strokeWidth={2} name="Snooze ↓" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}
    </motion.div>
  );
}
