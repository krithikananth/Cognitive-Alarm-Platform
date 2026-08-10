/**
 * Daily Plan — the suggested bedtime/wake time, morning focus, and priority
 * actions the recommendation engine generated for this client, plus the
 * combined insight lines from the coaching feed and behavioural analytics.
 */
import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineMoon,
  HiOutlineSparkles,
  HiOutlineSun,
  HiOutlineTrophy,
} from 'react-icons/hi2';
import { PanelError, PlanChip } from './primitives';
import { fadeUp } from './constants';
import { formatTimeDisplay } from '../../utils/timeFormat';
import { formatHabitScore } from '../../utils/habitScore';

export default function DailyPlan({
  digest,
  behavioral,
  clientName,
  timezone,
  error,
  onRetry,
}) {
  const insights = useMemo(() => {
    const fromDigest = digest?.insights || [];
    const fromBehavioral = (behavioral?.insights || []).filter(
      (line) => !fromDigest.includes(line)
    );
    return [...fromDigest, ...fromBehavioral].slice(0, 5);
  }, [digest, behavioral]);

  const plan = digest?.daily_plan;

  return (
    <motion.div {...fadeUp} transition={{ delay: 0.24 }} className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlineSparkles className="w-5 h-5 text-primary-400" />
          Daily Plan
        </h2>
        <span className="text-xs text-slate-400">
          {clientName} · {timezone}
        </span>
      </div>

      {error && !digest ? (
        <PanelError message={error} onRetry={onRetry} />
      ) : !plan ? (
        <p className="text-sm text-slate-500 py-6 text-center">
          No data available for this period. A preferred wake time and sleep goal on the client
          profile generate a plan.
        </p>
      ) : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
            <PlanChip
              label="Bedtime"
              value={plan.suggested_bedtime ? formatTimeDisplay(plan.suggested_bedtime) : '—'}
              icon={HiOutlineMoon}
            />
            <PlanChip
              label="Wake"
              value={plan.suggested_wake_time ? formatTimeDisplay(plan.suggested_wake_time) : '—'}
              icon={HiOutlineSun}
            />
            <PlanChip
              label="Focus"
              value={digest.summary?.top_focus_label || plan.morning_focus || '—'}
              icon={HiOutlineSparkles}
            />
            <PlanChip
              label="Habit score"
              value={formatHabitScore(digest.summary?.habit_score)}
              icon={HiOutlineTrophy}
            />
          </div>

          {plan.morning_focus && (
            <p className="text-sm text-slate-200 mb-3">{plan.morning_focus}</p>
          )}

          {plan.priority_actions?.length > 0 ? (
            <div className="rounded-xl border border-primary-500/20 bg-primary-500/5 p-4 mb-4">
              <p className="text-xs uppercase tracking-wider text-primary-300 mb-2">
                Priority actions
              </p>
              <ul className="space-y-1">
                {plan.priority_actions.map((action, i) => (
                  <li key={i} className="text-sm text-slate-300 flex gap-2">
                    <span className="text-primary-400">•</span>
                    {action}
                  </li>
                ))}
              </ul>
            </div>
          ) : (
            <p className="text-sm text-slate-500 mb-4">
              No priority actions today — this client is meeting every tracked target.
            </p>
          )}

          {insights.length > 0 && (
            <div className="rounded-xl border border-surface-700/40 bg-surface-900/40 p-4 space-y-2">
              <p className="text-xs uppercase tracking-wider text-slate-500 mb-1">Key insights</p>
              {insights.map((insight, i) => (
                <p key={i} className="text-sm text-slate-300 leading-relaxed">
                  {insight}
                </p>
              ))}
            </div>
          )}
        </>
      )}
    </motion.div>
  );
}
