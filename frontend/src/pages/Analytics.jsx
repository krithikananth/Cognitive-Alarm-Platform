/**
 * Analytics — challenge performance deep-dive.
 * Lifestyle / sleep / habit coaching lives on Wellness Coach (/wellness).
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
import useAuthStore from '../store/authStore';
import ActivityHealthPanel from '../components/analytics/ActivityHealthPanel';

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

const LEARNING_STATE_META = {
  improving: { label: 'Improving', tone: 'text-emerald-400' },
  plateaued: { label: 'Plateaued', tone: 'text-amber-400' },
  declining: { label: 'Declining', tone: 'text-red-400' },
  volatile: { label: 'Volatile', tone: 'text-orange-400' },
  struggling: { label: 'Struggling', tone: 'text-red-400' },
  steady: { label: 'Steady', tone: 'text-sky-400' },
  insufficient_data: { label: 'Warming up', tone: 'text-slate-400' },
};

const ENGAGEMENT_META = {
  thriving: { label: 'Thriving', tone: 'text-emerald-400' },
  engaged: { label: 'Engaged', tone: 'text-teal-400' },
  steady: { label: 'Steady', tone: 'text-sky-400' },
  at_risk: { label: 'At risk', tone: 'text-amber-400' },
  disengaged: { label: 'Disengaged', tone: 'text-red-400' },
  insufficient_data: { label: 'Warming up', tone: 'text-slate-400' },
};

const MASTERY_TONE = {
  mastered: 'text-emerald-400',
  proficient: 'text-teal-400',
  developing: 'text-amber-400',
  novice: 'text-red-400',
  unrated: 'text-slate-500',
};

const ADAPTATION_META = {
  effective: { label: 'Working', tone: 'text-emerald-400' },
  neutral: { label: 'No clear effect', tone: 'text-slate-400' },
  ineffective: { label: 'Not helping', tone: 'text-amber-400' },
  insufficient_data: { label: 'Warming up', tone: 'text-slate-400' },
};

const ENGAGEMENT_TREND_META = {
  improving: { label: 'Improving', tone: 'text-emerald-400' },
  stable: { label: 'Holding steady', tone: 'text-sky-400' },
  declining: { label: 'Declining', tone: 'text-amber-400' },
  insufficient_data: { label: 'Warming up', tone: 'text-slate-400' },
};

function formatHour(hour) {
  const value = Number(hour);
  if (Number.isNaN(value)) return '—';
  const suffix = value >= 12 ? 'PM' : 'AM';
  const display = value % 12 === 0 ? 12 : value % 12;
  return `${display}${suffix}`;
}

function formatBias(bias) {
  if (bias > 0) return 'Raising difficulty by one level';
  if (bias < 0) return 'Easing difficulty by one level';
  return 'No difficulty change';
}

function formatTrend(value, unit) {
  const number = Number(value || 0);
  const sign = number > 0 ? '+' : '';
  return `${sign}${number}${unit}`;
}

export default function Analytics() {
  const { user } = useAuthStore();
  const [stats, setStats] = useState(null);
  const [analysis, setAnalysis] = useState(null);
  const [learningProfile, setLearningProfile] = useState(null);
  const [history, setHistory] = useState([]);
  const [historyTotal, setHistoryTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      setLoading(true);
      try {
        const [statsRes, analysisRes, historyRes, learningRes] = await Promise.all([
          alarmAPI.getChallengeStats(),
          alarmAPI.getChallengeAnalysis(),
          alarmAPI.getChallengeHistory({ page, per_page: 15 }),
          alarmAPI.getLearningProfile(),
        ]);
        if (cancelled) return;
        setStats(statsRes.data);
        setAnalysis(analysisRes.data);
        setLearningProfile(learningRes.data);
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

  // The dedicated learning-profile route is what the challenge engine reads at
  // ring time; the analysis payload stays as a fallback.
  const patterns =
    learningProfile?.learning_patterns || analysis?.personalization?.learning_patterns;
  const engagement =
    learningProfile?.engagement || analysis?.personalization?.engagement;
  const learningMeta =
    LEARNING_STATE_META[patterns?.learning_state] ||
    LEARNING_STATE_META.insufficient_data;
  const adaptation = patterns?.adaptation_effectiveness;
  const adaptationMeta =
    ADAPTATION_META[adaptation?.verdict] || ADAPTATION_META.insufficient_data;
  const engagementMeta =
    ENGAGEMENT_META[engagement?.state] || ENGAGEMENT_META.insufficient_data;
  const engagementTrend = engagement?.improvement;
  const engagementTrendMeta =
    ENGAGEMENT_TREND_META[engagementTrend?.direction] ||
    ENGAGEMENT_TREND_META.insufficient_data;

  const masteryRows = useMemo(
    () =>
      Object.values(patterns?.by_type || {})
        .filter((t) => t.mastery && t.mastery !== 'unrated')
        .sort((a, b) => (b.accuracy ?? 0) - (a.accuracy ?? 0)),
    [patterns]
  );

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
      <motion.div {...fadeUp} className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-3">
            <HiOutlineChartBar className="w-7 h-7 text-emerald-400" />
            Challenge Analytics
          </h1>
          <p className="text-slate-400 mt-1">
            Accuracy, personalization, and attempt history for wake-up challenges
          </p>
        </div>
        {user?.role === 'wellness_coach' && (
          <Link to="/wellness" className="btn-secondary text-sm">
            Wellness Coach →
          </Link>
        )}
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
        <motion.div {...fadeUp} transition={{ delay: 0.1 }} className="lg:col-span-2 space-y-6">
          <div className="card">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                <HiOutlineLightBulb className="w-5 h-5 text-amber-400" />
                Completion Analysis
              </h2>
              <span className="inline-flex items-center gap-1.5 text-xs px-2.5 py-1 rounded-full bg-surface-700 text-slate-300">
                <TrendIcon className="w-3.5 h-3.5" />
                {summary.trend_label || 'Need more attempts'}
              </span>
            </div>

            <div className="space-y-2 mb-5">
              {(analysis?.insights || []).length === 0 ? (
                <p className="text-sm text-slate-500">
                  No insights yet. Complete a few challenges after your alarm to unlock completion analysis.
                </p>
              ) : (
                (analysis?.insights || []).map((insight, i) => (
                  <p key={i} className="text-sm text-slate-300 leading-relaxed">
                    {insight}
                  </p>
                ))
              )}
            </div>

            <div className="grid sm:grid-cols-2 gap-4 mb-5">
              <div className="rounded-xl border border-emerald-500/20 bg-emerald-500/5 p-4">
                <p className="text-xs uppercase tracking-wider text-emerald-400 mb-2">Strengths</p>
                {(analysis?.strengths || []).length === 0 ? (
                  <p className="text-sm text-slate-500">
                    No strengths detected yet. Complete a few more challenges to reveal where you perform best.
                  </p>
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
                  <p className="text-sm text-slate-500">
                    No weak spots identified yet. Keep solving challenges — we&apos;ll flag types that need practice once we have enough data.
                  </p>
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
              {(analysis?.recommendations || []).length === 0 ? (
                <p className="text-sm text-slate-500 py-2">
                  No challenge tips yet. Solve a few challenges after your alarm to unlock personalized practice advice.
                </p>
              ) : (
                (analysis?.recommendations || []).map((rec, i) => (
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
                ))
              )}
            </div>
          </div>

          <div className="card">
            <h2 className="text-lg font-semibold text-white mb-4">Accuracy by Challenge Type</h2>
            {typeChartData.length === 0 ? (
              <p className="text-sm text-slate-500 py-8 text-center">
                No type breakdown yet. Complete challenges of different types when your alarm rings to see accuracy by type.
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

        <motion.div {...fadeUp} transition={{ delay: 0.15 }} className="space-y-6">
          <div className="card">
            <h2 className="text-lg font-semibold text-white mb-3">Personalization</h2>
            <p className="text-xs text-slate-400 mb-3 uppercase tracking-wider">
              Adaptive difficulty
            </p>
            {!analysis?.personalization?.adaptive_difficulty?.started ? (
              <p className="text-sm text-slate-300">
                Adaptive difficulty has not started yet. Complete 5 verified challenges after wake-ups to unlock personalized difficulty.
              </p>
            ) : (
              <>
                <p className="text-sm text-slate-300 mb-4">
                  {analysis?.personalization?.adaptive_difficulty?.reason ||
                    'Adaptive difficulty shifts after 5 consecutive wake completions or failures.'}
                </p>
                <div className="flex items-center justify-between text-sm mb-4">
                  <span className="text-slate-400">Success streak</span>
                  <span className="text-white font-medium">
                    {analysis?.personalization?.adaptive_difficulty?.success_streak ?? 0}
                  </span>
                </div>
                <div className="flex items-center justify-between text-sm mb-4">
                  <span className="text-slate-400">Failure streak</span>
                  <span className="text-white font-medium">
                    {analysis?.personalization?.adaptive_difficulty?.failure_streak ?? 0}
                  </span>
                </div>
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
                    <span className="text-sm text-slate-500">
                      No preferred types yet. Complete challenges across types so we can learn what works best for you.
                    </span>
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
              </>
            )}
          </div>

          <div className="card">
            <div className="flex items-center justify-between mb-3">
              <h2 className="text-lg font-semibold text-white">Learning Patterns</h2>
              <span className={`text-xs font-medium ${learningMeta.tone}`}>
                {learningMeta.label}
              </span>
            </div>

            {!patterns?.has_enough_data ? (
              <p className="text-sm text-slate-300">
                {patterns?.learning_state_label ||
                  'Learning analysis unlocks after your first few challenges.'}
              </p>
            ) : (
              <>
                <p className="text-sm text-slate-300 mb-4">
                  {patterns.learning_state_label}
                </p>

                <div className="grid grid-cols-2 gap-3 mb-4">
                  <div className="rounded-xl bg-surface-800/60 p-3">
                    <p className="text-[11px] text-slate-400 uppercase tracking-wider">
                      Accuracy trend
                    </p>
                    <p className="text-sm text-white font-medium mt-1">
                      {formatTrend(patterns.accuracy_trend_pp_per_10, ' pts')}
                    </p>
                    <p className="text-[11px] text-slate-500">per 10 attempts</p>
                  </div>
                  <div className="rounded-xl bg-surface-800/60 p-3">
                    <p className="text-[11px] text-slate-400 uppercase tracking-wider">
                      Speed trend
                    </p>
                    <p className="text-sm text-white font-medium mt-1">
                      {formatTrend(patterns.speed_trend_seconds_per_10, 's')}
                    </p>
                    <p className="text-[11px] text-slate-500">per 10 attempts</p>
                  </div>
                  <div className="rounded-xl bg-surface-800/60 p-3">
                    <p className="text-[11px] text-slate-400 uppercase tracking-wider">
                      Consistency
                    </p>
                    <p className="text-sm text-white font-medium mt-1">
                      {patterns.consistency == null ? '—' : `${patterns.consistency}`}
                    </p>
                    <p className="text-[11px] text-slate-500">50 – 100 scale</p>
                  </div>
                  <div className="rounded-xl bg-surface-800/60 p-3">
                    <p className="text-[11px] text-slate-400 uppercase tracking-wider">
                      Best-fit level
                    </p>
                    <p className="text-sm text-accent-400 font-medium capitalize mt-1">
                      {patterns.optimal_difficulty || '—'}
                    </p>
                    <p className="text-[11px] text-slate-500">
                      {patterns.sample_size} attempts analysed
                    </p>
                  </div>
                </div>

                {adaptation && (
                  <div
                    className="rounded-xl border border-surface-700/50 bg-surface-900/40 p-3 mb-4"
                    title={`Each time the served difficulty changed, accuracy over the ${adaptation.window} attempts before is compared with the ${adaptation.window} after. An adaptation counts as effective when it moved you closer to the ${adaptation.target_band.low}–${adaptation.target_band.high}% target band — not simply when accuracy rose, since a harder level is meant to bring accuracy down.`}
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <p className="text-[11px] text-slate-400 uppercase tracking-wider">
                        Difficulty adaptation effectiveness
                      </p>
                      <p className={`text-sm font-medium ${adaptationMeta.tone}`}>
                        {adaptationMeta.label}
                      </p>
                    </div>
                    {adaptation.verdict === 'insufficient_data' ? (
                      <p className="text-xs text-slate-500 mt-1">
                        {adaptation.adaptations_detected} difficulty change
                        {adaptation.adaptations_detected === 1 ? '' : 's'} so far —
                        needs {adaptation.min_events} with at least{' '}
                        {adaptation.min_side_sample} attempts on each side.
                      </p>
                    ) : (
                      <>
                        <p className="text-sm text-white font-medium mt-1">
                          {adaptation.effectiveness_rate}% of {adaptation.adaptations_judged}{' '}
                          adaptations moved you toward the target band
                        </p>
                        <p className="text-[11px] text-slate-500 mt-1">
                          Accuracy {adaptation.avg_accuracy_before}% →{' '}
                          {adaptation.avg_accuracy_after}% · distance from band{' '}
                          {adaptation.avg_band_distance_before} →{' '}
                          {adaptation.avg_band_distance_after} pts
                        </p>
                      </>
                    )}
                  </div>
                )}

                {masteryRows.length > 0 && (
                  <>
                    <p className="text-xs text-slate-400 mb-2 uppercase tracking-wider">
                      Mastery by type
                    </p>
                    <div className="space-y-2 mb-4">
                      {masteryRows.map((row) => (
                        <div
                          key={row.type}
                          className="flex items-center justify-between text-sm"
                        >
                          <span className="text-slate-300">{formatType(row.type)}</span>
                          <span className="flex items-center gap-2">
                            <span className="text-slate-400 text-xs">
                              {row.accuracy}% · {formatTrend(row.trend_pp_per_10, '')}
                            </span>
                            <span
                              className={`text-xs capitalize ${MASTERY_TONE[row.mastery] || 'text-slate-400'
                                }`}
                            >
                              {row.mastery}
                            </span>
                          </span>
                        </div>
                      ))}
                    </div>
                  </>
                )}

                {(patterns.time_of_day?.peak_hours?.length > 0 ||
                  patterns.time_of_day?.low_hours?.length > 0) && (
                    <>
                      <p className="text-xs text-slate-400 mb-2 uppercase tracking-wider">
                        Time of day
                      </p>
                      <div className="space-y-1 mb-4 text-sm">
                        {patterns.time_of_day.peak_hours?.length > 0 && (
                          <p className="text-slate-300">
                            Sharpest around{' '}
                            <span className="text-emerald-400">
                              {patterns.time_of_day.peak_hours.map(formatHour).join(', ')}
                            </span>
                          </p>
                        )}
                        {patterns.time_of_day.low_hours?.length > 0 && (
                          <p className="text-slate-300">
                            Weakest around{' '}
                            <span className="text-amber-400">
                              {patterns.time_of_day.low_hours.map(formatHour).join(', ')}
                            </span>
                          </p>
                        )}
                      </div>
                    </>
                  )}
              </>
            )}

            <p className="text-xs text-slate-400 mb-2 uppercase tracking-wider">
              Engagement
            </p>
            <div className="flex items-center justify-between text-sm mb-2">
              <span className="text-slate-400">State</span>
              <span className={`font-medium ${engagementMeta.tone}`}>
                {engagementMeta.label}
                {engagement?.state !== 'insufficient_data' &&
                  ` · ${engagement?.engagement_score ?? 0}`}
              </span>
            </div>
            <div className="flex items-center justify-between text-sm mb-2">
              <span className="text-slate-400">Engine action</span>
              <span className="text-white">
                {formatBias(engagement?.directives?.difficulty_bias ?? 0)}
              </span>
            </div>
            <div
              className="flex items-center justify-between text-sm mb-2"
              title={`Your engagement score now against the same score recomputed as it stood ${engagementTrend?.period_days ?? 14
                } days ago, so the difference is a real change in how you have been using the app.`}
            >
              <span className="text-slate-400">vs {engagementTrend?.period_days ?? 14}d ago</span>
              <span className={`font-medium ${engagementTrendMeta.tone}`}>
                {engagementTrend?.status === 'ok'
                  ? `${engagementTrendMeta.label} · ${engagementTrend.change > 0 ? '+' : ''
                  }${engagementTrend.change}`
                  : engagementTrendMeta.label}
              </span>
            </div>
            {engagementTrend?.status === 'ok' && (
              <p className="text-xs text-slate-500 mb-2">
                {engagementTrend.previous_score} → {engagementTrend.current_score}
                {engagementTrend.improvement_rate == null
                  ? ''
                  : ` (${engagementTrend.improvement_rate > 0 ? '+' : ''}${engagementTrend.improvement_rate
                  }%)`}
                {' · '}
                {engagementTrend.previous_attempts} → {engagementTrend.current_attempts}{' '}
                attempts
              </p>
            )}
            <p className="text-xs text-slate-400">
              {engagement?.directives?.reason ||
                'Engagement tuning starts once you have a few wake-ups logged.'}
            </p>
          </div>

          <div className="card">
            <h2 className="text-lg font-semibold text-white mb-3">By Difficulty</h2>
            <div className="space-y-3">
              {Object.entries(analysis?.by_difficulty || stats?.by_difficulty || {}).length === 0 ? (
                <p className="text-sm text-slate-500">
                  No difficulty data yet. Solve challenges at easy, medium, or hard when your alarm rings to populate this.
                </p>
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
            No attempts logged yet. Ring an alarm and solve a challenge to start your challenge history.
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
                        className={`text-xs px-2 py-0.5 rounded-full ${row.is_correct
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

      <ActivityHealthPanel />
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
