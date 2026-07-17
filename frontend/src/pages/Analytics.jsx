/**
 * Analytics — behavioral trends + challenge performance + recommendations.
 */
import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
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
  HiOutlineMoon,
  HiOutlineSun,
  HiOutlineBolt,
  HiOutlineBellAlert,
} from 'react-icons/hi2';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  CartesianGrid,
  LineChart,
  Line,
  Legend,
} from 'recharts';
import toast from 'react-hot-toast';
import { alarmAPI, analyticsAPI, recommendationAPI } from '../services/api';
import { formatTimeDisplay } from '../utils/timeFormat';

const LIFESTYLE_CATEGORY_STYLES = {
  sleep: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/25',
  wake: 'bg-amber-500/15 text-amber-300 border-amber-500/25',
  habit: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
  productivity: 'bg-sky-500/15 text-sky-300 border-sky-500/25',
  challenge: 'bg-violet-500/15 text-violet-300 border-violet-500/25',
};

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
  const key = (type || '').toLowerCase();
  return TYPE_LABELS[key] || (type || 'Unknown').replace(/_/g, ' ');
}

function trendMeta(trend) {
  if (trend === 'improving') {
    return { Icon: HiOutlineArrowTrendingUp, label: 'Improving', color: 'text-emerald-400' };
  }
  if (trend === 'declining') {
    return { Icon: HiOutlineArrowTrendingDown, label: 'Declining', color: 'text-orange-400' };
  }
  if (trend === 'stable') {
    return { Icon: HiOutlineMinus, label: 'Stable', color: 'text-slate-300' };
  }
  return { Icon: HiOutlineMinus, label: 'Not enough data', color: 'text-slate-500' };
}

