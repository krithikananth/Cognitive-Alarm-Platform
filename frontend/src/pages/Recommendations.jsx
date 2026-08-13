/**
 * Recommendations — the personalized coaching feed the rule engine generates
 * from the signed-in user's own profile, alarms, wake events and challenge
 * attempts.
 *
 * Two requests, deliberately separate so one failing never blanks the other:
 *   GET /recommendations       → full feed + by_category + summary + insights
 *   GET /recommendations/daily → the top-5 digest and today's plan
 *
 * Category filtering of the card list is done client-side against `by_category`,
 * which the backend already returns for every category. Selecting Sleep,
 * Wake-up or Productivity additionally loads that category's dedicated
 * endpoint, which returns the insights scoped to that category — the combined
 * feed only carries the un-scoped insight list.
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { motion } from 'framer-motion';
import {
  HiOutlineArrowPath,
  HiOutlineArrowRight,
  HiOutlineCalendarDays,
  HiOutlineCheckCircle,
  HiOutlineExclamationTriangle,
  HiOutlineFire,
  HiOutlineHandThumbDown,
  HiOutlineHandThumbUp,
  HiOutlineLightBulb,
  HiOutlineMoon,
  HiOutlineSparkles,
  HiOutlineSun,
  HiOutlineTrophy,
  HiOutlineXMark,
} from 'react-icons/hi2';
import { recommendationAPI, readErrorDetail } from '../services/api';
import { formatTimeDisplay } from '../utils/timeFormat';
import { formatHabitScore } from '../utils/habitScore';

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

const CATEGORIES = ['sleep', 'wake', 'habit', 'productivity', 'challenge'];

const CATEGORY_LABELS = {
  sleep: 'Sleep',
  wake: 'Wake-up',
  habit: 'Habit',
  productivity: 'Productivity',
  challenge: 'Challenge',
};

const CATEGORY_STYLES = {
  sleep: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/25',
  wake: 'bg-amber-500/15 text-amber-300 border-amber-500/25',
  habit: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/25',
  productivity: 'bg-sky-500/15 text-sky-300 border-sky-500/25',
  challenge: 'bg-violet-500/15 text-violet-300 border-violet-500/25',
};

const PRIORITY_STYLES = {
  high: 'bg-red-500/15 text-red-400',
  medium: 'bg-amber-500/15 text-amber-400',
  low: 'bg-slate-500/20 text-slate-300',
};

/**
 * Categories with a dedicated endpoint that returns category-scoped insights.
 * `wake` deliberately covers wake + habit coaching, which is how the backend
 * groups it.
 */
const CATEGORY_ENDPOINTS = {
  sleep: () => recommendationAPI.getSleep(),
  wake: () => recommendationAPI.getWake(),
  productivity: () => recommendationAPI.getProductivity(),
};

function PanelError({ message, onRetry }) {
  return (
    <div
      role="alert"
      className="flex flex-wrap items-center justify-between gap-3 rounded-xl border border-red-500/30 bg-red-500/5 px-4 py-4"
    >
      <div className="flex items-center gap-2 text-sm text-red-300">
        <HiOutlineExclamationTriangle className="w-5 h-5 flex-shrink-0" />
        {message || 'This section could not be loaded.'}
      </div>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="inline-flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border border-surface-700/60 bg-surface-800 text-slate-300 hover:text-white transition"
        >
          <HiOutlineArrowPath className="w-3.5 h-3.5" />
          Try again
        </button>
      ) : null}
    </div>
  );
}

function SummaryStat({ icon: Icon, label, value, hint }) {
  return (
    <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 px-3 py-3">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-500 mb-1">
        <Icon className="w-3.5 h-3.5" />
        {label}
      </div>
      <p className="text-sm font-semibold text-white truncate">{value}</p>
      {hint ? <p className="text-xs text-slate-500 mt-0.5 truncate">{hint}</p> : null}
    </div>
  );
}

const FEEDBACK_BUTTONS = [
  { rating: 'helpful', label: 'Helpful', Icon: HiOutlineHandThumbUp, active: 'text-emerald-300' },
  {
    rating: 'not_helpful',
    label: 'Not helpful',
    Icon: HiOutlineHandThumbDown,
    active: 'text-red-300',
  },
  { rating: 'dismissed', label: 'Dismiss', Icon: HiOutlineXMark, active: 'text-slate-300' },
];

