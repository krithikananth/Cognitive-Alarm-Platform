/**
 * Productivity Analytics — morning-routine, cognitive-readiness, and
 * consistency scores from GET /coach/clients/{id}/productivity, the client's
 * saved productivity goals, and the productivity slice of the coaching feed.
 *
 * Metrics and coaching cards come from two different requests, so each half
 * reports its own failure independently.
 */
import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineAcademicCap,
  HiOutlineBolt,
  HiOutlineChartBar,
  HiOutlineSun,
  HiOutlineTrophy,
} from 'react-icons/hi2';
import { MiniStat, PanelError, RecCard } from './primitives';
import { fadeUp, trendMeta } from './constants';

export default function ProductivityAnalytics({
  productivity,
  digest,
  goals,
  error,
  digestError,
  onRetry,
}) {
  const trend = trendMeta(productivity?.trend?.direction);
  const TrendIcon = trend.Icon;

  const cards = useMemo(() => {
    const fromCategory = digest?.by_category?.productivity || [];
    if (fromCategory.length) return fromCategory.slice(0, 4);
    return (digest?.recommendations || [])
      .filter((r) => r.category === 'productivity')
      .slice(0, 4);
  }, [digest]);

  return (
    <motion.div {...fadeUp} transition={{ delay: 0.22 }} className="card">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlineBolt className="w-5 h-5 text-sky-400" />
          Productivity Analytics
        </h2>
        {productivity?.verified_wakes > 0 && (
          <span className={`inline-flex items-center gap-1 text-xs ${trend.color}`}>
            <TrendIcon className="w-3.5 h-3.5" />
            {trend.label}
          </span>
        )}
      </div>

      {error && !productivity ? (
        <PanelError message={error} onRetry={onRetry} />
      ) : (
        <div className="grid grid-cols-2 gap-3 mb-4">
          <MiniStat
            icon={HiOutlineSun}
            label="Morning routine"
            value={
              productivity?.morning_routine_score != null
                ? `${productivity.morning_routine_score}%`
                : '—'
            }
          />
          <MiniStat
            icon={HiOutlineAcademicCap}
            label="Cognitive readiness"
            value={
              productivity?.cognitive_readiness_score != null
                ? `${productivity.cognitive_readiness_score}%`
                : '—'
            }
          />
          <MiniStat
            icon={HiOutlineChartBar}
            label="Consistency"
            value={
              productivity?.consistency_rate != null ? `${productivity.consistency_rate}%` : '—'
            }
          />
          <MiniStat
            icon={HiOutlineTrophy}
            label="Active days"
            value={productivity ? `${productivity.active_days_in_period}/${productivity.days}` : '—'}
          />
        </div>
      )}

      <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 p-4 mb-4">
        <p className="text-[10px] uppercase tracking-wider text-slate-500 mb-2">
          Saved productivity goals
        </p>
        {!goals.length ? (
          <p className="text-sm text-slate-500">
            No goals saved yet — goal-based coaching stays generic until this client sets one.
          </p>
        ) : (
          <div className="flex flex-wrap gap-2">
            {goals.map((goal) => (
              <span
                key={goal}
                className="text-xs px-2.5 py-1 rounded-full border border-sky-500/25 bg-sky-500/10 text-sky-300"
              >
                {goal}
              </span>
            ))}
          </div>
        )}
      </div>

      {digestError && !digest ? (
        <PanelError message={digestError} onRetry={onRetry} />
      ) : !cards.length ? (
        <p className="text-sm text-slate-500 py-6 text-center">
          No data available for this period. Client goals plus completed morning wake cycles
          unlock these tips.
        </p>
      ) : (
        <div className="space-y-3">
          {cards.map((rec) => (
            <RecCard key={rec.id} rec={rec} emphasize />
          ))}
        </div>
      )}
    </motion.div>
  );
}
