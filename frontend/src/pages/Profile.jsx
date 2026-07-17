/**
 * Profile page — user info, sleep schedule, preferences, habit settings.
 */
import React, { useEffect, useState } from 'react';
import { useForm } from 'react-hook-form';
import { motion } from 'framer-motion';
import {
  HiOutlineUser, HiOutlineMoon, HiOutlineCog6Tooth,
  HiOutlinePuzzlePiece, HiOutlineChartBar,
  HiOutlineCheckCircle, HiOutlineGlobeAlt,
} from 'react-icons/hi2';
import toast from 'react-hot-toast';
import useAuthStore from '../store/authStore';
import { userAPI } from '../services/api';
import { formatTimeDisplay } from '../utils/timeFormat';

const TABS = [
  { id: 'profile', label: 'Profile', icon: HiOutlineUser },
  { id: 'sleep', label: 'Sleep Schedule', icon: HiOutlineMoon },
  { id: 'preferences', label: 'Preferences', icon: HiOutlineCog6Tooth },
];

const CHALLENGE_TYPES = ['math', 'logic', 'memory', 'word_game', 'pattern', 'riddle', 'quiz'];
const DIFFICULTY_LEVELS = ['beginner', 'easy', 'medium', 'hard', 'expert'];

/** Nested profile object from GET/PUT /users/profile (and preference updates). */
function getNestedProfile(bundle) {
  return bundle?.profile ?? null;
}

/**
 * Normalize a difficulty preference from the API.
 * Returns null when the bundle is still loading or the value is unrecognized,
 * so the UI never pretends a default was saved.
 */
function normalizeDifficultyPreference(bundle) {
  const nested = getNestedProfile(bundle);
  const raw = nested?.difficulty_preference ?? bundle?.difficulty_preference;
  if (raw == null || raw === '') return null;
  const normalized = String(raw).toLowerCase();
  return DIFFICULTY_LEVELS.includes(normalized) ? normalized : null;
}

function readPreferredChallengeTypes(bundle) {
  const nested = getNestedProfile(bundle);
  const types = nested?.preferred_challenge_types;
  return Array.isArray(types) ? types : null;
}

function readProductivityGoals(bundle) {
  const nested = getNestedProfile(bundle);
  const goals = nested?.productivity_goals;
  if (goals == null) return null;
  return typeof goals === 'string' ? goals : String(goals);
}

