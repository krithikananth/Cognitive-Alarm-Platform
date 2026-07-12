/**
 * Challenge Analytics — performance tracking + completion analysis.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineChartBar,
  HiOutlineLightBulb,
  HiOutlineTrophy,
  HiOutlineClock,
  HiOutlineSparkles,
  HiOutlineExclamationTriangle,
  HiOutlineCheckCircle,
  HiOutlineArrowTrendingUp,
  HiOutlineArrowTrendingDown,
  HiOutlineMinus,
} from 'react-icons/hi2';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
} from 'recharts';
import toast from 'react-hot-toast';
import { alarmAPI } from '../services/api';

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

const TYPE_LABELS = {
  math: 'Math',
  logic: 'Logic',
  memory: 'Memory',
  word_game: 'Word',
  pattern: 'Pattern',
  riddle: 'Riddle',
  quiz: 'Quiz',
  random: 'Random',
};

function formatType(type) {
  return TYPE_LABELS[type] || (type || 'Unknown').replace(/_/g, ' ');
}

export default function Analytics() {
  const [stats, setStats] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [statsRes, analysisRes, historyRes] = await Promise.all([
          alarmAPI.getChallengeStats(),
          alarmAPI.getChallengeAnalysis(),
          alarmAPI.getChallengeHistory({ page, per_page: 15 }),
        ]);
        if (cancelled) return;
        setStats(statsRes.data);
        setAnalysis(analysisRes.data);
        setHistory(historyRes.data.history || []);
        setHistoryTotal(historyRes.data.total || 0);
      } catch (err) {
        toast.error(err.response?.data?.detail || 'Failed to load analytics');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [page]);

  const typeChartData = useMemo(() => {
    const byType = analysis?.by_type || stats?.by_type || {};
    return Object.entries(byType).map(([type, s]) => ({
      type: formatType(type),
      accuracy: s.accuracy ?? 0,
      attempts: s.total ?? 0,
    }));
  }, [analysis, stats]);

  const summary = analysis?.summary || {};
  const trendIcon =
    summary.trend === 'improving'
      ? HiOutlineArrowTrendingUp
      : summary.trend === 'declining'
        ? HiOutlineArrowTrendingDown
        : HiOutlineMinus;
  const TrendIcon = trendIcon;

  if (loading && !stats) {
    return (
      <div className="flex items-center justify-center min-h-[40vh]">
        <div className="w-10 h-10 border-4 border-accent-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <motion.div {...fadeUp}>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <HiOutlineChartBar className="w-7 h-7 text-emerald-400" />
          Challenge Analytics
        </h1>
        <p className="text-slate-400 mt-1">
          Performance tracking, completion analysis, and personalized recommendations
        </p>
      </motion.div>

      {/* Summary cards */}
      <motion.div {...fadeUp} transition={{ delay: 0.05 }} className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          label="Accuracy"
          value={`${summary.accuracy_percentage ?? stats?.accuracy_percentage ?? 0}%`}
          icon={HiOutlineTrophy}
          color="from-emerald-500 to-teal-500"
        />
        <StatCard
          label="Attempts"
          value={summary.total_attempts ?? stats?.total_attempts ?? 0}
          icon={HiOutlineSparkles}
          color="from-violet-500 to-purple-500"
        />
        <StatCard
          label="Avg Time"
          value={`${summary.avg_response_time ?? stats?.avg_response_time ?? 0}s`}
          icon={HiOutlineClock}
          color="from-amber-500 to-orange-500"
        />
        <StatCard
          label="Points"
          value={summary.total_points_earned ?? stats?.total_points_earned ?? 0}
          icon={HiOutlineCheckCircle}
          color="from-sky-500 to-blue-500"
        />
      </motion.div>

      <div className="grid lg:grid-cols-3 gap-6">
        {/* Insights & recommendations */}
        <motion.div {...fadeUp} transition={{ delay: 0.1 }} className="lg:col-span-2 space-y-6">
          <div className="card">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                <HiOutlineLightBulb className="w-5 h-5 text-amber-400" />
                Completion Analysis
              </h2>
              <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-surface-700 text-slate-300">
                <TrendIcon className="w-3.5 h-3.5" />
                {summary.trend_label || 'No trend yet'}
              </span>
            </div>

            <div className="space-y-2 mb-5">
              {(analysis?.insights || []).map((insight, i) => (
                <p key={i} className="text-sm text-slate-300 leading-relaxed">
                  {insight}
                </p>
              ))}
            </div>

            <div className="grid sm:grid-cols-2 gap-4 mb-5">
              <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4">
                <p className="text-xs uppercase tracking-wider text-emerald-400 mb-2">Strengths</p>
                {(analysis?.strengths || []).length === 0 ? (
                  <p className="text-sm text-slate-500">Need more attempts to detect strengths.</p>
                ) : (
                  <ul className="space-y-2">
                    {analysis.strengths.map((s) => (
                      <li key={s.type} className="text-sm text-slate-200">
                        {s.label}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
              <div className="rounded-xl border border-orange-500/20 bg-orange-500/5 p-4">
                <p className="text-xs uppercase tracking-wider text-orange-400 mb-2">Weaknesses</p>
                {(analysis?.weaknesses || []).length === 0 ? (
                  <p className="text-sm text-slate-500">No clear weak spots yet — nice work.</p>
                ) : (
                  <ul className="space-y-2">
                    {analysis.weaknesses.map((w) => (
                      <li key={w.type} className="text-sm text-slate-200">
                        {w.label}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </div>

            <h3 className="text-sm font-semibold text-white mb-3 flex items-center gap-2">
              <HiOutlineExclamationTriangle className="w-4 h-4 text-amber-400" />
              Recommendations
            </h3>
            <div className="space-y-3">
              {(analysis?.recommendations || []).map((rec, i) => (
                <div
                  key={i}
                  className="rounded-xl border border-surface-700/60 bg-surface-800/40 p-4"
                >
                  <div className="flex items-center gap-2 mb-1">
                    <PriorityBadge priority={rec.priority} />
                    <p className="text-sm font-medium text-white">{rec.title}</p>
                  </div>
                  <p className="text-sm text-slate-400">{rec.detail}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="card">
            <h2 className="text-lg font-semibold text-white mb-4">Accuracy by Challenge Type</h2>
            {typeChartData.length === 0 ? (
              <p className="text-sm text-slate-500 py-8 text-center">
                Complete challenges to see type breakdown charts.
              </p>
            ) : (
              <div className="h-64">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={typeChartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="type" stroke="#94a3b8" tick={{ fontSize: 12 }} />
                    <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} domain={[0, 100]} />
                    <Tooltip
                      contentStyle={{
                        background: '#1e293b',
                        border: '1px solid #334155',
                        borderRadius: 12,
                      }}
                      labelStyle={{ color: '#e2e8f0' }}
                    />
                    <Bar dataKey="accuracy" fill="#10b981" radius={[8, 8, 0, 0]} name="Accuracy %" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </motion.div>

        {/* Personalization sidebar */}
        <motion.div {...fadeUp} transition={{ delay: 0.15 }} className="space-y-6">
          <div className="card">
            <h2 className="text-lg font-semibold text-white mb-3">Personalization</h2>
            <p className="text-xs text-slate-400 mb-3 uppercase tracking-wider">
              Adaptive difficulty
            </p>
            <p className="text-sm text-slate-300 mb-4">
              {analysis?.personalization?.adaptive_difficulty?.reason ||
                'Adaptive difficulty activates after 5+ recent attempts.'}
            </p>
            <div className="flex items-center justify-between text-sm mb-4">
              <span className="text-slate-400">Profile preference</span>
              <span className="text-white capitalize">
                {analysis?.personalization?.difficulty_preference || 'medium'}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm mb-4">
              <span className="text-slate-400">Adapted level</span>
              <span className="text-accent-400 capitalize font-medium">
                {analysis?.personalization?.adaptive_difficulty?.difficulty || '—'}
              </span>
            </div>

            <p className="text-xs text-slate-400 mb-2 uppercase tracking-wider">
              Preferred types
            </p>
            <div className="flex flex-wrap gap-2 mb-4">
              {(analysis?.personalization?.preferred_challenge_types || []).length === 0 ? (
                <span className="text-sm text-slate-500">All types (default)</span>
              ) : (
                analysis.personalization.preferred_challenge_types.map((t) => (
                  <span
                    key={t}
                    className="text-xs px-2.5 py-1 rounded-lg bg-accent-500/10 text-accent-300 border border-accent-500/20"
                  >
                    {formatType(t)}
                  </span>
                ))
              )}
            </div>

            <p className="text-xs text-slate-400 mb-2 uppercase tracking-wider">
              Suggested mix
            </p>
            <div className="flex flex-wrap gap-2">
              {(analysis?.suggested_preferred_types || []).map((t) => (
                <span
                  key={t}
                  className="text-xs px-2.5 py-1 rounded-lg bg-surface-700 text-slate-300"
                >
                  {formatType(t)}
                </span>
              ))}
            </div>
          </div>

          <div className="card">
            <h2 className="text-lg font-semibold text-white mb-3">By Difficulty</h2>
            <div className="space-y-3">
              {Object.entries(analysis?.by_difficulty || stats?.by_difficulty || {}).length === 0 ? (
                <p className="text-sm text-slate-500">No difficulty data yet.</p>
              ) : (
                Object.entries(analysis?.by_difficulty || stats?.by_difficulty || {}).map(
                  ([diff, s]) => (
                    <div key={diff}>
                      <div className="flex justify-between text-sm mb-1">
                        <span className="capitalize text-slate-300">{diff}</span>
                        <span className="text-slate-400">
                          {s.accuracy}% · {s.total} tries
                        </span>
                      </div>
                      <div className="w-full bg-surface-700 rounded-full h-2">
                        <div
                          className="h-2 rounded-full bg-gradient-to-r from-emerald-500 to-teal-400"
                          style={{ width: `${Math.min(100, s.accuracy || 0)}%` }}
                        />
                      </div>
                    </div>
                  )
                )
              )}
            </div>
          </div>
        </motion.div>
      </div>

      {/* History table */}
      <motion.div {...fadeUp} transition={{ delay: 0.2 }} className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white">Challenge History</h2>
          <span className="text-xs text-slate-400">{historyTotal} attempts</span>
        </div>

        {history.length === 0 ? (
          <p className="text-sm text-slate-500 py-6 text-center">
            No attempts logged yet. Ring an alarm and solve a challenge to start tracking.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-left text-xs uppercase tracking-wider text-slate-500 border-b border-surface-700/50">
                  <th className="pb-3 pr-3">When</th>
                  <th className="pb-3 pr-3">Type</th>
                  <th className="pb-3 pr-3">Difficulty</th>
                  <th className="pb-3 pr-3">Result</th>
                  <th className="pb-3 pr-3">Time</th>
                  <th className="pb-3 pr-3">Points</th>
                  <th className="pb-3">Prompt</th>
                </tr>
              </thead>
              <tbody>
                {history.map((row) => (
                  <tr key={row.id} className="border-b border-surface-800/60 text-slate-300">
                    <td className="py-3 pr-3 whitespace-nowrap text-slate-400">
                      {row.created_at
                        ? new Date(row.created_at).toLocaleString()
                        : '—'}
                    </td>
                    <td className="py-3 pr-3 capitalize">{formatType(row.challenge_type)}</td>
                    <td className="py-3 pr-3 capitalize">{row.difficulty || '—'}</td>
                    <td className="py-3 pr-3">
                      <span
                        className={`text-xs px-2 py-0.5 rounded-full ${
                          row.is_correct
                            ? 'bg-emerald-500/15 text-emerald-400'
                            : 'bg-red-500/15 text-red-400'
                        }`}
                      >
                        {row.is_correct ? 'Correct' : 'Incorrect'}
                      </span>
                    </td>
                    <td className="py-3 pr-3">{row.time_taken_seconds}s</td>
                    <td className="py-3 pr-3">{row.points_earned}</td>
                    <td className="py-3 max-w-[240px] truncate text-slate-400" title={row.challenge_prompt}>
                      {row.challenge_prompt || '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {historyTotal > 15 && (
          <div className="flex items-center justify-end gap-2 mt-4">
            <button
              type="button"
              className="btn-secondary text-sm px-3 py-1.5 disabled:opacity-40"
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              Previous
            </button>
            <span className="text-xs text-slate-400">Page {page}</span>
            <button
              type="button"
              className="btn-secondary text-sm px-3 py-1.5 disabled:opacity-40"
              disabled={page * 15 >= historyTotal}
              onClick={() => setPage((p) => p + 1)}
            >
              Next
            </button>
          </div>
        )}
      </motion.div>
    </div>
  );
}

function StatCard({ label, value, icon: Icon, color }) {
  return (
    <div className="stat-card">
      <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${color} flex items-center justify-center mb-2`}>
        <Icon className="w-5 h-5 text-white" />
      </div>
      <p className="text-xs text-slate-400 uppercase tracking-wider">{label}</p>
      <p className="stat-value mt-1">{value}</p>
    </div>
  );
}

function PriorityBadge({ priority }) {
  const styles = {
    high: 'bg-red-500/15 text-red-400',
    medium: 'bg-amber-500/15 text-amber-400',
    low: 'bg-slate-500/20 text-slate-300',
  };
  return (
    <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full ${styles[priority] || styles.low}`}>
      {priority}
    </span>
  );
}
