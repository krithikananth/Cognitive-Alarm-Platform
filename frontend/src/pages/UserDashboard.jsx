/**
 * UserDashboard — personal dashboard: alarm history, wake-up stats, habit score
 * summary cards, challenge performance, and productivity insights.
 * Detailed habit charts live on WellnessCoachDashboard to avoid duplication.
 * Data from /dashboard/* and /analytics/* (no mock data, no new endpoints).
 */
import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  HiOutlineClock, HiOutlineTrophy, HiOutlineFire, HiOutlineChartBar,
  HiOutlinePuzzlePiece, HiOutlinePlus, HiOutlineBolt, HiOutlineSun, HiOutlineMoon,
  HiOutlineArrowPath, HiOutlineArrowTrendingUp, HiOutlineArrowTrendingDown,
  HiOutlineMinus, HiOutlineExclamationTriangle, HiOutlineClipboardDocumentList,
  HiOutlineCheckCircle, HiOutlineXCircle, HiOutlineChevronLeft, HiOutlineChevronRight,
  HiOutlineAcademicCap,
} from 'react-icons/hi2';
import {
  BarChart, Bar, LineChart, Line, PieChart, Pie, Cell,
  XAxis, YAxis, Tooltip, Legend, ResponsiveContainer, CartesianGrid,
} from 'recharts';
import useAuthStore from '../store/authStore';
import useAlarmStore from '../store/alarmStore';
import { userAPI, dashboardAPI, analyticsAPI } from '../services/api';
import { formatHabitScore } from '../utils/habitScore';

const CHART_TOOLTIP_STYLE = {
  contentStyle: { background: '#1e293b', border: '1px solid #334155', borderRadius: 12 },
  labelStyle: { color: '#e2e8f0' },
};

const CHALLENGE_TYPE_LABELS = {
  math: 'Math',
  logic: 'Logic',
  memory: 'Memory',
  word_game: 'Word',
  pattern: 'Pattern',
  riddle: 'Riddle',
  quiz: 'Quiz',
  random: 'Random',
};

function formatChallengeType(type) {
  if (!type) return '—';
  const key = String(type).toLowerCase();
  return CHALLENGE_TYPE_LABELS[key] || key.replace(/_/g, ' ');
}

function trendMeta(direction) {
  if (direction === 'improving') {
    return { Icon: HiOutlineArrowTrendingUp, label: 'Improving', color: 'text-emerald-400' };
  }
  if (direction === 'declining') {
    return { Icon: HiOutlineArrowTrendingDown, label: 'Declining', color: 'text-orange-400' };
  }
  if (direction === 'stable') {
    return { Icon: HiOutlineMinus, label: 'Stable', color: 'text-slate-300' };
  }
  return { Icon: HiOutlineMinus, label: 'Not enough data', color: 'text-slate-500' };
}

