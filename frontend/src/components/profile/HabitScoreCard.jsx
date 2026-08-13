/**
 * Habit score, adaptation state and challenge-type preferences.
 *
 * Reads the raw profile record, which carries the adaptation fields the
 * /users/profile bundle does not expose (adapted difficulty, consistency
 * score and lifetime counters).
 */
import React, { useCallback, useEffect, useMemo, useState } from 'react';
import { motion } from 'framer-motion';
import { HiOutlineArrowPath, HiOutlineSparkles } from 'react-icons/hi2';
import toast from 'react-hot-toast';
import { profileAPI, userAPI, readErrorDetail } from '../../services/api';
import { formatHabitScore } from '../../utils/habitScore';

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

const CHALLENGE_TYPES = ['math', 'logic', 'memory', 'word_game', 'riddle', 'quiz'];

function label(key) {
  return key.replace(/_/g, ' ');
}

function Metric({ name, value, hint }) {
  return (
    <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 px-3 py-2.5">
      <p className="text-[11px] uppercase tracking-wider text-slate-500 mb-1">{name}</p>
      <p className="text-lg font-semibold text-white capitalize">{value}</p>
      {hint ? <p className="text-[11px] text-slate-500 mt-0.5">{hint}</p> : null}
    </div>
  );
}

export default function HabitScoreCard() {
  const [profile, setProfile] = useState(null);
  const [score, setScore] = useState(null);
  const [preferences, setPreferences] = useState(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [profileRes, scoreRes, prefRes] = await Promise.all([
        profileAPI.getMe(),
        profileAPI.getHabitScore(),
        userAPI.getPreferences(),
      ]);
      setProfile(profileRes.data);
      setScore(scoreRes.data);
      setPreferences(prefRes.data);
      setError(null);
    } catch (err) {
      setError((await readErrorDetail(err, '')) || 'Failed to load habit details');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const selectedTypes = useMemo(
    () => preferences?.preferred_challenge_types || [],
    [preferences]
  );

  const toggleType = async (type) => {
    if (saving) return;
    const next = selectedTypes.includes(type)
      ? selectedTypes.filter((t) => t !== type)
      : [...selectedTypes, type];
    if (next.length === 0) {
      toast.error('Keep at least one challenge type');
      return;
    }
    setSaving(true);
    try {
      const { data } = await profileAPI.updateHabits({
        habit_preferences: {
          ...(profile?.habit_preferences || {}),
          preferred_challenge_types: next,
        },
      });
      setProfile(data);
      setPreferences((prev) => ({ ...prev, preferred_challenge_types: next }));
      toast.success('Challenge preferences updated');
    } catch (err) {
      toast.error((await readErrorDetail(err, '')) || 'Could not save preferences');
    } finally {
      setSaving(false);
    }
  };

  if (loading && !profile) {
    return (
      <motion.div {...fadeUp} className="card">
        <div className="flex items-center justify-center py-8" role="status" aria-live="polite">
          <div className="w-6 h-6 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
          <span className="sr-only">Loading habit details</span>
        </div>
      </motion.div>
    );
  }

  if (error && !profile) {
    return (
      <motion.div {...fadeUp} className="card">
        <p className="text-sm text-red-300" role="alert">{error}</p>
        <button type="button" onClick={load} className="mt-3 text-sm text-primary-400">
          Try again
        </button>
      </motion.div>
    );
  }

  const breakdown = score?.breakdown || {};
  const weights = score?.weights || {};

  return (
    <motion.div {...fadeUp} className="card">
      <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlineSparkles className="w-5 h-5 text-primary-400" />
          Habit score &amp; adaptation
        </h2>
        <button
          type="button"
          onClick={load}
          disabled={loading}
          className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-sm border border-surface-600 text-slate-300 hover:text-white hover:border-surface-500 disabled:opacity-50"
        >
          <HiOutlineArrowPath className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          Refresh
        </button>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-5">
        <Metric name="Habit score" value={formatHabitScore(score?.habit_score)} />
        <Metric
          name="Serving difficulty"
          value={profile?.adapted_difficulty || '—'}
          hint={`you chose ${profile?.difficulty_preference || '—'}`}
        />
        <Metric
          name="Wake consistency"
          value={Math.round(profile?.wake_up_consistency_score ?? 0)}
        />
        <Metric
          name="Lifetime wake-ups"
          value={profile?.total_alarms_dismissed ?? 0}
          hint={`${profile?.total_snoozes ?? 0} snoozes`}
        />
      </div>

      {Object.keys(breakdown).length > 0 ? (
        <div className="mb-5">
          <h3 className="text-sm font-semibold text-white mb-2">Score components</h3>
          <ul className="space-y-1.5">
            {Object.entries(breakdown).map(([key, value]) => (
              <li
                key={key}
                className="flex items-center justify-between gap-3 text-sm rounded-lg border border-surface-700/40 px-3 py-2"
              >
                <span className="text-slate-300 capitalize">{label(key)}</span>
                <span className="text-white font-medium">
                  {Math.round(Number(value) || 0)}
                  {weights[key] != null ? (
                    <span className="text-xs text-slate-500 ml-2">
                      weight {Math.round(Number(weights[key]) * 100)}%
                    </span>
                  ) : null}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <div>
        <h3 className="text-sm font-semibold text-white mb-1">Preferred challenge types</h3>
        <p className="text-xs text-slate-500 mb-2">
          These bias which challenge an alarm serves you.
        </p>
        <div className="flex flex-wrap gap-2">
          {CHALLENGE_TYPES.map((type) => {
            const active = selectedTypes.includes(type);
            return (
              <button
                key={type}
                type="button"
                onClick={() => toggleType(type)}
                disabled={saving}
                aria-pressed={active}
                className={`px-3 py-1.5 rounded-lg text-sm border transition disabled:opacity-50 ${active
                    ? 'border-primary-500/40 bg-primary-600/20 text-primary-200'
                    : 'border-surface-600 text-slate-400 hover:text-white'
                  }`}
              >
                {label(type)}
              </button>
            );
          })}
        </div>
      </div>
    </motion.div>
  );
}