function RecommendationCard({ rec, onRate, pending }) {
  const dismissed = rec.feedback === 'dismissed';
  return (
    <div
      className={`rounded-xl border border-surface-700/50 bg-surface-900/40 p-4 flex flex-col transition ${dismissed ? 'opacity-60' : ''
        }`}
    >
      <div className="flex flex-wrap items-center gap-2 mb-1.5">
        <span
          className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border ${CATEGORY_STYLES[rec.category] || CATEGORY_STYLES.habit
            }`}
        >
          {CATEGORY_LABELS[rec.category] || rec.category}
        </span>
        <span
          className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full ${PRIORITY_STYLES[rec.priority] || PRIORITY_STYLES.low
            }`}
        >
          {rec.priority}
        </span>
      </div>
      <p className="text-sm font-medium text-white mb-1">{rec.title}</p>
      <p className="text-sm text-slate-400 leading-relaxed flex-1">{rec.detail}</p>
      {rec.action_hint ? (
        <div className="mt-3 pt-3 border-t border-surface-700/30">
          {rec.action_path ? (
            <Link
              to={rec.action_path}
              className="inline-flex items-center gap-1.5 text-xs font-medium text-primary-300 hover:text-primary-200 transition"
            >
              {rec.action_hint}
              <HiOutlineArrowRight className="w-3.5 h-3.5" />
            </Link>
          ) : (
            <span className="text-xs text-slate-500">{rec.action_hint}</span>
          )}
        </div>
      ) : null}
      <div className="mt-3 pt-3 border-t border-surface-700/30 flex flex-wrap items-center gap-1">
        <span className="text-[11px] text-slate-500 mr-1">Was this useful?</span>
        {FEEDBACK_BUTTONS.map(({ rating, label, Icon, active }) => {
          const selected = rec.feedback === rating;
          return (
            <button
              key={rating}
              type="button"
              disabled={pending}
              aria-pressed={selected}
              aria-label={`${label}: ${rec.title}`}
              title={
                selected ? `${label} — click again to undo` : label
              }
              onClick={() => onRate(rec.id, rating, selected)}
              className={`inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-lg border transition disabled:opacity-50 ${selected
                ? `border-surface-600 bg-surface-800 ${active}`
                : 'border-surface-700/60 text-slate-500 hover:text-white'
                }`}
            >
              <Icon className="w-3.5 h-3.5" />
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export default function Recommendations() {
  const [feed, setFeed] = useState(null);
  const [digest, setDigest] = useState(null);
  const [relevance, setRelevance] = useState(null);
  const [feedError, setFeedError] = useState(null);
  const [digestError, setDigestError] = useState(null);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [category, setCategory] = useState('all');
  const [focus, setFocus] = useState({});
  const [focusLoading, setFocusLoading] = useState(false);
  const [pendingId, setPendingId] = useState(null);

  const load = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);

    const [feedRes, digestRes, relevanceRes] = await Promise.allSettled([
      recommendationAPI.getAll(),
      recommendationAPI.getDaily(),
      recommendationAPI.getRelevance(),
    ]);

    if (feedRes.status === 'fulfilled') {
      setFeed(feedRes.value.data);
      setFeedError(null);
    } else {
      setFeed(null);
      // A blank server `detail` must not read as "no error" — keep a message.
      setFeedError(
        (await readErrorDetail(feedRes.reason, '')) ||
        'Your recommendations could not be loaded.'
      );
    }

    if (digestRes.status === 'fulfilled') {
      setDigest(digestRes.value.data);
      setDigestError(null);
    } else {
      setDigest(null);
      setDigestError(
        (await readErrorDetail(digestRes.reason, '')) ||
        "Today's plan could not be loaded."
      );
    }

    // Relevance is a read-out of past feedback; a failure here must not blank
    // the advice itself.
    setRelevance(relevanceRes.status === 'fulfilled' ? relevanceRes.value.data : null);

    setLoading(false);
    setRefreshing(false);
  }, []);

  const applyRating = useCallback((id, rating) => {
    const patch = (list) =>
      (list || []).map((r) => (r.id === id ? { ...r, feedback: rating } : r));
    setFeed((prev) =>
      prev
        ? {
          ...prev,
          recommendations: patch(prev.recommendations),
          by_category: Object.fromEntries(
            Object.entries(prev.by_category || {}).map(([k, v]) => [k, patch(v)])
          ),
        }
        : prev
    );
    setDigest((prev) =>
      prev ? { ...prev, recommendations: patch(prev.recommendations) } : prev
    );
  }, []);

  const rate = useCallback(
    async (id, rating, isUndo) => {
      const next = isUndo ? null : rating;
      setPendingId(id);
      try {
        if (isUndo) await recommendationAPI.clearFeedback(id);
        else await recommendationAPI.sendFeedback(id, rating);
        applyRating(id, next);
        const fresh = await recommendationAPI.getRelevance();
        setRelevance(fresh.data);
      } catch {
        // Leave the card as-is; the stored verdict is the source of truth.
      } finally {
        setPendingId(null);
      }
    },
    [applyRating]
  );

  useEffect(() => {
    load(false);
  }, [load]);

  // Category-scoped insights come from the dedicated endpoints; the combined
  // feed only carries the un-scoped list. Cached per category for the session.
  useEffect(() => {
    const request = CATEGORY_ENDPOINTS[category];
    if (!request || focus[category] !== undefined) return undefined;

    let cancelled = false;
    setFocusLoading(true);
    request()
      .then(({ data }) => {
        if (!cancelled) setFocus((prev) => ({ ...prev, [category]: data }));
      })
      .catch(() => {
        // The cards below still render from the combined feed.
        if (!cancelled) setFocus((prev) => ({ ...prev, [category]: null }));
      })
      .finally(() => {
        if (!cancelled) setFocusLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [category, focus]);

  const counts = useMemo(() => {
    const byCat = feed?.by_category || {};
    const all = feed?.recommendations || [];
    return CATEGORIES.reduce((acc, key) => {
      acc[key] = (byCat[key] || []).length || all.filter((r) => r.category === key).length;
      return acc;
    }, {});
  }, [feed]);

  const visible = useMemo(() => {
    const all = feed?.recommendations || [];
    if (category === 'all') return all;
    const byCat = feed?.by_category || {};
    return (byCat[category] || []).length
      ? byCat[category]
      : all.filter((r) => r.category === category);
  }, [feed, category]);

  const summary = feed?.summary || digest?.summary || {};
  const plan = digest?.daily_plan || feed?.daily_plan || {};
  const insights = feed?.insights || digest?.insights || [];
  const totalCount = feed?.recommendations?.length || 0;

  if (loading) {
    return (
      <div className="flex items-center justify-center py-24" role="status" aria-live="polite">
        <div className="w-10 h-10 border-4 border-primary-500 border-t-transparent rounded-full animate-spin" />
        <span className="sr-only">Loading your recommendations</span>
      </div>
    );
  }

  return (
    <div className="max-w-7xl mx-auto space-y-6">
      {/* ─── Header ─── */}
      <motion.div
        {...fadeUp}
        className="flex flex-wrap items-start justify-between gap-3"
      >
        <div>
          <h1 className="text-2xl font-bold text-white flex items-center gap-2">
            <HiOutlineLightBulb className="w-6 h-6 text-amber-400" />
            Recommendations
          </h1>
          <p className="text-slate-400">
            Personalized sleep, wake-up, habit, productivity, and challenge coaching
          </p>
        </div>
        <button
          type="button"
          onClick={() => load(true)}
          disabled={refreshing}
          className="btn-secondary text-sm inline-flex items-center gap-2 disabled:opacity-50 disabled:cursor-not-allowed"
          title="Refresh recommendations"
        >
          <HiOutlineArrowPath className={`w-4 h-4 ${refreshing ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </motion.div>

      {/* ─── Today's plan (daily digest) ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.05 }} className="card">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2 mb-1">
          <HiOutlineCalendarDays className="w-5 h-5 text-primary-400" />
          Today&apos;s Plan
        </h2>
        <p className="text-xs text-slate-500 mb-4">
          The highest-priority actions for today, plus the schedule they assume.
        </p>

        {digestError && !digest ? (
          <PanelError message={digestError} onRetry={() => load(true)} />
        ) : (
          <>
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
              <SummaryStat
                icon={HiOutlineMoon}
                label="Suggested bedtime"
                value={
                  plan.suggested_bedtime ? formatTimeDisplay(plan.suggested_bedtime) : '—'
                }
              />
              <SummaryStat
                icon={HiOutlineSun}
                label="Wake goal"
                value={
                  plan.suggested_wake_time
                    ? formatTimeDisplay(plan.suggested_wake_time)
                    : '—'
                }
              />
              <SummaryStat
                icon={HiOutlineSparkles}
                label="Morning focus"
                value={plan.morning_focus || summary.top_focus_label || '—'}
              />
              <SummaryStat
                icon={HiOutlineTrophy}
                label="Habit score"
                value={formatHabitScore(summary.habit_score)}
                hint={`Streak ${summary.streak_days ?? 0}d · best ${summary.best_streak ?? 0}d`}
              />
            </div>

            {(plan.priority_actions || []).length > 0 && (
              <div className="rounded-xl border border-surface-700/40 bg-surface-900/30 p-4 mb-5">
                <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">
                  Priority actions
                </p>
                <ul className="space-y-2">
                  {plan.priority_actions.map((action) => (
                    <li key={action} className="flex items-start gap-2 text-sm text-slate-200">
                      <HiOutlineCheckCircle className="w-4 h-4 text-emerald-400 flex-shrink-0 mt-0.5" />
                      {action}
                    </li>
                  ))}
                </ul>
              </div>
            )}

            {(digest?.recommendations || []).length === 0 ? (
              <p className="text-sm text-slate-500 py-4 text-center">
                No coaching items for today yet. Set a wake goal, arm an alarm, and complete a
                verified wake-up to unlock personalized advice.
              </p>
            ) : (
              <div className="grid lg:grid-cols-2 gap-3">
                {digest.recommendations.map((rec) => (
                  <RecommendationCard
                    key={rec.id}
                    rec={rec}
                    onRate={rate}
                    pending={pendingId === rec.id}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </motion.div>

      {/* ─── Insights ─── */}
      {insights.length > 0 && (
        <motion.div {...fadeUp} transition={{ delay: 0.1 }} className="card">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2 mb-3">
            <HiOutlineFire className="w-5 h-5 text-orange-400" />
            What your data shows
          </h2>
          <ul className="space-y-2">
            {insights.map((line) => (
              <li key={line} className="flex items-start gap-2 text-sm text-slate-300">
                <span className="w-1.5 h-1.5 rounded-full bg-primary-400 flex-shrink-0 mt-1.5" />
                {line}
              </li>
            ))}
          </ul>
        </motion.div>
      )}

      {/* ─── Full feed with category filter ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.15 }} className="card">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-1">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <HiOutlineLightBulb className="w-5 h-5 text-amber-400" />
            All Recommendations
          </h2>
          <span className="text-xs px-2.5 py-1 rounded-full bg-surface-700 text-slate-300">
            {totalCount} item{totalCount === 1 ? '' : 's'}
          </span>
        </div>
        <p className="text-xs text-slate-500 mb-4">
          Generated from your wake consistency, snooze frequency, challenge accuracy, sleep
          target, habit score, and saved productivity goals.
        </p>

        {feedError && !feed ? (
          <PanelError message={feedError} onRetry={() => load(true)} />
        ) : (
          <>
            <div className="flex flex-wrap gap-2 mb-5">
              <button
                type="button"
                onClick={() => setCategory('all')}
                aria-pressed={category === 'all'}
                className={`text-xs px-3 py-1.5 rounded-full border transition ${category === 'all'
                  ? 'bg-primary-600/20 text-primary-200 border-primary-500/40'
                  : 'bg-surface-800/60 text-slate-400 border-surface-700/60 hover:text-white'
                  }`}
              >
                All · {totalCount}
              </button>
              {CATEGORIES.map((key) => (
                <button
                  key={key}
                  type="button"
                  onClick={() => setCategory(key)}
                  aria-pressed={category === key}
                  className={`text-xs px-3 py-1.5 rounded-full border transition ${category === key
                    ? CATEGORY_STYLES[key]
                    : 'bg-surface-800/60 text-slate-400 border-surface-700/60 hover:text-white'
                    }`}
                >
                  {CATEGORY_LABELS[key]} · {counts[key] ?? 0}
                </button>
              ))}
            </div>

            {CATEGORY_ENDPOINTS[category] ? (
              <div className="rounded-xl border border-surface-700/40 bg-surface-900/30 p-4 mb-5">
                <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">
                  {CATEGORY_LABELS[category]} focus
                </p>
                {focus[category] === undefined && focusLoading ? (
                  <p className="text-sm text-slate-500">Loading focused insights…</p>
                ) : (focus[category]?.insights || []).length > 0 ? (
                  <ul className="space-y-1.5">
                    {focus[category].insights.map((line) => (
                      <li
                        key={line}
                        className="flex items-start gap-2 text-sm text-slate-300"
                      >
                        <span className="w-1.5 h-1.5 rounded-full bg-primary-400 flex-shrink-0 mt-1.5" />
                        {line}
                      </li>
                    ))}
                  </ul>
                ) : (
                  <p className="text-sm text-slate-500">
                    No {CATEGORY_LABELS[category].toLowerCase()}-specific insights yet.
                  </p>
                )}
              </div>
            ) : null}

            {visible.length === 0 ? (
              <p className="text-sm text-slate-500 py-8 text-center">
                {totalCount === 0
                  ? 'No recommendations yet. The engine needs a wake goal, an active alarm, or a few verified wake-ups before it can advise.'
                  : `No ${CATEGORY_LABELS[category] || category} recommendations in this feed right now.`}
              </p>
            ) : (
              <div className="grid lg:grid-cols-2 gap-3">
                {visible.map((rec) => (
                  <RecommendationCard
                    key={rec.id}
                    rec={rec}
                    onRate={rate}
                    pending={pendingId === rec.id}
                  />
                ))}
              </div>
            )}
          </>
        )}
      </motion.div>

      {/* ─── Measured relevance (from the ratings above) ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.2 }} className="card">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2 mb-1">
          <HiOutlineHandThumbUp className="w-5 h-5 text-emerald-400" />
          How relevant has this advice been?
        </h2>
        <p className="text-xs text-slate-500 mb-4">
          Measured from your own ratings — the share of cards you marked helpful out of
          those you judged either way. Dismissals are counted separately.
        </p>

        {!relevance || relevance.status !== 'ok' ? (
          <p className="text-sm text-slate-500 py-4 text-center">
            {relevance?.rated
              ? `Rate ${relevance.min_responses - relevance.rated} more recommendation${relevance.min_responses - relevance.rated === 1 ? '' : 's'
              } to see how relevant your advice has been.`
              : `Rate at least ${relevance?.min_responses ?? 3
              } recommendations as helpful or not helpful to unlock this.`}
          </p>
        ) : (
          <>
            <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
              <SummaryStat
                icon={HiOutlineHandThumbUp}
                label="Relevance"
                value={`${relevance.relevance_rate}%`}
                hint={`${relevance.helpful} of ${relevance.rated} rated helpful`}
              />
              <SummaryStat
                icon={HiOutlineHandThumbDown}
                label="Not helpful"
                value={relevance.not_helpful}
              />
              <SummaryStat
                icon={HiOutlineXMark}
                label="Dismissed"
                value={relevance.dismissed}
                hint="Not counted in the rate"
              />
              <SummaryStat
                icon={HiOutlineSparkles}
                label="Engine confidence"
                value={
                  relevance.avg_stated_confidence == null
                    ? '—'
                    : `${relevance.avg_stated_confidence}%`
                }
                hint={
                  relevance.confidence_gap == null
                    ? 'Claimed on the cards you rated'
                    : `${relevance.confidence_gap > 0 ? '+' : ''}${relevance.confidence_gap
                    } pts vs measured`
                }
              />
            </div>

            {Object.keys(relevance.by_category || {}).length > 0 && (
              <div className="rounded-xl border border-surface-700/40 bg-surface-900/30 p-4">
                <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">
                  By category
                </p>
                <ul className="space-y-1.5">
                  {Object.entries(relevance.by_category).map(([key, bucket]) => (
                    <li
                      key={key}
                      className="flex items-center justify-between text-sm text-slate-300"
                    >
                      <span>{CATEGORY_LABELS[key] || key}</span>
                      <span className="text-xs text-slate-400">
                        {bucket.rated
                          ? `${bucket.relevance_rate}% · ${bucket.helpful}/${bucket.rated}`
                          : `${bucket.dismissed} dismissed`}
                      </span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </>
        )}
      </motion.div>
    </div>
  );
}
