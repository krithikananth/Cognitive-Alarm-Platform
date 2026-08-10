/**
 * Recommendations — the full rule-engine feed for one client, grouped by
 * category, with per-category counts and the plan summary figures.
 *
 * Source: GET /coach/clients/{id}/recommendations. Coaches receive every
 * category rather than the 5-item client digest, so the panel can group.
 */
import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineLightBulb,
  HiOutlineMoon,
  HiOutlineSparkles,
  HiOutlineSun,
  HiOutlineTrophy,
} from 'react-icons/hi2';
import { MiniStat, PanelError, RecCard } from './primitives';
import { CATEGORY_STYLES, fadeUp } from './constants';
import { formatTimeDisplay } from '../../utils/timeFormat';
import { formatHabitScore } from '../../utils/habitScore';

const CATEGORIES = ['sleep', 'wake', 'habit', 'challenge', 'productivity'];

export default function Recommendations({ digest, error, onRetry }) {
  const grouped = useMemo(() => {
    const byCat = digest?.by_category || {};
    const all = digest?.recommendations || [];
    return CATEGORIES.map((category) => ({
      category,
      items: (byCat[category] || []).length
        ? byCat[category]
        : all.filter((r) => r.category === category),
    })).filter((group) => group.items.length > 0);
  }, [digest]);

  const summary = useMemo(() => {
    const byCat = digest?.by_category || {};
    const fromCards = (digest?.recommendations || []).reduce((acc, rec) => {
      acc[rec.category] = (acc[rec.category] || 0) + 1;
      return acc;
    }, {});
    return CATEGORIES.map((category) => ({
      category,
      count: (byCat[category] || []).length || fromCards[category] || 0,
    }));
  }, [digest]);

  return (
    <motion.div {...fadeUp} transition={{ delay: 0.25 }} className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-1">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlineLightBulb className="w-5 h-5 text-amber-400" />
          Recommendations
        </h2>
        {digest?.summary?.top_focus_label && (
          <span className="text-xs px-2.5 py-1 rounded-full bg-surface-700 text-slate-300">
            Focus: {digest.summary.top_focus_label}
          </span>
        )}
      </div>
      <p className="text-xs text-slate-500 mb-4">
        Rule-engine output for this client only — driven by wake consistency, snooze frequency,
        challenge accuracy, sleep adherence, habit-score movement, activity level, and saved
        productivity goals.
      </p>

      {error && !digest ? (
        <PanelError message={error} onRetry={onRetry} />
      ) : (
        <>
          <div className="grid grid-cols-2 sm:grid-cols-5 gap-2 mb-5">
            {summary.map((row) => (
              <div
                key={row.category}
                className={`rounded-xl border px-3 py-2 ${
                  CATEGORY_STYLES[row.category] || CATEGORY_STYLES.habit
                }`}
              >
                <p className="text-[10px] uppercase tracking-wider opacity-80">{row.category}</p>
                <p className="text-lg font-semibold text-white">{row.count}</p>
              </div>
            ))}
          </div>

          <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-5">
            <MiniStat
              icon={HiOutlineMoon}
              label="Bedtime"
              value={
                digest?.summary?.suggested_bedtime
                  ? formatTimeDisplay(digest.summary.suggested_bedtime)
                  : '—'
              }
            />
            <MiniStat
              icon={HiOutlineSun}
              label="Wake goal"
              value={
                digest?.summary?.preferred_wake_time
                  ? formatTimeDisplay(digest.summary.preferred_wake_time)
                  : '—'
              }
            />
            <MiniStat
              icon={HiOutlineTrophy}
              label="Habit score"
              value={formatHabitScore(digest?.summary?.habit_score)}
            />
            <MiniStat
              icon={HiOutlineSparkles}
              label="Goals"
              value={digest?.summary?.goals_count ?? 0}
            />
          </div>

          {!grouped.length ? (
            <p className="text-sm text-slate-500 py-6 text-center">
              No data available for this period. The engine needs verified wake-ups, snooze
              events, or challenge attempts from this client before it can advise.
            </p>
          ) : (
            <div className="space-y-5">
              {grouped.map((group) => (
                <div key={group.category}>
                  <p className="text-xs uppercase tracking-wider text-slate-500 mb-2">
                    {group.category} · {group.items.length}
                  </p>
                  <div className="grid lg:grid-cols-2 gap-3">
                    {group.items.map((rec) => (
                      <RecCard key={rec.id} rec={rec} />
                    ))}
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </motion.div>
  );
}
