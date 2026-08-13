/**
 * Challenge Performance — cognitive challenge accuracy, response times, and
 * the client's most recent attempts.
 *
 * Source: GET /coach/clients/{id}/challenge-performance
 * (dashboard_aggregations.compute_challenge_performance).
 * Attempt timestamps are UTC instants, so they render in the client's own
 * stored timezone rather than the coach's browser zone.
 */
import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineArrowTrendingDown,
  HiOutlineArrowTrendingUp,
  HiOutlineBolt,
  HiOutlineChartBar,
  HiOutlinePuzzlePiece,
  HiOutlineSparkles,
  HiOutlineTrophy,
} from 'react-icons/hi2';
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { EmptyChart, MiniStat, PanelError } from './primitives';
import { CHART_TOOLTIP_STYLE, clientTimezoneOf, fadeUp, trendMeta } from './constants';
import { formatInTimeZone } from '../../utils/timeFormat';

export default function ChallengePerformance({ challenge, clientRow, error, onRetry }) {
  const timezone = clientTimezoneOf(clientRow);
  const trend = trendMeta(challenge?.trend?.direction);
  const TrendIcon = trend.Icon;
  const completion = challenge?.completion;
  // The chip reports the accuracy trend, which needs attempts in two periods —
  // it is not a verdict on whether the section has data.
  const hasTrend = ['improving', 'declining', 'stable'].includes(
    challenge?.trend?.direction
  );
  // The backend ranks only categories with 2+ attempts, so identical best/worst
  // means a single category qualified and there is nothing to compare against.
  const onlyCategory =
    challenge?.best_type && challenge.best_type === challenge.worst_type
      ? challenge.best_type
      : null;

  const categoryLabel = (type) =>
    `${type.replace(/_/g, ' ')} · ${Math.round(challenge.by_type?.[type]?.accuracy ?? 0)}%`;

  const byType = useMemo(
    () =>
      Object.entries(challenge?.by_type || {}).map(([type, stats]) => ({
        type: type.replace(/_/g, ' '),
        accuracy: Math.round(stats.accuracy ?? 0),
        attempts: stats.total ?? 0,
      })),
    [challenge]
  );

  const recentAttempts = useMemo(
    () =>
      (challenge?.recent_activity || []).map((attempt, index) => ({
        key: `${attempt.created_at || index}-${index}`,
        when:
          formatInTimeZone(attempt.created_at, timezone, {
            month: 'short',
            day: 'numeric',
            hour: 'numeric',
            minute: '2-digit',
          }) || '—',
        category: (attempt.challenge_type || 'unknown').replace(/_/g, ' '),
        difficulty: attempt.difficulty || '—',
        isCorrect: Boolean(attempt.is_correct),
        seconds: attempt.time_taken_seconds ?? 0,
        points: attempt.points_earned ?? 0,
      })),
    [challenge, timezone]
  );

  return (
    <motion.div {...fadeUp} transition={{ delay: 0.18 }} className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlinePuzzlePiece className="w-5 h-5 text-violet-400" />
          Challenge Performance
        </h2>
        {challenge?.total_attempts > 0 && hasTrend && (
          <span className={`inline-flex items-center gap-1 text-xs ${trend.color}`}>
            <TrendIcon className="w-3.5 h-3.5" />
            {trend.label}
          </span>
        )}
      </div>

      {error && !challenge ? (
        <PanelError message={error} onRetry={onRetry} />
      ) : (
        <>
          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
            <MiniStat
              icon={HiOutlinePuzzlePiece}
              label="Attempts"
              value={challenge?.total_attempts ?? 0}
            />
            <MiniStat
              icon={HiOutlineTrophy}
              label="Accuracy"
              value={challenge ? `${Math.round(challenge.accuracy)}%` : '—'}
            />
            <MiniStat
              icon={HiOutlineBolt}
              label="Avg response"
              value={challenge ? `${challenge.avg_response_time}s` : '—'}
            />
            <MiniStat
              icon={HiOutlineSparkles}
              label="Points earned"
              value={challenge?.total_points_earned ?? 0}
            />
          </div>

          {completion?.served > 0 && (
            <div
              className="rounded-xl border border-surface-700/40 bg-surface-900/40 p-4 mb-5"
              title="Share of challenges served to this client that they finished inside the time limit. Unanswered and timed-out challenges never reach the attempt log, so accuracy cannot show them."
            >
              <div className="flex flex-wrap items-baseline justify-between gap-2 mb-1">
                <p className="text-sm font-medium text-white">Challenge completion</p>
                <p className="text-lg font-semibold text-emerald-300">
                  {completion.completion_rate}%
                </p>
              </div>
              <p className="text-xs text-slate-400">
                Finished {completion.completed} of {completion.served} challenges served
                {' · '}
                {completion.timed_out} timed out
                {' · '}
                {completion.abandoned} left unanswered
              </p>
            </div>
          )}

          {!challenge?.total_attempts ? (
            <EmptyChart message="No data available for this period. Accuracy by puzzle type appears once this client solves alarm challenges." />
          ) : (
            <>
              <div className="grid lg:grid-cols-2 gap-6">
                <div>
                  <h3 className="text-sm font-semibold text-white mb-3">Accuracy by category</h3>
                  <div className="h-64">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart data={byType}>
                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                        <XAxis dataKey="type" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                        <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} domain={[0, 100]} />
                        <Tooltip {...CHART_TOOLTIP_STYLE} />
                        <Bar dataKey="accuracy" fill="#a78bfa" radius={[8, 8, 0, 0]} name="Accuracy %" />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3 content-start">
                  {onlyCategory ? (
                    <MiniStat
                      icon={HiOutlinePuzzlePiece}
                      label="Only category with data"
                      value={categoryLabel(onlyCategory)}
                    />
                  ) : (
                    <>
                      <MiniStat
                        icon={HiOutlineArrowTrendingUp}
                        label="Strongest category"
                        value={
                          challenge.best_type
                            ? categoryLabel(challenge.best_type)
                            : 'Needs 2+ attempts in a category'
                        }
                      />
                      <MiniStat
                        icon={HiOutlineArrowTrendingDown}
                        label="Weakest category"
                        value={
                          challenge.worst_type
                            ? categoryLabel(challenge.worst_type)
                            : 'Needs 2+ attempts in a category'
                        }
                      />
                    </>
                  )}
                  <MiniStat
                    icon={HiOutlineTrophy}
                    label="Correct answers"
                    value={`${challenge.correct_answers ?? 0}/${challenge.total_attempts}`}
                  />
                  <MiniStat
                    icon={HiOutlineChartBar}
                    label="Accuracy change"
                    value={
                      challenge.trend?.direction === 'insufficient_data'
                        ? '—'
                        : `${challenge.trend.accuracy_change > 0 ? '+' : ''}${challenge.trend.accuracy_change
                        } pts`
                    }
                  />
                </div>
              </div>

              <div className="mt-6">
                <div className="flex flex-wrap items-center justify-between gap-2 mb-3">
                  <h3 className="text-sm font-semibold text-white">Recent attempts</h3>
                  <span className="text-xs text-slate-500">Times shown in {timezone}</span>
                </div>
                {!recentAttempts.length ? (
                  <p className="text-sm text-slate-500 py-4">
                    No data available for this period.
                  </p>
                ) : (
                  <div className="overflow-x-auto rounded-xl border border-surface-700/50">
                    <table className="w-full text-sm">
                      <thead>
                        <tr className="text-left text-[10px] uppercase tracking-wider text-slate-500 bg-surface-900/50">
                          <th className="px-3 py-2 font-medium">When</th>
                          <th className="px-3 py-2 font-medium">Category</th>
                          <th className="px-3 py-2 font-medium">Difficulty</th>
                          <th className="px-3 py-2 font-medium">Result</th>
                          <th className="px-3 py-2 font-medium text-right">Response</th>
                          <th className="px-3 py-2 font-medium text-right">Points</th>
                        </tr>
                      </thead>
                      <tbody>
                        {recentAttempts.map((attempt) => (
                          <tr key={attempt.key} className="border-t border-surface-700/40">
                            <td className="px-3 py-2 text-slate-300 whitespace-nowrap">
                              {attempt.when}
                            </td>
                            <td className="px-3 py-2 text-slate-300 capitalize">
                              {attempt.category}
                            </td>
                            <td className="px-3 py-2 text-slate-400 capitalize">
                              {attempt.difficulty}
                            </td>
                            <td
                              className={`px-3 py-2 font-medium ${attempt.isCorrect ? 'text-emerald-400' : 'text-orange-400'
                                }`}
                            >
                              {attempt.isCorrect ? 'Correct' : 'Missed'}
                            </td>
                            <td className="px-3 py-2 text-slate-300 text-right whitespace-nowrap">
                              {attempt.seconds}s
                            </td>
                            <td className="px-3 py-2 text-slate-300 text-right">
                              {attempt.points}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </div>
            </>
          )}
        </>
      )}
    </motion.div>
  );
}