const EVENT_TYPE_META = {
  dismissed: { label: 'Dismissed', color: '#34d399', text: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20', Icon: HiOutlineCheckCircle },
  abandoned: { label: 'Abandoned', color: '#f87171', text: 'text-red-400', bg: 'bg-red-500/10 border-red-500/20', Icon: HiOutlineXCircle },
  snoozed: { label: 'Snoozed', color: '#fbbf24', text: 'text-amber-400', bg: 'bg-amber-500/10 border-amber-500/20', Icon: HiOutlineClock },
};

function hourLabel(h) {
  const period = h >= 12 ? 'P' : 'A';
  let hh = h % 12;
  if (hh === 0) hh = 12;
  return `${hh}${period}`;
}

function historyEventDetail(evt) {
  const d = evt.details || {};
  if (evt.event_type === 'dismissed') {
    const parts = [];
    if (d.dismiss_method) parts.push(`via ${String(d.dismiss_method).replace(/_/g, ' ')}`);
    if (d.challenges_required) parts.push(`${d.challenges_completed ?? 0}/${d.challenges_required} challenges`);
    if (d.snooze_count) parts.push(`${d.snooze_count} snooze${d.snooze_count === 1 ? '' : 's'}`);
    if (d.time_to_dismiss_seconds != null) parts.push(`${d.time_to_dismiss_seconds}s to dismiss`);
    return parts.join(' • ') || 'Verified wake-up';
  }
  if (evt.event_type === 'abandoned') {
    const parts = [];
    if (d.failed_attempts) parts.push(`${d.failed_attempts} failed attempt${d.failed_attempts === 1 ? '' : 's'}`);
    if (d.snooze_count) parts.push(`${d.snooze_count} snooze${d.snooze_count === 1 ? '' : 's'}`);
    return parts.join(' • ') || 'Alarm cycle abandoned';
  }
  if (evt.event_type === 'snoozed') {
    const parts = [`Snooze #${d.snooze_number ?? '?'}`];
    if (d.snooze_limit) parts.push(`of ${d.snooze_limit}`);
    return parts.join(' ');
  }
  return '';
}

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

const HISTORY_PER_PAGE = 6;

export default function UserDashboard() {
  const { user } = useAuthStore();
  const { alarms, fetchAlarms, fetchUpcoming } = useAlarmStore();

  const [stats, setStats] = useState(null);

  const [period, setPeriod] = useState('weekly'); // weekly=7d, monthly=30d
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [error, setError] = useState(null);

  const [summaryStats, setSummaryStats] = useState(null);
  const [wakeStats, setWakeStats] = useState(null);
  const [challengePerf, setChallengePerf] = useState(null);
  const [productivity, setProductivity] = useState(null);
  const [habitTrend, setHabitTrend] = useState(null);
  const [activityTrend, setActivityTrend] = useState(null);

  const [historyEvents, setHistoryEvents] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [historyPage, setHistoryPage] = useState(1);
  const [historyLoading, setHistoryLoading] = useState(true);
  const [historyError, setHistoryError] = useState(null);

  // Monotonic id so only the latest insights request may commit UI state
  // (covers rapid refresh clicks and weekly/monthly toggles).
  const requestIdRef = useRef(0);

  const loadStats = useCallback(() => {
    userAPI.getStats().then((res) => setStats(res.data)).catch(() => {});
  }, []);

  const loadInsights = useCallback(async (p) => {
    const requestId = ++requestIdRef.current;
    const days = p === 'monthly' ? 30 : 7;
    setRefreshing(true);
    try {
      const results = await Promise.allSettled([
        dashboardAPI.getSummary(p),
        dashboardAPI.getWakeStats(days),
        dashboardAPI.getChallengePerformance(days),
        dashboardAPI.getProductivity(days),
        analyticsAPI.getHabitTrends(days),
        analyticsAPI.getMonthlyTrends(days),
      ]);
      // Drop stale responses from an older period/refresh click.
      if (requestId !== requestIdRef.current) return;

      const [summaryRes, wakeRes, challengeRes, prodRes, habitRes, trendRes] = results;
      const allFailed = results.every((r) => r.status === 'rejected');

      setSummaryStats(summaryRes.status === 'fulfilled' ? summaryRes.value.data : null);
      setWakeStats(wakeRes.status === 'fulfilled' ? wakeRes.value.data : null);
      setChallengePerf(challengeRes.status === 'fulfilled' ? challengeRes.value.data : null);
      setProductivity(prodRes.status === 'fulfilled' ? prodRes.value.data : null);
      setHabitTrend(habitRes.status === 'fulfilled' ? habitRes.value.data : null);
      setActivityTrend(trendRes.status === 'fulfilled' ? trendRes.value.data : null);
      setError(allFailed ? 'Failed to load dashboard insights.' : null);
    } finally {
      if (requestId === requestIdRef.current) {
        setLoading(false);
        setRefreshing(false);
      }
    }
  }, []);

  const loadHistory = useCallback(async (page, p) => {
    setHistoryLoading(true);
    try {
      const days = p === 'monthly' ? 30 : 7;
      const { data } = await dashboardAPI.getAlarmHistory({ page, per_page: HISTORY_PER_PAGE, days });
      setHistoryEvents(data.events || []);
      setHistoryTotal(data.total || 0);
      setHistoryPage(data.page || page);
      setHistoryError(null);
    } catch {
      setHistoryEvents([]);
      setHistoryError('Failed to load alarm history.');
    } finally {
      setHistoryLoading(false);
    }
  }, []);

  const refresh = useCallback(() => {
    if (refreshing || loading) return;
    loadInsights(period);
    loadHistory(1, period);
  }, [refreshing, loading, loadInsights, loadHistory, period]);

  // Keep a ref to the latest refresh so the event listener (attached once)
  // never captures a stale `period` closure.
  const refreshRef = useRef(refresh);
  useEffect(() => {
    refreshRef.current = refresh;
  }, [refresh]);

  // Mount-once: fetch alarms/stats and wire real-time refresh after alarm
  // completion, snooze, or challenge completion, plus on window focus so
  // data never goes stale while the tab is backgrounded.
  useEffect(() => {
    fetchAlarms();
    fetchUpcoming();
    loadStats();
    const handleWakeCompleted = () => refreshRef.current();
    window.addEventListener('icap:wake-completed', handleWakeCompleted);
    window.addEventListener('focus', loadStats);
    return () => {
      window.removeEventListener('icap:wake-completed', handleWakeCompleted);
      window.removeEventListener('focus', loadStats);
    };
  }, [fetchAlarms, fetchUpcoming, loadStats]);

  // Fetch period-scoped insights + alarm history (page 1) on mount and
  // whenever the weekly/monthly toggle changes.
  useEffect(() => {
    loadInsights(period);
    loadHistory(1, period);
  }, [period, loadInsights, loadHistory]);

  const goToHistoryPage = (p) => {
    if (p < 1) return;
    loadHistory(p, period);
  };

  const greeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return { text: 'Good Morning', icon: HiOutlineSun, color: 'text-amber-400' };
    if (hour < 17) return { text: 'Good Afternoon', icon: HiOutlineSun, color: 'text-orange-400' };
    return { text: 'Good Evening', icon: HiOutlineMoon, color: 'text-indigo-400' };
  };
  const g = greeting();
  const GIcon = g.icon;

  // ── Chart data derivations ──
  const weekdayChartData = useMemo(
    () => (wakeStats?.by_weekday || []).map((r) => ({ day: r.weekday, wakes: r.count })),
    [wakeStats]
  );
  const hasWeekdayActivity = weekdayChartData.some((d) => d.wakes > 0);

  const hourlyChartData = useMemo(
    () => (wakeStats?.by_hour || []).map((r) => ({ hour: hourLabel(r.hour), count: r.count })),
    [wakeStats]
  );
  const hasHourlyActivity = hourlyChartData.length > 0;

  const activitySeries = useMemo(
    () => (activityTrend?.series || []).map((r) => ({ ...r, label: (r.date || '').slice(5) })),
    [activityTrend]
  );
  const hasActivityData = activitySeries.some((d) => d.verified_wakes || d.snoozes || d.on_time_wakes);

  const periodStats = summaryStats?.period_stats || null;

  const historyBreakdownData = useMemo(() => [
    { name: 'Dismissed', value: wakeStats?.verified_wakes || 0, key: 'dismissed' },
    { name: 'Abandoned', value: wakeStats?.abandoned_wakes || 0, key: 'abandoned' },
    { name: 'Snoozed', value: periodStats?.total_snoozes || 0, key: 'snoozed' },
  ], [wakeStats, periodStats]);
  const hasHistoryBreakdown = historyBreakdownData.some((d) => d.value > 0);

  const challengeTypeData = useMemo(
    () => Object.entries(challengePerf?.by_type || {}).map(([type, s]) => ({
      type: formatChallengeType(type),
      accuracy: s.accuracy,
      attempts: s.total,
    })),
    [challengePerf]
  );

  const challengeCompareData = useMemo(() => {
    if (!challengePerf?.trend) return [];
    return [
      { name: 'Previous', accuracy: challengePerf.trend.previous_accuracy },
      { name: 'Recent', accuracy: challengePerf.trend.recent_accuracy },
    ];
  }, [challengePerf]);

  const productivityMetricsData = useMemo(() => {
    if (!productivity) return [];
    return [
      { metric: 'Routine', score: productivity.morning_routine_score },
      { metric: 'Cognitive', score: productivity.cognitive_readiness_score },
      { metric: 'Consistency', score: productivity.consistency_rate },
    ];
  }, [productivity]);

  const productivityCompareData = useMemo(() => {
    if (!productivity?.trend) return [];
    return [
      { name: 'Previous', rate: productivity.trend.previous_clean_wake_rate },
      { name: 'Recent', rate: productivity.trend.recent_clean_wake_rate },
    ];
  }, [productivity]);

  const habitScoreTrendMeta = trendMeta(habitTrend?.trend);
  const HabitTrendIcon = habitScoreTrendMeta.Icon;
  const challengeTrendMeta = trendMeta(challengePerf?.trend?.direction);
  const ChallengeTrendIcon = challengeTrendMeta.Icon;
  const productivityTrendMeta = trendMeta(productivity?.trend?.direction);
  const ProductivityTrendIcon = productivityTrendMeta.Icon;

  const habitWeights = habitTrend?.weights || {
    wake_up_consistency: 0.35,
    challenge_completion: 0.25,
    snooze_reduction: 0.2,
    sleep_adherence: 0.2,
  };
  const habitBreakdown = habitTrend?.current_breakdown || summaryStats?.habit_score_breakdown || null;
  const currentHabitScore = habitTrend?.current_habit_score ?? stats?.current_habit_score;

  const historyTotalPages = Math.max(1, Math.ceil(historyTotal / HISTORY_PER_PAGE));

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* ─── Greeting Header ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0 }} className="flex items-center justify-between">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <GIcon className={`w-6 h-6 ${g.color}`} />
            <h1 className="text-2xl font-bold text-white font-display">{g.text}</h1>
          </div>
          <p className="text-slate-400">
            {user?.full_name || user?.username}, here&apos;s your personal dashboard
          </p>
        </div>
        <Link to="/alarms" className="btn-primary flex items-center gap-2 text-sm">
          <HiOutlinePlus className="w-4 h-4" />
          New Alarm
        </Link>
      </motion.div>

      {/* ─── Stats Row ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.05 }} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={HiOutlineClock}
          label="Active Alarms"
          value={stats?.active_alarms != null ? stats.active_alarms : '—'}
          color="from-primary-500 to-primary-700"
        />
        <StatCard
          icon={HiOutlineTrophy}
          label="Habit Score"
          value={formatHabitScore(currentHabitScore)}
          color="from-accent-500 to-accent-700"
        />
        <StatCard
          icon={HiOutlineFire}
          label="Day Streak"
          value={stats?.current_streak != null ? stats.current_streak : '—'}
          color="from-orange-500 to-red-600"
          hint="Consecutive successful wake-up days"
        />
        <StatCard
          icon={HiOutlineChartBar}
          label="Success Rate"
          value={stats?.wakeup_success_rate != null ? `${Math.round(stats.wakeup_success_rate)}%` : '—'}
          color="from-emerald-500 to-teal-600"
        />
      </motion.div>

      {/* ─── Period Toggle ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.08 }} className="flex flex-wrap items-center justify-between gap-3">
        <p className="text-sm text-slate-400">
          Showing data for the {period === 'monthly' ? 'last 30 days' : 'last 7 days'}
        </p>
        <div className="flex items-center gap-2">
          <div className="flex gap-2">
            {['weekly', 'monthly'].map((view) => (
              <button
                key={view}
                type="button"
                onClick={() => setPeriod(view)}
                className={`text-xs px-3 py-1.5 rounded-lg border transition capitalize ${
                  period === view
                    ? 'bg-primary-500/20 text-primary-200 border-primary-500/40'
                    : 'bg-surface-800 text-slate-400 border-surface-700/50 hover:text-white'
                }`}
              >
                {view}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={refresh}
            disabled={refreshing || loading}
            title="Refresh dashboard"
            aria-label="Refresh dashboard"
            className="relative z-10 p-1.5 rounded-lg border border-surface-700/50 bg-surface-800 text-slate-400 hover:text-white transition disabled:opacity-50 disabled:cursor-not-allowed cursor-pointer"
          >
            <HiOutlineArrowPath className={`w-4 h-4 pointer-events-none ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </motion.div>

      {error && (
        <p className="text-xs text-red-400/80">{error}</p>
      )}

      {/* ─── 1. Alarm History ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.1 }} className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <HiOutlineClipboardDocumentList className="w-5 h-5 text-sky-400" />
            Alarm History
          </h2>
          <span className="text-xs text-slate-400">
            {historyTotal} event{historyTotal === 1 ? '' : 's'} in this period
          </span>
        </div>

        <div className="grid lg:grid-cols-3 gap-6 mb-5">
          {/* Activity breakdown */}
          <div>
            <h3 className="text-sm font-semibold text-white mb-3">Activity Breakdown</h3>
            {loading ? (
              <div className="h-48 rounded-xl bg-surface-900/40 animate-pulse" />
            ) : !hasHistoryBreakdown ? (
              <p className="text-sm text-slate-500 py-10 text-center">
                No alarm activity yet in this period.
              </p>
            ) : (
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={historyBreakdownData}
                      dataKey="value"
                      nameKey="name"
                      innerRadius={40}
                      outerRadius={65}
                      paddingAngle={3}
                    >
                      {historyBreakdownData.map((d) => (
                        <Cell key={d.key} fill={EVENT_TYPE_META[d.key].color} />
                      ))}
                    </Pie>
                    <Tooltip {...CHART_TOOLTIP_STYLE} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                  </PieChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          {/* Activity trend */}
          <div className="lg:col-span-2">
            <h3 className="text-sm font-semibold text-white mb-3">Alarm Activity Trend</h3>
            {loading ? (
              <div className="h-48 rounded-xl bg-surface-900/40 animate-pulse" />
            ) : !hasActivityData ? (
              <p className="text-sm text-slate-500 py-10 text-center">
                No activity trend yet. Complete wake cycles to populate this chart.
              </p>
            ) : (
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={activitySeries}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="label" stroke="#94a3b8" tick={{ fontSize: 10 }} />
                    <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} allowDecimals={false} />
                    <Tooltip {...CHART_TOOLTIP_STYLE} />
                    <Legend wrapperStyle={{ fontSize: 11 }} />
                    <Line type="monotone" dataKey="verified_wakes" stroke="#34d399" strokeWidth={2} name="Dismissed" dot={false} />
                    <Line type="monotone" dataKey="snoozes" stroke="#fbbf24" strokeWidth={2} name="Snoozed" dot={false} />
                    <Line type="monotone" dataKey="on_time_wakes" stroke="#38bdf8" strokeWidth={2} name="On time" dot={false} />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>
        </div>

        {/* Timeline */}
        <div className="border-t border-surface-700/30 pt-4">
          <h3 className="text-sm font-semibold text-white mb-3">Recent Activity</h3>
          {historyLoading ? (
            <div className="space-y-2">
              {Array.from({ length: 4 }).map((_, i) => (
                <div key={i} className="h-14 rounded-xl bg-surface-900/40 animate-pulse" />
              ))}
            </div>
          ) : historyError ? (
            <div className="text-center py-8">
              <HiOutlineExclamationTriangle className="w-8 h-8 text-red-400/70 mx-auto mb-2" />
              <p className="text-sm text-slate-400 mb-3">{historyError}</p>
              <button type="button" onClick={() => loadHistory(historyPage, period)} className="btn-secondary text-sm">
                Try again
              </button>
            </div>
          ) : historyEvents.length === 0 ? (
            <p className="text-sm text-slate-500 py-8 text-center">
              No alarm history in this period yet. Ring and dismiss an alarm to start building your history.
            </p>
          ) : (
            <>
              <div className="space-y-2">
                {historyEvents.map((evt) => {
                  const meta = EVENT_TYPE_META[evt.event_type] || EVENT_TYPE_META.dismissed;
                  const Icon = meta.Icon;
                  return (
                    <div key={evt.id} className={`flex items-center gap-3 p-3 rounded-xl border ${meta.bg}`}>
                      <div className={`w-9 h-9 rounded-lg flex items-center justify-center bg-surface-900/50 flex-shrink-0 ${meta.text}`}>
                        <Icon className="w-5 h-5" />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <span className={`text-sm font-medium ${meta.text}`}>{meta.label}</span>
                          <span className="text-xs text-slate-500">Alarm #{evt.alarm_id}</span>
                        </div>
                        <p className="text-xs text-slate-400 truncate">{historyEventDetail(evt)}</p>
                      </div>
                      <span className="text-xs text-slate-500 whitespace-nowrap">
                        {evt.timestamp ? new Date(evt.timestamp).toLocaleString() : '—'}
                      </span>
                    </div>
                  );
                })}
              </div>

              <div className="flex items-center justify-between mt-4 pt-3 border-t border-surface-700/30">
                <span className="text-xs text-slate-500">Page {historyPage} of {historyTotalPages}</span>
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => goToHistoryPage(historyPage - 1)}
                    disabled={historyPage <= 1}
                    aria-label="Previous page"
                    className="p-1.5 rounded-lg border border-surface-700/50 bg-surface-800 text-slate-400 hover:text-white transition disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <HiOutlineChevronLeft className="w-4 h-4" />
                  </button>
                  <button
                    type="button"
                    onClick={() => goToHistoryPage(historyPage + 1)}
                    disabled={historyPage >= historyTotalPages}
                    aria-label="Next page"
                    className="p-1.5 rounded-lg border border-surface-700/50 bg-surface-800 text-slate-400 hover:text-white transition disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    <HiOutlineChevronRight className="w-4 h-4" />
                  </button>
                </div>
              </div>
            </>
          )}
        </div>
      </motion.div>

      {/* ─── 2. Wake-up Statistics ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.14 }} className="card">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2 mb-4">
          <HiOutlineSun className="w-5 h-5 text-amber-400" />
          Wake-up Statistics
        </h2>
        <div className="grid lg:grid-cols-3 gap-6">
          <div>
            <h3 className="text-sm font-semibold text-white mb-3">By Weekday</h3>
            {loading ? (
              <div className="h-48 rounded-xl bg-surface-900/40 animate-pulse" />
            ) : !hasWeekdayActivity ? (
              <p className="text-sm text-slate-500 py-10 text-center">No weekday pattern yet.</p>
            ) : (
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={weekdayChartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="day" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                    <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} allowDecimals={false} />
                    <Tooltip {...CHART_TOOLTIP_STYLE} />
                    <Bar dataKey="wakes" fill="#38bdf8" radius={[8, 8, 0, 0]} name="Wakes" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div>
            <h3 className="text-sm font-semibold text-white mb-3">By Hour of Day</h3>
            {loading ? (
              <div className="h-48 rounded-xl bg-surface-900/40 animate-pulse" />
            ) : !hasHourlyActivity ? (
              <p className="text-sm text-slate-500 py-10 text-center">No hourly pattern yet.</p>
            ) : (
              <div className="h-48">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={hourlyChartData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="hour" stroke="#94a3b8" tick={{ fontSize: 10 }} interval={1} />
                    <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} allowDecimals={false} />
                    <Tooltip {...CHART_TOOLTIP_STYLE} />
                    <Bar dataKey="count" fill="#a78bfa" radius={[8, 8, 0, 0]} name="Wake-ups" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </div>

          <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 p-4">
            <p className="text-sm font-medium text-white mb-3">Key Metrics</p>
            {!wakeStats || wakeStats.total_wake_events === 0 ? (
              <p className="text-xs text-slate-500 py-4 text-center">
                No wake events yet. Ring your alarm and complete a verified wake-up to populate these stats.
              </p>
            ) : (
              <dl className="space-y-2">
                <Row label="Success rate" value={`${wakeStats.success_rate}%`} />
                <Row label="First-try rate" value={`${wakeStats.first_try_success_rate}%`} />
                <Row
                  label="Avg dismiss time"
                  value={wakeStats.avg_time_to_dismiss_seconds != null ? `${wakeStats.avg_time_to_dismiss_seconds}s` : '—'}
                />
                <Row label="Avg snoozes" value={wakeStats.avg_snoozes_before_dismiss ?? 0} />
                <Row label="Avg failed attempts" value={wakeStats.avg_failed_attempts ?? 0} />
              </dl>
            )}
          </div>
        </div>
      </motion.div>

      {/* ─── 3. Habit Score (summary cards; detailed charts live on Wellness Coach) ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.18 }} className="card">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <HiOutlineTrophy className="w-5 h-5 text-accent-400" />
            Habit Score
          </h2>
          <div className="flex items-center gap-3">
            <span className={`inline-flex items-center gap-1 text-[11px] ${habitScoreTrendMeta.color}`}>
              <HabitTrendIcon className="w-3.5 h-3.5" />
              {habitScoreTrendMeta.label}
            </span>
            {user?.role === 'wellness_coach' && (
              <Link
                to="/wellness"
                className="text-xs text-primary-300 hover:text-primary-200 transition"
              >
                Detailed analytics →
              </Link>
            )}
          </div>
        </div>

        <div className="grid sm:grid-cols-2 lg:grid-cols-5 gap-3">
          <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 p-4 sm:col-span-2 lg:col-span-1 flex flex-col justify-center">
            <p className="text-xs text-slate-400 uppercase tracking-wider mb-2">Current</p>
            <div className="flex items-end gap-1.5 mb-3">
              <span className="text-3xl font-bold gradient-accent bg-clip-text text-transparent">
                {currentHabitScore != null ? Math.round(currentHabitScore) : 0}
              </span>
              <span className="text-slate-400 text-sm mb-0.5">/ 100</span>
            </div>
            <div className="w-full bg-surface-700 rounded-full h-1.5">
              <div
                className="h-1.5 rounded-full gradient-accent transition-all duration-1000"
                style={{ width: `${Math.min(100, Math.max(0, currentHabitScore || 0))}%` }}
              />
            </div>
          </div>

          {[
            { key: 'wake_up_consistency', label: 'Wake consistency', accent: 'text-amber-300' },
            { key: 'challenge_completion', label: 'Challenges', accent: 'text-violet-300' },
            { key: 'snooze_reduction', label: 'Snooze control', accent: 'text-sky-300' },
            { key: 'sleep_adherence', label: 'Sleep adherence', accent: 'text-indigo-300' },
          ].map((row) => {
            const score = habitBreakdown ? Number(habitBreakdown[row.key] ?? 0) : null;
            const weight = Math.round((habitWeights[row.key] || 0) * 100);
            return (
              <div
                key={row.key}
                className="rounded-xl border border-surface-700/50 bg-surface-900/30 p-4 flex flex-col justify-center"
              >
                <p className="text-xs text-slate-400 mb-1">{row.label}</p>
                <p className={`text-2xl font-semibold ${row.accent}`}>
                  {score != null ? Math.round(score) : '—'}
                </p>
                <p className="text-[10px] text-slate-600 mt-1">{weight}% of score</p>
              </div>
            );
          })}
        </div>

        {!habitBreakdown && (
          <p className="text-xs text-slate-500 mt-3 text-center">
            Complete your first verified wake-up to unlock component scores.
          </p>
        )}
      </motion.div>

      {/* ─── 4. Challenge Performance ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.22 }} className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <HiOutlinePuzzlePiece className="w-5 h-5 text-violet-400" />
            Challenge Performance
          </h2>
          {challengePerf?.total_attempts > 0 && (
            <span className={`inline-flex items-center gap-1 text-[11px] ${challengeTrendMeta.color}`}>
              <ChallengeTrendIcon className="w-3.5 h-3.5" />
              {challengeTrendMeta.label}
            </span>
          )}
        </div>
        {!challengePerf || challengePerf.total_attempts === 0 ? (
          <p className="text-sm text-slate-500 py-8 text-center">
            No challenge attempts yet in this period. Solve a challenge when your alarm rings to see charts here.
          </p>
        ) : (
          <div className="grid lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
              <h3 className="text-sm font-semibold text-white mb-3">Accuracy by Challenge Type</h3>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={challengeTypeData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="type" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                    <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} domain={[0, 100]} />
                    <Tooltip {...CHART_TOOLTIP_STYLE} />
                    <Bar dataKey="accuracy" fill="#a78bfa" radius={[8, 8, 0, 0]} name="Accuracy %" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 p-4">
              <p className="text-sm font-medium text-white mb-3">Key Metrics</p>
              <dl className="space-y-2">
                <Row label="Overall accuracy" value={`${challengePerf.accuracy}%`} />
                <Row label="Attempts" value={challengePerf.total_attempts} />
                <Row label="Points earned" value={challengePerf.total_points_earned} />
                <Row label="Best type" value={formatChallengeType(challengePerf.best_type)} />
                <Row label="Worst type" value={formatChallengeType(challengePerf.worst_type)} />
              </dl>
            </div>

            {challengeCompareData.length > 0 && (
              <div className="lg:col-span-3">
                <h3 className="text-sm font-semibold text-white mb-3">Recent vs Previous Accuracy</h3>
                <div className="h-36">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={challengeCompareData} layout="vertical" margin={{ left: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis type="number" domain={[0, 100]} stroke="#94a3b8" tick={{ fontSize: 11 }} />
                      <YAxis type="category" dataKey="name" stroke="#94a3b8" tick={{ fontSize: 12 }} width={70} />
                      <Tooltip {...CHART_TOOLTIP_STYLE} />
                      <Bar dataKey="accuracy" radius={[0, 8, 8, 0]} name="Accuracy %">
                        {challengeCompareData.map((d, i) => (
                          <Cell key={d.name} fill={i === 0 ? '#64748b' : '#34d399'} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>
        )}
      </motion.div>

      {/* ─── 5. Productivity Insights ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.26 }} className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <HiOutlineAcademicCap className="w-5 h-5 text-sky-400" />
            Productivity Insights
          </h2>
          {productivity?.verified_wakes > 0 && (
            <span className={`inline-flex items-center gap-1 text-[11px] ${productivityTrendMeta.color}`}>
              <ProductivityTrendIcon className="w-3.5 h-3.5" />
              {productivityTrendMeta.label}
            </span>
          )}
        </div>
        {!productivity || productivity.verified_wakes === 0 ? (
          <p className="text-sm text-slate-500 py-8 text-center">
            No productivity data yet. Complete your first verified wake-up to unlock these charts.
          </p>
        ) : (
          <div className="grid lg:grid-cols-3 gap-6">
            <div className="lg:col-span-2">
              <h3 className="text-sm font-semibold text-white mb-3">Productivity Metrics</h3>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={productivityMetricsData}>
                    <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                    <XAxis dataKey="metric" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                    <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} domain={[0, 100]} />
                    <Tooltip {...CHART_TOOLTIP_STYLE} />
                    <Bar dataKey="score" radius={[8, 8, 0, 0]} name="Score">
                      {productivityMetricsData.map((d, i) => (
                        <Cell key={d.metric} fill={['#38bdf8', '#a78bfa', '#34d399'][i]} />
                      ))}
                    </Bar>
                  </BarChart>
                </ResponsiveContainer>
              </div>
            </div>

            <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 p-4">
              <p className="text-sm font-medium text-white mb-3">Key Metrics</p>
              <dl className="space-y-2">
                <Row label="Active days" value={`${productivity.active_days_in_period}/${productivity.days}`} />
                <Row label="Current streak" value={productivity.current_streak} />
                <Row label="Challenge accuracy" value={`${productivity.challenge_accuracy}%`} />
                <Row label="Avg wakefulness" value={productivity.avg_wakefulness ?? '—'} />
                <Row
                  label="Avg time to productive"
                  value={productivity.avg_time_to_productive_seconds != null ? `${productivity.avg_time_to_productive_seconds}s` : '—'}
                />
              </dl>
            </div>

            {productivityCompareData.length > 0 && (
              <div className="lg:col-span-3">
                <h3 className="text-sm font-semibold text-white mb-3">Clean Wake Rate: Recent vs Previous</h3>
                <div className="h-36">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={productivityCompareData} layout="vertical" margin={{ left: 10 }}>
                      <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                      <XAxis type="number" domain={[0, 100]} stroke="#94a3b8" tick={{ fontSize: 11 }} />
                      <YAxis type="category" dataKey="name" stroke="#94a3b8" tick={{ fontSize: 12 }} width={70} />
                      <Tooltip {...CHART_TOOLTIP_STYLE} />
                      <Bar dataKey="rate" radius={[0, 8, 8, 0]} name="Clean wake rate %">
                        {productivityCompareData.map((d, i) => (
                          <Cell key={d.name} fill={i === 0 ? '#64748b' : '#fbbf24'} />
                        ))}
                      </Bar>
                    </BarChart>
                  </ResponsiveContainer>
                </div>
              </div>
            )}
          </div>
        )}
      </motion.div>

      {/* ─── Upcoming Alarms + Quick Actions ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <motion.div {...fadeUp} transition={{ delay: 0.3 }} className="lg:col-span-2 card">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-lg font-semibold text-white flex items-center gap-2">
              <HiOutlineClock className="w-5 h-5 text-primary-400" />
              Upcoming Alarms
            </h2>
            <Link to="/alarms" className="text-sm text-primary-400 hover:text-primary-300 transition">View all →</Link>
          </div>

          {alarms.length === 0 ? (
            <div className="text-center py-12">
              <HiOutlineClock className="w-12 h-12 text-slate-600 mx-auto mb-3" />
              <p className="text-slate-400 mb-1">No alarms set yet</p>
              <p className="text-sm text-slate-500 mb-4 max-w-sm mx-auto">
                Create your first alarm to start tracking wake-ups, challenges, and analytics.
              </p>
              <Link to="/alarms" className="btn-primary text-sm inline-flex items-center gap-2">
                <HiOutlinePlus className="w-4 h-4" /> Create Your First Alarm
              </Link>
            </div>
          ) : (
            <div className="space-y-3">
              {alarms.filter((a) => a.is_active).slice(0, 5).map((alarm) => (
                <div key={alarm.id} className="flex items-center justify-between p-4 rounded-xl bg-surface-900/50 border border-surface-700/30 hover:border-primary-500/20 transition-all">
                  <div className="flex items-center gap-4">
                    <div className="w-12 h-12 rounded-xl bg-primary-500/10 flex items-center justify-center">
                      <span className="text-lg font-bold text-primary-400">{alarm.alarm_time?.slice(0, 5)}</span>
                    </div>
                    <div>
                      <p className="text-sm font-medium text-white">{alarm.label || 'Alarm'}</p>
                      <div className="flex items-center gap-2 mt-0.5">
                        <span className="badge-primary text-[10px]">{alarm.alarm_type}</span>
                        {alarm.challenge_type && (
                          <span className="badge-warning text-[10px]">{alarm.challenge_type}</span>
                        )}
                      </div>
                    </div>
                  </div>
                  <div className={`w-2.5 h-2.5 rounded-full ${alarm.is_active ? 'bg-emerald-400' : 'bg-slate-600'}`} />
                </div>
              ))}
            </div>
          )}
        </motion.div>

        <motion.div {...fadeUp} transition={{ delay: 0.35 }} className="card">
          <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <HiOutlineBolt className="w-5 h-5 text-amber-400" />
            Quick Actions
          </h2>
          <div className="space-y-3">
            <QuickAction icon={HiOutlinePlus} label="Create Alarm" to="/alarms" color="primary" />
            <QuickAction icon={HiOutlinePuzzlePiece} label="Practice Challenge" to="/practice" color="accent" />
            {user?.role === 'wellness_coach' && (
              <QuickAction icon={HiOutlineAcademicCap} label="Wellness Coach" to="/wellness" color="accent" />
            )}
            <QuickAction icon={HiOutlineChartBar} label="View Analytics" to="/analytics" color="emerald" />
            <QuickAction icon={HiOutlineTrophy} label="View Reports" to="/reports" color="orange" />
          </div>
        </motion.div>
      </div>
    </div>
  );
}

// ─── Sub-components ───

function StatCard({ icon: Icon, label, value, color, hint }) {
  return (
    <div className="stat-card" title={hint || undefined}>
      <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${color} flex items-center justify-center mb-2`}>
        <Icon className="w-5 h-5 text-white" />
      </div>
      <p className="stat-value">{value}</p>
      <p className="text-sm text-slate-400">{label}</p>
      {hint ? <p className="text-xs text-slate-500 mt-1">{hint}</p> : null}
    </div>
  );
}

function QuickAction({ icon: Icon, label, to, onClick, color }) {
  const colorMap = {
    primary: 'bg-primary-500/10 text-primary-400 border-primary-500/20',
    accent: 'bg-accent-500/10 text-accent-400 border-accent-500/20',
    emerald: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/20',
    orange: 'bg-orange-500/10 text-orange-400 border-orange-500/20',
  };

  const className = `flex items-center gap-3 p-3 rounded-xl border transition-all hover:scale-[1.02] ${colorMap[color]}`;

  if (onClick) {
    return (
      <button onClick={onClick} className={`${className} w-full text-left`}>
        <Icon className="w-5 h-5" />
        <span className="text-sm font-medium text-white">{label}</span>
      </button>
    );
  }

  return (
    <Link to={to} className={className}>
      <Icon className="w-5 h-5" />
      <span className="text-sm font-medium text-white">{label}</span>
    </Link>
  );
}

function Row({ label, value }) {
  return (
    <div className="flex items-center justify-between text-sm gap-3">
      <dt className="text-slate-400">{label}</dt>
      <dd className="text-slate-200 font-medium truncate capitalize">{value}</dd>
    </div>
  );
}