export default function Profile() {
  const { user, fetchProfile } = useAuthStore();
  const [activeTab, setActiveTab] = useState('profile');
  const [profile, setProfile] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    loadProfile();
  }, []);

  const loadProfile = async () => {
    try {
      const res = await userAPI.getProfile();
      setProfile(res.data);
      return res.data;
    } catch (err) {
      console.error(err);
      return null;
    }
  };

  // Refreshes both the page-local profile bundle and the shared auth store's
  // `user` (which the header/user-card above reads from), so edits made in
  // any tab are reflected immediately instead of only after a page reload.
  const refreshAll = async () => {
    await Promise.all([loadProfile(), fetchProfile()]);
  };

  return (
    <div className="max-w-4xl mx-auto space-y-6">
      {/* Header */}
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }}>
        <h1 className="text-2xl font-bold text-white font-display flex items-center gap-2">
          <HiOutlineUser className="w-7 h-7 text-primary-400" />
          Profile & Settings
        </h1>
        <p className="text-slate-400 mt-1">Manage your account, sleep schedule, and preferences</p>
      </motion.div>

      {/* User Card */}
      <motion.div initial={{ opacity: 0, y: 20 }} animate={{ opacity: 1, y: 0 }} transition={{ delay: 0.1 }} className="card">
        <div className="flex items-center gap-4">
          <div className="w-16 h-16 rounded-2xl gradient-accent flex items-center justify-center text-2xl font-bold text-white">
            {user?.full_name?.[0] || user?.username?.[0] || '?'}
          </div>
          <div>
            <h2 className="text-lg font-semibold text-white">{user?.full_name || user?.username}</h2>
            <p className="text-sm text-slate-400">{user?.email}</p>
            <div className="flex items-center gap-2 mt-1">
              <span className="badge-primary">{user?.role}</span>
              <span className="flex items-center gap-1 text-xs text-slate-400">
                <HiOutlineGlobeAlt className="w-3.5 h-3.5" />
                {user?.timezone || profile?.timezone || profile?.profile?.timezone || 'UTC'}
              </span>
            </div>
          </div>
        </div>
      </motion.div>

      {/* Tabs */}
      <div className="flex gap-1 p-1 rounded-xl bg-surface-800/50 border border-surface-700/30">
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${
              activeTab === tab.id
                ? 'bg-primary-600/20 text-primary-300 border border-primary-500/30'
                : 'text-slate-400 hover:text-white hover:bg-surface-700/30'
            }`}
          >
            <tab.icon className="w-4 h-4" />
            {tab.label}
          </button>
        ))}
      </div>

      {/* Tab Content */}
      <motion.div key={activeTab} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        {activeTab === 'profile' && <ProfileTab user={user} onUpdate={refreshAll} />}
        {activeTab === 'sleep' && <SleepTab profile={profile} onUpdate={refreshAll} />}
        {activeTab === 'preferences' && (
          profile
            ? <PreferencesTab profile={profile} onUpdate={refreshAll} />
            : (
              <div className="card">
                <p className="text-sm text-slate-400">Loading preferences…</p>
              </div>
            )
        )}
      </motion.div>
    </div>
  );
}


function ProfileTab({ user, onUpdate }) {
  const { register, handleSubmit, reset } = useForm({
    defaultValues: {
      full_name: user?.full_name || '',
      username: user?.username || '',
      timezone: user?.timezone || 'UTC',
    },
  });
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const logout = useAuthStore((s) => s.logout);

  const onSubmit = async (data) => {
    try {
      await userAPI.updateUser(data);
      toast.success('Profile updated!');
      await onUpdate?.();
      reset(data);
    } catch (err) {
      toast.error('Update failed');
    }
  };

  const handleDeleteAccount = async () => {
    setDeleting(true);
    try {
      await userAPI.deleteAccount();
      toast.success('Account deleted successfully');
      logout();
    } catch (err) {
      toast.error(err.response?.data?.detail || 'Failed to delete account');
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6">
      <div className="card">
        <h3 className="text-lg font-semibold text-white mb-4">Personal Information</h3>
        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            <div>
              <label className="label">Full Name</label>
              <input type="text" className="input" {...register('full_name')} />
            </div>
            <div>
              <label className="label">Username</label>
              <input type="text" className="input" {...register('username')} />
            </div>
          </div>
          <div>
            <label className="label">Timezone</label>
            <input type="text" className="input" {...register('timezone')} />
          </div>
          <button type="submit" className="btn-primary">Save Changes</button>
        </form>
      </div>

      {/* Danger Zone — Delete Account */}
      <div className="card border-red-500/30">
        <h3 className="text-lg font-semibold text-red-400 mb-2">Danger Zone</h3>
        <p className="text-sm text-slate-400 mb-4">
          Permanently delete your account and all associated data. This action cannot be undone.
        </p>
        {!showDeleteConfirm ? (
          <button
            onClick={() => setShowDeleteConfirm(true)}
            className="px-4 py-2 rounded-lg border border-red-500/50 text-red-400 text-sm font-medium hover:bg-red-500/10 transition-all"
            id="delete-account-btn"
          >
            Delete Account
          </button>
        ) : (
          <div className="p-4 rounded-xl bg-red-500/10 border border-red-500/30 space-y-3">
            <p className="text-sm text-red-300 font-medium">
              Are you sure? All your alarms, preferences, and habit data will be permanently removed.
            </p>
            <div className="flex gap-3">
              <button
                onClick={handleDeleteAccount}
                disabled={deleting}
                className="px-4 py-2 rounded-lg bg-red-600 text-white text-sm font-medium hover:bg-red-700 transition-all disabled:opacity-50"
              >
                {deleting ? 'Deleting...' : 'Yes, Delete My Account'}
              </button>
              <button
                onClick={() => setShowDeleteConfirm(false)}
                className="px-4 py-2 rounded-lg border border-surface-600 text-slate-400 text-sm font-medium hover:bg-surface-700 transition-all"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function SleepTab({ profile, onUpdate }) {
  const { register, handleSubmit, watch } = useForm({
    defaultValues: {
      preferred_wakeup_time: profile?.profile?.preferred_wakeup_time?.slice(0, 5) || '07:00',
      sleep_duration_hours: profile?.profile?.sleep_duration_hours || 8,
    },
  });

  const preferredWakeupTime = watch('preferred_wakeup_time');

  const onSubmit = async (data) => {
    try {
      await userAPI.updateSleepSchedule({
        preferred_wakeup_time: data.preferred_wakeup_time,
        sleep_duration_hours: parseFloat(data.sleep_duration_hours),
      });
      toast.success('Sleep schedule updated!');
      onUpdate();
    } catch (err) {
      toast.error('Update failed');
    }
  };

  return (
    <div className="card">
      <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
        <HiOutlineMoon className="w-5 h-5 text-indigo-400" />
        Sleep Schedule
      </h3>
      <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <div>
            <label className="label">Preferred Wake-up Time</label>
            <input type="time" className="input text-xl font-bold" {...register('preferred_wakeup_time')} />
            <p className="mt-1.5 text-sm text-slate-400">
              {formatTimeDisplay(preferredWakeupTime)}
            </p>
          </div>
          <div>
            <label className="label">Sleep Duration (hours)</label>
            <input type="number" step="0.5" min="3" max="14" className="input text-xl font-bold" {...register('sleep_duration_hours')} />
          </div>
        </div>
        <div className="p-4 rounded-xl bg-primary-500/10 border border-primary-500/20">
          <p className="text-sm text-primary-300">
            💡 Based on your settings, you should aim to go to bed by <strong>
            {(() => {
              const wake = profile?.profile?.preferred_wakeup_time || '07:00';
              const dur = profile?.profile?.sleep_duration_hours || 8;
              const [h, m] = wake.split(':').map(Number);
              const bedH = ((h - Math.floor(dur)) + 24) % 24;
              const bedtime24 = `${bedH.toString().padStart(2, '0')}:${(m || 0).toString().padStart(2, '0')}`;
              return formatTimeDisplay(bedtime24);
            })()}
            </strong>
          </p>
        </div>
        <button type="submit" className="btn-primary">Update Schedule</button>
      </form>
    </div>
  );
}

function PreferencesTab({ profile, onUpdate }) {
  // Saved values from the server bundle (null while profile is still loading).
  const serverDifficulty = normalizeDifficultyPreference(profile);
  const serverTypes = readPreferredChallengeTypes(profile);
  const serverTypesKey = serverTypes == null ? null : JSON.stringify(serverTypes);
  const serverGoals = readProductivityGoals(profile);

  // Local draft state — never seed difficulty with a fake "medium" before the
  // profile has loaded; that caused stale/wrong selection after refresh.
  const [selectedTypes, setSelectedTypes] = useState(() => {
    return readPreferredChallengeTypes(profile) ?? ['math', 'logic'];
  });
  const [difficulty, setDifficulty] = useState(() => serverDifficulty);
  const [goals, setGoals] = useState(() => serverGoals ?? '');
  const [prefsReady, setPrefsReady] = useState(() => serverDifficulty != null);

  // Hydrate / re-sync when the *saved* preference value changes (initial
  // fetch completing, hard refresh, or post-save reload). Dependency is the
  // normalized string so unrelated profile object identity changes do not
  // clobber an in-progress unsaved selection.
  useEffect(() => {
    if (serverDifficulty == null) return;
    setDifficulty(serverDifficulty);
    setPrefsReady(true);
  }, [serverDifficulty]);

  useEffect(() => {
    if (serverTypesKey == null) return;
    try {
      const parsed = JSON.parse(serverTypesKey);
      if (Array.isArray(parsed)) setSelectedTypes(parsed);
    } catch {
      // ignore malformed snapshot
    }
  }, [serverTypesKey]);

  useEffect(() => {
    if (serverGoals == null) return;
    setGoals(serverGoals);
  }, [serverGoals]);

  const toggleType = (type) => {
    setSelectedTypes((prev) =>
      prev.includes(type) ? prev.filter((t) => t !== type) : [...prev, type]
    );
  };

  const handleSave = async () => {
    if (!prefsReady || !difficulty) {
      toast.error('Preferences are still loading');
      return;
    }
    try {
      const res = await userAPI.updatePreferences({
        preferred_challenge_types: selectedTypes,
        difficulty_preference: difficulty,
        productivity_goals: goals,
      });
      // Trust the write response immediately so a slow refresh cannot flash
      // an older selection.
      const savedDifficulty = normalizeDifficultyPreference(res.data);
      if (savedDifficulty != null) {
        setDifficulty(savedDifficulty);
        setPrefsReady(true);
      }
      const savedTypes = readPreferredChallengeTypes(res.data);
      if (savedTypes != null) {
        setSelectedTypes(savedTypes);
      }
      const savedGoals = readProductivityGoals(res.data);
      if (savedGoals != null) {
        setGoals(savedGoals);
      }
      toast.success('Preferences saved!');
      await onUpdate?.();
    } catch (err) {
      toast.error('Save failed');
    }
  };

  return (
    <div className="space-y-6">
      {/* Challenge Types */}
      <div className="card">
        <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <HiOutlinePuzzlePiece className="w-5 h-5 text-accent-400" />
          Preferred Challenge Types
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {CHALLENGE_TYPES.map((type) => (
            <button
              key={type}
              onClick={() => toggleType(type)}
              className={`p-3 rounded-xl border text-sm font-medium capitalize transition-all ${
                selectedTypes.includes(type)
                  ? 'border-accent-500 bg-accent-500/10 text-accent-300'
                  : 'border-surface-700/50 text-slate-400 hover:border-surface-600'
              }`}
            >
              {selectedTypes.includes(type) && <HiOutlineCheckCircle className="w-4 h-4 inline mr-1" />}
              {type}
            </button>
          ))}
        </div>
      </div>

      {/* Difficulty */}
      <div className="card">
        <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <HiOutlineChartBar className="w-5 h-5 text-amber-400" />
          Default Difficulty
        </h3>
        <div className="flex gap-2">
          {DIFFICULTY_LEVELS.map((d) => (
            <button
              key={d}
              onClick={() => setDifficulty(d)}
              className={`flex-1 py-3 rounded-xl text-sm font-medium capitalize transition-all ${
                difficulty === d
                  ? 'gradient-accent text-white'
                  : 'bg-surface-800/50 text-slate-400 border border-surface-700/30 hover:border-surface-600'
              }`}
            >
              {d}
            </button>
          ))}
        </div>
      </div>

      {/* Productivity Goals */}
      <div className="card">
        <h3 className="text-lg font-semibold text-white mb-4">Productivity Goals</h3>
        <textarea
          value={goals}
          onChange={(e) => setGoals(e.target.value)}
          rows={4}
          placeholder="What are your productivity goals? (e.g., Wake up by 6 AM, exercise daily...)"
          className="input resize-none"
        />
      </div>

      <button onClick={handleSave} className="btn-primary w-full">Save All Preferences</button>
    </div>
  );
}