export default function Analytics() {
  const [stats, setStats] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [recommendations, setRecommendations] = useState(null);
  const [behavioral, setBehavioral] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [recFilter, setRecFilter] = useState('all');
  const [trendView, setTrendView] = useState('weekly');
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [statsRes, analysisRes, historyRes, recRes, behavioralRes] =
          await Promise.all([
            alarmAPI.getChallengeStats(),
            alarmAPI.getChallengeAnalysis(),
            alarmAPI.getChallengeHistory({ page, per_page: 15 }),
            recommendationAPI.getAll(),
            analyticsAPI.getBehavioral(30),
          ]);
        if (cancelled) return;
        setStats(statsRes.data);
        setAnalysis(analysisRes.data);
        setHistory(historyRes.data.history || []);
        setHistoryTotal(historyRes.data.total || 0);
        setRecommendations(recRes.data);
        setBehavioral(behavioralRes.data);
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

  const filteredRecs = useMemo(() => {
    const all = recommendations?.recommendations || [];
    if (recFilter === 'all') return all;
    return all.filter((r) => r.category === recFilter);
  }, [recommendations, recFilter]);

  const typeChartData = useMemo(() => {
    const byType = analysis?.by_type || stats?.by_type || {};
    return Object.entries(byType).map(([type, s]) => ({
      type: formatType(type),
      accuracy: s.accuracy ?? 0,
      attempts: s.total ?? 0,
    }));
  }, [analysis, stats]);

  const weekdaySnoozeData = useMemo(() => {
    return (behavioral?.snooze_pattern?.by_weekday || []).map((row) => ({
      day: row.weekday,
      snoozes: row.count,
    }));
  }, [behavioral]);

  const periodSeries = useMemo(() => {
    const block =
      trendView === 'monthly'
        ? behavioral?.monthly_trends
        : behavioral?.weekly_trends;
    return (block?.series || []).map((row) => ({
      ...row,
      label: trendView === 'monthly' ? row.date.slice(5) : row.weekday,
    }));
  }, [behavioral, trendView]);

  const habitSeries = useMemo(() => {
    return (behavioral?.habit_trends?.series || [])
      .filter((row) => row.has_activity)
      .map((row) => ({
        date: row.date.slice(5),
        score: row.habit_score,
      }));
  }, [behavioral]);

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

  const snooze = behavioral?.snooze_pattern;
  const wake = behavioral?.wake_up_consistency;
  const sleep = behavioral?.sleep_schedule_adherence;
  const habits = behavioral?.habit_trends;
  const snoozeTrend = trendMeta(snooze?.trend);
  const wakeTrend = trendMeta(wake?.trend);
  const sleepTrend = trendMeta(sleep?.trend);
  const habitTrend = trendMeta(habits?.trend);
  const SnoozeTrendIcon = snoozeTrend.Icon;
  const WakeTrendIcon = wakeTrend.Icon;
  const SleepTrendIcon = sleepTrend.Icon;
  const HabitTrendIcon = habitTrend.Icon;

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      <motion.div {...fadeUp}>
        <h1 className="text-2xl font-bold text-white flex items-center gap-3">
          <HiOutlineChartBar className="w-7 h-7 text-emerald-400" />
          Insights & Recommendations
        </h1>
        <p className="text-slate-400 mt-1">
          Behavioral trends, sleep/wake habits, productivity coaching, and challenge performance
        </p>
      </motion.div>

      {/* Behavioral analytics */}
      <motion.div {...fadeUp} transition={{ delay: 0.02 }} className="card">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <HiOutlineBellAlert className="w-5 h-5 text-sky-400" />
            Behavioral Analytics
          </h2>
          <span className="text-xs text-slate-400">
            Last {behavioral?.window_days ?? 30} days
          </span>
        </div>

        {(behavioral?.insights || []).length > 0 && (
          <div className="space-y-1.5 mb-5">
            {behavioral.insights.map((insight, i) => (
              <p key={i} className="text-sm text-slate-300 leading-relaxed">
                {insight}
              </p>
            ))}
          </div>
        )}

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          <MiniStat
            icon={HiOutlineBellAlert}
            label="Snoozes"
            value={snooze?.total_snoozes ?? 0}
          />
          <MiniStat
            icon={HiOutlineSun}
            label="Wake consistency"
            value={
              wake?.consistency_score != null
                ? Math.round(wake.consistency_score)
                : '—'
            }
          />
          <MiniStat
            icon={HiOutlineMoon}
            label="Schedule adherence"
            value={
              sleep?.adherence_rate != null
                ? `${Math.round(sleep.adherence_rate)}%`
                : '—'
            }
          />
          <MiniStat
            icon={HiOutlineTrophy}
            label="Habit score"
            value={
              habits?.current_habit_score != null
                ? Math.round(habits.current_habit_score)
                : '—'
            }
          />
        </div>

        <div className="grid md:grid-cols-3 gap-4 mb-5">
          <MetricBlock
            title="Snooze pattern"
            trend={snoozeTrend}
            TrendIcon={SnoozeTrendIcon}
            rows={[
              ['Avg / wake', snooze?.avg_snoozes_per_wake ?? 0],
              ['Limit hits', `${snooze?.limit_hit_rate ?? 0}%`],
              ['Peak day', snooze?.peak_weekday || '—'],
              ['Peak hour', snooze?.peak_hour != null ? `${snooze.peak_hour}:00` : '—'],
            ]}
          />
          <MetricBlock
            title="Wake-up consistency"
            trend={wakeTrend}
            TrendIcon={WakeTrendIcon}
            rows={[
              ['Verified wakes', wake?.verified_wakes ?? 0],
              ['Mean wake', wake?.mean_wake_time ? formatTimeDisplay(wake.mean_wake_time) : '—'],
              ['Std (min)', wake?.std_wake_minutes ?? '—'],
              ['On-time rate', `${wake?.on_time_rate ?? 0}%`],
            ]}
          />
          <MetricBlock
            title="Sleep schedule"
            trend={sleepTrend}
            TrendIcon={SleepTrendIcon}
            rows={[
              [
                'Preferred wake',
                sleep?.preferred_wake_time
                  ? formatTimeDisplay(sleep.preferred_wake_time)
                  : '—',
              ],
              [
                'Suggested bed',
                sleep?.suggested_bedtime
                  ? formatTimeDisplay(sleep.suggested_bedtime)
                  : '—',
              ],
              ['Adherent days', `${sleep?.adherent_days ?? 0}/${sleep?.observed_days ?? 0}`],
              ['Avg deviation', sleep?.avg_deviation_minutes != null ? `${sleep.avg_deviation_minutes}m` : '—'],
            ]}
          />
        </div>

        <div className="grid lg:grid-cols-2 gap-6 mb-5">
          <div>
            <h3 className="text-sm font-semibold text-white mb-3">Snoozes by weekday</h3>
            {weekdaySnoozeData.every((d) => d.snoozes === 0) ? (
              <p className="text-sm text-slate-500 py-8 text-center">
                Snooze an alarm to populate weekday patterns.
              </p>
            ) : (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={weekdaySnoozeData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="day" stroke="#94a3b8" tick={{ fontSize: 12 }} />
                    <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} allowDecimals={false} />
                    <Tooltip
                      contentStyle={{
                        background: '#1e293b',
                        border: '1px solid #334155',
                        borderRadius: 12,
                      }}
                      labelStyle={{ color: '#e2e8f0' }}
                    />
                    <Bar dataKey="snoozes" fill="#38bdf8" radius={[8, 8, 0, 0]} name="Snoozes" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div>
            <div className="flex items-center justify-between mb-3">
              <h3 className="text-sm font-semibold text-white">
                {trendView === 'monthly' ? 'Monthly' : 'Weekly'} trends
              </h3>
              <div className="flex gap-2">
                {['weekly', 'monthly'].map((view) => (
                  <button
                    key={view}
                    type="button"
                    onClick={() => setTrendView(view)}
                    className={`text-xs px-3 py-1.5 rounded-lg border transition ${
                      trendView === view
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
              <p className="text-sm text-slate-500 py-8 text-center">
                Complete wake cycles to see period trends.
              </p>
            ) : (
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={periodSeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="label" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                    <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} allowDecimals={false} />
                    <Tooltip
                      contentStyle={{
                        background: '#1e293b',
                        border: '1px solid #334155',
                        borderRadius: 12,
                      }}
                      labelStyle={{ color: '#e2e8f0' }}
                    />
                    <Legend />
                    <Line type="monotone" dataKey="verified_wakes" stroke="#34d399" strokeWidth={2} name="Wakes" dot={false} />
                    <Line type="monotone" dataKey="snoozes" stroke="#38bdf8" strokeWidth={2} name="Snoozes" dot={false} />
                    <Line type="monotone" dataKey="on_time_wakes" stroke="#fbbf24" strokeWidth={2} name="On time" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>

        <div>
          <div className="flex items-center justify-between mb-3">
            <h3 className="text-sm font-semibold text-white flex items-center gap-2">
              Habit trends
              <span className={`inline-flex items-center gap-1 text-xs ${habitTrend.color}`}>
                <HabitTrendIcon className="w-3.5 h-3.5" />
                {habitTrend.label}
              </span>
            </h3>
            <span className="text-xs text-slate-400">
              Avg proxy {habits?.avg_proxy_score ?? 0}
            </span>
          </div>
          {habitSeries.length === 0 ? (
            <p className="text-sm text-slate-500 py-6 text-center">
              Habit trend series fills in as you dismiss alarms and complete challenges.
            </p>
          ) : (
            <div className="h-52">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={habitSeries}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                  <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                  <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} domain={[0, 100]} />
                  <Tooltip
                    contentStyle={{
                      background: '#1e293b',
                      border: '1px solid #334155',
                      borderRadius: 12,
                    }}
                    labelStyle={{ color: '#e2e8f0' }}
                  />
                  <Line type="monotone" dataKey="score" stroke="#a78bfa" strokeWidth={2} name="Habit proxy" />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </div>
      </motion.div>

      {/* Lifestyle recommendation engine */}
      <motion.div {...fadeUp} transition={{ delay: 0.03 }} className="card">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <HiOutlineBolt className="w-5 h-5 text-amber-400" />
            Recommendation Engine
          </h2>
          {recommendations?.summary?.top_focus_label && (
            <span className="text-xs px-2.5 py-1 rounded-full bg-surface-700 text-slate-300">
              Focus: {recommendations.summary.top_focus_label}
            </span>
          )}
        </div>

        <div className="grid grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
          <MiniStat
            icon={HiOutlineMoon}
            label="Bedtime"
            value={recommendations?.summary?.suggested_bedtime
              ? formatTimeDisplay(recommendations.summary.suggested_bedtime)
              : '—'}
          />
          <MiniStat
            icon={HiOutlineSun}
            label="Wake goal"
            value={recommendations?.summary?.preferred_wake_time
              ? formatTimeDisplay(recommendations.summary.preferred_wake_time)
              : '—'}
          />
          <MiniStat
            icon={HiOutlineTrophy}
            label="Habit score"
            value={
              recommendations?.summary?.habit_score != null
                ? Math.round(recommendations.summary.habit_score)
                : '—'
            }
          />
          <MiniStat
            icon={HiOutlineSparkles}
            label="Goals"
            value={recommendations?.summary?.goals_count ?? 0}
          />
        </div>

        {(recommendations?.insights || []).length > 0 && (
          <div className="space-y-1.5 mb-5">
            {recommendations.insights.map((insight, i) => (
              <p key={i} className="text-sm text-slate-300 leading-relaxed">
                {insight}
              </p>
            ))}
          </div>
        )}

        {recommendations?.daily_plan?.priority_actions?.length > 0 && (
          <div className="rounded-xl border border-primary-500/20 bg-primary-500/5 p-4 mb-5">
            <p className="text-xs uppercase tracking-wider text-primary-300 mb-2">
              Daily plan
            </p>
            <p className="text-sm text-slate-200 mb-2">
              {recommendations.daily_plan.morning_focus}
            </p>
            <ul className="space-y-1">
              {recommendations.daily_plan.priority_actions.map((action, i) => (
                <li key={i} className="text-sm text-slate-400 flex gap-2">
                  <span className="text-primary-400">•</span>
                  {action}
                </li>
              ))}
            </ul>
          </div>
        )}

        <div className="flex flex-wrap gap-2 mb-4">
          {['all', 'sleep', 'wake', 'habit', 'productivity', 'challenge'].map((cat) => (
            <button
              key={cat}
              type="button"
              onClick={() => setRecFilter(cat)}
              className={`text-xs px-3 py-1.5 rounded-lg border transition ${
                recFilter === cat
                  ? 'bg-primary-500/20 text-primary-200 border-primary-500/40'
                  : 'bg-surface-800 text-slate-400 border-surface-700/50 hover:text-white'
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        <div className="space-y-3">
          {filteredRecs.length === 0 ? (
            <p className="text-sm text-slate-500 py-4 text-center">
              No recommendations in this category yet.
            </p>
          ) : (
            filteredRecs.map((rec) => (
              <div
                key={rec.id}
                className="rounded-xl border border-surface-700/60 bg-surface-800/40 p-4"
              >
                <div className="flex flex-wrap items-center gap-2 mb-1">
                  <span
                    className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border ${
                      LIFESTYLE_CATEGORY_STYLES[rec.category] || LIFESTYLE_CATEGORY_STYLES.habit
                    }`}
                  >
                    {rec.category}
                  </span>
                  <PriorityBadge priority={rec.priority} />
                  <p className="text-sm font-medium text-white">{rec.title}</p>
                </div>
                <p className="text-sm text-slate-400">{rec.detail}</p>
                {rec.action_path && (
                  <Link
                    to={rec.action_path}
                    className="inline-flex mt-2 text-xs text-primary-400 hover:text-primary-300"
                  >
                    {rec.action_hint || 'Take action'} →
                  </Link>
                )}
              </div>
            ))
          )}
        </div>
      </motion.div>

      {/* Challenge summary cards */}
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
              Challenge Recommendations
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

function MiniStat({ icon: Icon, label, value }) {
  return (
    <div className="rounded-xl border border-surface-700/40 bg-surface-900/40 px-3 py-2.5">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-500 mb-1">
        <Icon className="w-3.5 h-3.5" />
        {label}
      </div>
      <p className="text-sm font-semibold text-white truncate">{value}</p>
    </div>
  );
}

function MetricBlock({ title, trend, TrendIcon, rows }) {
  return (
    <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 p-4">
      <div className="flex items-center justify-between mb-3">
        <p className="text-sm font-medium text-white">{title}</p>
        <span className={`inline-flex items-center gap-1 text-[11px] ${trend.color}`}>
          <TrendIcon className="w-3.5 h-3.5" />
          {trend.label}
        </span>
      </div>
      <dl className="space-y-2">
        {rows.map(([label, value]) => (
          <div key={label} className="flex items-center justify-between text-sm gap-3">
            <dt className="text-slate-400">{label}</dt>
            <dd className="text-slate-200 font-medium truncate">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}
