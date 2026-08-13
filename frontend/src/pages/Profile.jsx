/**
 * Profile page — user info, sleep schedule, preferences, habit settings.
 */
import React, { useEffect, useRef, useState } from 'react';
import { useForm } from 'react-hook-form';
import { motion } from 'framer-motion';
import {
  HiOutlineUser, HiOutlineMoon, HiOutlineCog6Tooth,
  HiOutlinePuzzlePiece, HiOutlineChartBar,
  HiOutlineCheckCircle, HiOutlineGlobeAlt, HiOutlineBell,
} from 'react-icons/hi2';
import toast from 'react-hot-toast';
import useAuthStore from '../store/authStore';
import { userAPI, notificationAPI, authAPI } from '../services/api';
import { ROLES } from '../utils/routeAccess';
import { formatTimeDisplay, formatTime12Hour, computeBedtime } from '../utils/timeFormat';
import HabitScoreCard from '../components/profile/HabitScoreCard';

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

/**
 * Read a single preferred challenge type from the API bundle.
 * Backend still stores a list; we take the first valid entry so the UI
 * is single-select and refresh always restores one chip.
 */
function readPreferredChallengeType(bundle) {
  const nested = getNestedProfile(bundle);
  const types = nested?.preferred_challenge_types;
  if (!Array.isArray(types) || types.length === 0) return null;
  const first = String(types[0]).toLowerCase().trim();
  return CHALLENGE_TYPES.includes(first) ? first : null;
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

  // Sleep schedule, challenge preferences and the reminder system are all
  // specified for alarm users; the spec defines no coach-side settings.
  const isCoach = user?.role === ROLES.WELLNESS_COACH;
  const tabs = isCoach ? TABS.filter((tab) => tab.id === 'profile') : TABS;

  useEffect(() => {
    loadProfile();
    fetchProfile();
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
        <p className="text-slate-400 mt-1">
          {isCoach
            ? 'Manage your account information'
            : 'Manage your account, sleep schedule, and preferences'}
        </p>
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
      {tabs.length > 1 && (
        <div className="flex gap-1 p-1 rounded-xl bg-surface-800/50 border border-surface-700/30">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`flex-1 flex items-center justify-center gap-2 px-4 py-2.5 rounded-lg text-sm font-medium transition-all ${activeTab === tab.id
                ? 'bg-primary-600/20 text-primary-300 border border-primary-500/30'
                : 'text-slate-400 hover:text-white hover:bg-surface-700/30'
                }`}
            >
              <tab.icon className="w-4 h-4" />
              {tab.label}
            </button>
          ))}
        </div>
      )}

      {/* Tab Content */}
      <motion.div key={activeTab} initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }}>
        {activeTab === 'profile' && (
          profile
            ? <ProfileTab user={user} profile={profile} onUpdate={refreshAll} />
            : (
              <div className="card">
                <p className="text-sm text-slate-400">Loading profile…</p>
              </div>
            )
        )}
        {activeTab === 'sleep' && !isCoach && (
          <SleepTab profile={profile} onUpdate={refreshAll} />
        )}
        {activeTab === 'preferences' && !isCoach && (
          profile
            ? (
              <div className="space-y-6">
                <PreferencesTab profile={profile} onUpdate={refreshAll} />
                <HabitScoreCard />
              </div>
            )
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


function ProfileTab({ user, profile, onUpdate }) {
  const resolvedTimezone =
    profile?.timezone ||
    profile?.profile?.timezone ||
    user?.timezone ||
    'UTC';
  const { register, handleSubmit, reset } = useForm({
    defaultValues: {
      full_name: user?.full_name || '',
      username: user?.username || '',
      timezone: resolvedTimezone,
    },
  });
  const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [signingOutAll, setSigningOutAll] = useState(false);
  const [email, setEmail] = useState(user?.email || '');
  const [savingEmail, setSavingEmail] = useState(false);
  const logout = useAuthStore((s) => s.logout);
  const logoutAll = useAuthStore((s) => s.logoutAll);

  // Keep the form in sync when the profile bundle finishes loading / refreshes.
  useEffect(() => {
    reset({
      full_name: user?.full_name || '',
      username: user?.username || '',
      timezone: resolvedTimezone,
    });
  }, [user?.full_name, user?.username, resolvedTimezone, reset]);

  useEffect(() => {
    setEmail(user?.email || '');
  }, [user?.email]);

  const handleSaveEmail = async (event) => {
    event.preventDefault();
    const next = email.trim();
    if (!next || next === user?.email || savingEmail) return;
    setSavingEmail(true);
    try {
      await authAPI.updateMe({ email: next });
      toast.success('Email updated — verify the new address to keep alerts working');
      await onUpdate?.();
    } catch (err) {
      const detail = err.response?.data?.detail;
      toast.error(typeof detail === 'string' ? detail : 'Could not update email');
      setEmail(user?.email || '');
    } finally {
      setSavingEmail(false);
    }
  };

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

  const handleSignOutEverywhere = async () => {
    if (signingOutAll) return;
    setSigningOutAll(true);
    const result = await logoutAll();
    if (result?.success) {
      toast.success('Signed out on all devices');
    } else {
      toast.error('Could not revoke other sessions — signed out here only');
    }
    setSigningOutAll(false);
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

      {/* Email lives on the user row, not the profile, so it has its own save. */}
      <div className="card">
        <h3 className="text-lg font-semibold text-white mb-2">Email Address</h3>
        <p className="text-sm text-slate-400 mb-4">
          Password resets, verification links and reminder emails all go to this
          address. Changing it takes effect immediately.
        </p>
        <form onSubmit={handleSaveEmail} className="flex flex-col sm:flex-row gap-3">
          <input
            type="email"
            className="input flex-1"
            id="profile-email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="you@example.com"
          />
          <button
            type="submit"
            id="save-email-btn"
            disabled={savingEmail || !email.trim() || email.trim() === user?.email}
            className="btn-primary sm:w-auto disabled:opacity-50"
          >
            {savingEmail ? 'Saving…' : 'Update Email'}
          </button>
        </form>
      </div>

      {/* Sessions — revoke tokens issued to every other browser/device */}
      <div className="card">
        <h3 className="text-lg font-semibold text-white mb-2">Active Sessions</h3>
        <p className="text-sm text-slate-400 mb-4">
          Signing out everywhere revokes every token issued to this account, so any
          other browser or device is signed out immediately. Use this if you left
          yourself logged in somewhere you no longer control.
        </p>
        <button
          type="button"
          onClick={handleSignOutEverywhere}
          disabled={signingOutAll}
          id="sign-out-everywhere-btn"
          className="px-4 py-2 rounded-lg border border-surface-600 text-slate-300 text-sm font-medium hover:bg-surface-700 transition-all disabled:opacity-50"
        >
          {signingOutAll ? 'Signing out…' : 'Sign out on all devices'}
        </button>
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
  const defaultWake =
    profile?.profile?.preferred_wakeup_time?.slice(0, 5) ||
    profile?.profile?.preferred_wake_time?.slice(0, 5) ||
    '07:00';
  const defaultDuration = profile?.profile?.sleep_duration_hours || 8;
  const { register, handleSubmit, watch, reset } = useForm({
    defaultValues: {
      preferred_wakeup_time: defaultWake,
      sleep_duration_hours: defaultDuration,
    },
  });

  useEffect(() => {
    reset({
      preferred_wakeup_time: defaultWake,
      sleep_duration_hours: defaultDuration,
    });
  }, [defaultWake, defaultDuration, reset]);

  const preferredWakeupTime = watch('preferred_wakeup_time');
  const sleepDurationHours = watch('sleep_duration_hours');
  const recommendedBedtime = computeBedtime(preferredWakeupTime, sleepDurationHours);
  const sleepGoalHours = Number(sleepDurationHours || 8);
  const sleepGoalText = `${sleepGoalHours} hours`;

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
        <div className="p-4 rounded-xl bg-primary-500/10 border border-primary-500/20 space-y-1.5">
          <p className="text-base font-semibold text-white">
            Recommended Bedtime:{' '}
            <span className="text-primary-300">{formatTime12Hour(recommendedBedtime)}</span>
          </p>
          <p className="text-sm text-slate-300">
            Based on Wake Time: {formatTime12Hour(preferredWakeupTime || '07:00')}
          </p>
          <p className="text-sm text-slate-300">
            Sleep Goal: {sleepGoalText}
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
  const serverType = readPreferredChallengeType(profile);
  const serverGoals = readProductivityGoals(profile);

  // Local draft state — never seed difficulty with a fake "medium" before the
  // profile has loaded; that caused stale/wrong selection after refresh.
  // Challenge type is single-select; backend still receives a one-item list.
  const [selectedType, setSelectedType] = useState(() => {
    return readPreferredChallengeType(profile) ?? 'math';
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
    if (serverType == null) return;
    setSelectedType(serverType);
  }, [serverType]);

  useEffect(() => {
    if (serverGoals == null) return;
    setGoals(serverGoals);
  }, [serverGoals]);

  const handleSave = async () => {
    if (!prefsReady || !difficulty) {
      toast.error('Preferences are still loading');
      return;
    }
    try {
      const res = await userAPI.updatePreferences({
        // Backend accepts a list; persist exactly one preferred type.
        preferred_challenge_types: [selectedType],
        difficulty_preference: difficulty,
      });
      // Goals have their own endpoint, which normalizes the free-text field
      // into the stored list. Only written when the text actually changed.
      const goalsRes =
        (serverGoals ?? '') === goals
          ? null
          : await userAPI.updateGoals({ productivity_goals: goals });
      const saved = goalsRes?.data || res.data;
      // Trust the write response immediately so a slow refresh cannot flash
      // an older selection.
      const savedDifficulty = normalizeDifficultyPreference(saved);
      if (savedDifficulty != null) {
        setDifficulty(savedDifficulty);
        setPrefsReady(true);
      }
      const savedType = readPreferredChallengeType(saved);
      if (savedType != null) {
        setSelectedType(savedType);
      }
      const savedGoals = readProductivityGoals(saved);
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
      <NotificationPreferencesCard />

      {/* Challenge Types */}
      <div className="card">
        <h3 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
          <HiOutlinePuzzlePiece className="w-5 h-5 text-accent-400" />
          Preferred Challenge Types
        </h3>
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3" role="radiogroup" aria-label="Preferred challenge type">
          {CHALLENGE_TYPES.map((type) => {
            const isSelected = selectedType === type;
            return (
              <button
                key={type}
                type="button"
                role="radio"
                aria-checked={isSelected}
                onClick={() => setSelectedType(type)}
                className={`p-3 rounded-xl border text-sm font-medium capitalize transition-all ${isSelected
                  ? 'border-accent-500 bg-accent-500/10 text-accent-300'
                  : 'border-surface-700/50 text-slate-400 hover:border-surface-600'
                  }`}
              >
                {isSelected && <HiOutlineCheckCircle className="w-4 h-4 inline mr-1" />}
                {type}
              </button>
            );
          })}
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
              className={`flex-1 py-3 rounded-xl text-sm font-medium capitalize transition-all ${difficulty === d
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

function ToggleRow({ label, description, checked, onChange, disabled = false }) {
  return (
    <label className={`flex items-start justify-between gap-4 py-2 ${disabled ? 'opacity-50' : 'cursor-pointer'}`}>
      <div className="min-w-0">
        <p className="text-sm font-medium text-slate-200">{label}</p>
        {description && (
          <p className="text-xs text-slate-500 mt-0.5">{description}</p>
        )}
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={checked}
        disabled={disabled}
        onClick={() => !disabled && onChange(!checked)}
        className={`relative w-11 h-6 rounded-full transition-colors flex-shrink-0 ${checked ? 'bg-primary-500' : 'bg-surface-600'
          } disabled:cursor-not-allowed`}
      >
        <span
          className={`absolute top-0.5 left-0.5 w-5 h-5 rounded-full bg-white transition-transform ${checked ? 'translate-x-5' : 'translate-x-0'
            }`}
        />
      </button>
    </label>
  );
}

const NOTIFICATION_SOUNDS = [
  { value: 'default', label: 'Default' },
  { value: 'gentle', label: 'Gentle' },
  { value: 'chime', label: 'Chime' },
  { value: 'silent', label: 'Silent' },
];

const NOTIFICATION_FREQUENCIES = [
  {
    value: 'all',
    label: 'All',
    description: 'Bedtime, wake, habit, challenge, progress, and motivational',
  },
  {
    value: 'essential',
    label: 'Essential',
    description: 'Bedtime and wake reminders only',
  },
  {
    value: 'minimal',
    label: 'Minimal',
    description: 'Wake reminders only',
  },
];

/** Server-side validation ranges; fallback matches the backend column default. */
const REMINDER_MINUTE_FIELDS = {
  bedtime_reminder_minutes_before: { min: 5, max: 120, fallback: 30 },
  wake_reminder_minutes_before: { min: 5, max: 60, fallback: 15 },
};

/** Backend schedules the daily motivational at 08:00 when no time is stored. */
const DEFAULT_MOTIVATIONAL_TIME = '08:00';

/**
 * Coerce a minutes field to a value the API accepts. `fallback` (the last
 * value the server returned) is used only when the field was left blank —
 * a partially typed value must never be replaced by a hardcoded default.
 */
function normalizeReminderMinutes(field, value, fallback) {
  const { min, max } = REMINDER_MINUTE_FIELDS[field];
  const parsed = Number(value);
  if (value === '' || value === null || value === undefined || !Number.isFinite(parsed)) {
    return fallback;
  }
  return Math.min(max, Math.max(min, Math.round(parsed)));
}

function snapshotReminderToggles(prefs) {
  return {
    bedtime_reminder_enabled: !!prefs.bedtime_reminder_enabled,
    wake_reminder_enabled: !!prefs.wake_reminder_enabled,
    habit_alerts_enabled: !!prefs.habit_alerts_enabled,
    challenge_reminders_enabled: !!prefs.challenge_reminders_enabled,
    progress_updates_enabled: !!prefs.progress_updates_enabled,
    motivational_enabled: !!prefs.motivational_enabled,
  };
}

function withRemindersDisabled(prefs) {
  return {
    ...prefs,
    bedtime_reminder_enabled: false,
    wake_reminder_enabled: false,
    habit_alerts_enabled: false,
    challenge_reminders_enabled: false,
    progress_updates_enabled: false,
    motivational_enabled: false,
  };
}

function NotificationPreferencesCard() {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [prefs, setPrefs] = useState(null);
  /** Preserved reminder toggles while master notifications are off. */
  const reminderSnapshotRef = useRef(null);
  /** Last state the server confirmed — the recovery source for blank inputs. */
  const savedPrefsRef = useRef(null);

  const minutesFallback = (field) =>
    savedPrefsRef.current?.[field] ?? REMINDER_MINUTE_FIELDS[field].fallback;

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const { data } = await notificationAPI.getPreferences();
        if (cancelled) return;
        savedPrefsRef.current = data;
        if (data.notifications_enabled === false) {
          reminderSnapshotRef.current = snapshotReminderToggles(data);
          setPrefs(withRemindersDisabled(data));
        } else {
          reminderSnapshotRef.current = null;
          setPrefs(data);
        }
      } catch {
        if (!cancelled) toast.error('Failed to load notification preferences');
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, []);

  const patch = (field, value) => {
    setPrefs((prev) => (prev ? { ...prev, [field]: value } : prev));
  };

  const handleMasterToggle = (enabled) => {
    setPrefs((prev) => {
      if (!prev) return prev;
      if (!enabled) {
        reminderSnapshotRef.current = snapshotReminderToggles(prev);
        return withRemindersDisabled({ ...prev, notifications_enabled: false });
      }
      const snap = reminderSnapshotRef.current;
      return {
        ...prev,
        notifications_enabled: true,
        bedtime_reminder_enabled: snap
          ? snap.bedtime_reminder_enabled
          : prev.bedtime_reminder_enabled,
        wake_reminder_enabled: snap
          ? snap.wake_reminder_enabled
          : prev.wake_reminder_enabled,
        habit_alerts_enabled: snap
          ? snap.habit_alerts_enabled
          : prev.habit_alerts_enabled,
        challenge_reminders_enabled: snap
          ? snap.challenge_reminders_enabled
          : prev.challenge_reminders_enabled,
        progress_updates_enabled: snap
          ? snap.progress_updates_enabled
          : prev.progress_updates_enabled,
        motivational_enabled: snap
          ? snap.motivational_enabled
          : prev.motivational_enabled,
      };
    });
  };

  const handleSave = async () => {
    if (!prefs) return;
    setSaving(true);
    try {
      const masterEnabled = prefs.notifications_enabled !== false;
      // While master is off, UI forces reminder toggles off — persist the
      // snapshot so turning notifications back on restores prior choices.
      const reminderFlags =
        !masterEnabled && reminderSnapshotRef.current
          ? reminderSnapshotRef.current
          : {
            bedtime_reminder_enabled: prefs.bedtime_reminder_enabled,
            wake_reminder_enabled: prefs.wake_reminder_enabled,
            habit_alerts_enabled: prefs.habit_alerts_enabled,
            challenge_reminders_enabled: prefs.challenge_reminders_enabled,
            progress_updates_enabled: prefs.progress_updates_enabled,
            motivational_enabled: prefs.motivational_enabled,
          };

      // A field left blank mid-edit falls back to the last saved value, and
      // out-of-range input is clamped so the request can never 422 away a save.
      const bedtimeMinutes = normalizeReminderMinutes(
        'bedtime_reminder_minutes_before',
        prefs.bedtime_reminder_minutes_before,
        minutesFallback('bedtime_reminder_minutes_before')
      );
      const wakeMinutes = normalizeReminderMinutes(
        'wake_reminder_minutes_before',
        prefs.wake_reminder_minutes_before,
        minutesFallback('wake_reminder_minutes_before')
      );
      const motivationalTime = prefs.motivational_time
        ? String(prefs.motivational_time).slice(0, 5)
        : (prefs.motivational_enabled ? DEFAULT_MOTIVATIONAL_TIME : null);

      const { data } = await notificationAPI.updatePreferences({
        notifications_enabled: masterEnabled,
        ...reminderFlags,
        bedtime_reminder_minutes_before: bedtimeMinutes,
        wake_reminder_minutes_before: wakeMinutes,
        motivational_time: motivationalTime,
        quiet_hours_start: prefs.quiet_hours_start
          ? String(prefs.quiet_hours_start).slice(0, 5)
          : null,
        quiet_hours_end: prefs.quiet_hours_end
          ? String(prefs.quiet_hours_end).slice(0, 5)
          : null,
        notification_sound: prefs.notification_sound || 'default',
        notification_frequency: prefs.notification_frequency || 'all',
        push_enabled: prefs.push_enabled,
      });

      savedPrefsRef.current = data;
      if (data.notifications_enabled === false) {
        reminderSnapshotRef.current = snapshotReminderToggles(data);
        setPrefs(withRemindersDisabled(data));
      } else {
        reminderSnapshotRef.current = null;
        setPrefs(data);
      }
      toast.success('Notification preferences saved');

      // Apply to scheduling immediately after save
      try {
        const { syncLocalPendingNotifications, clearLocalSchedules } = await import(
          '../services/notificationService'
        );
        if (data.notifications_enabled === false) {
          clearLocalSchedules();
        } else {
          await syncLocalPendingNotifications();
        }
      } catch {
        // Local sync is best-effort
      }
    } catch {
      toast.error('Failed to save notification preferences');
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="card flex items-center justify-center py-8">
        <div className="w-5 h-5 border-2 border-primary-500 border-t-transparent rounded-full animate-spin" />
      </div>
    );
  }

  if (!prefs) return null;

  const masterOn = prefs.notifications_enabled !== false;
  const freq = prefs.notification_frequency || 'all';
  const bedtimeAllowed = masterOn && (freq === 'all' || freq === 'essential');
  const wakeAllowed = masterOn;
  const habitAllowed = masterOn && freq === 'all';
  const challengeAllowed = masterOn && freq === 'all';
  const progressAllowed = masterOn && freq === 'all';
  const motivationalAllowed = masterOn && freq === 'all';

  return (
    <div className="card space-y-4">
      <h3 className="text-lg font-semibold text-white mb-1 flex items-center gap-2">
        <HiOutlineBell className="w-5 h-5 text-primary-400" />
        Notification Preferences
      </h3>
      <p className="text-xs text-slate-500">
        Adjust settings, then save — scheduling updates immediately on save.
      </p>

      <ToggleRow
        label="Enable notifications"
        description="Master switch for all scheduled reminders"
        checked={masterOn}
        onChange={handleMasterToggle}
      />

      {!masterOn && (
        <p className="text-xs text-slate-500 -mt-2">
          Reminder options are disabled while notifications are off. Turning
          notifications back on restores your previous reminder settings.
        </p>
      )}

      <div
        className={`space-y-3 ${masterOn ? '' : 'opacity-50 pointer-events-none'}`}
        aria-disabled={!masterOn}
      >
        <ToggleRow
          label="Bedtime reminder"
          description="Wind-down alert before your computed bedtime"
          checked={!!prefs.bedtime_reminder_enabled}
          disabled={!bedtimeAllowed}
          onChange={(v) => patch('bedtime_reminder_enabled', v)}
        />
        {prefs.bedtime_reminder_enabled && bedtimeAllowed && (
          <label className="block text-xs text-slate-400">
            Minutes before bedtime
            <input
              type="number"
              min={5}
              max={120}
              value={prefs.bedtime_reminder_minutes_before ?? ''}
              onChange={(e) =>
                patch(
                  'bedtime_reminder_minutes_before',
                  e.target.value === '' ? '' : Number(e.target.value)
                )
              }
              onBlur={() =>
                patch(
                  'bedtime_reminder_minutes_before',
                  normalizeReminderMinutes(
                    'bedtime_reminder_minutes_before',
                    prefs.bedtime_reminder_minutes_before,
                    minutesFallback('bedtime_reminder_minutes_before')
                  )
                )
              }
              className="input mt-1 w-28"
              disabled={!masterOn}
            />
          </label>
        )}

        <ToggleRow
          label="Wake reminder"
          description="Pre-alarm nudge from your alarm schedule"
          checked={!!prefs.wake_reminder_enabled}
          disabled={!wakeAllowed}
          onChange={(v) => patch('wake_reminder_enabled', v)}
        />
        {prefs.wake_reminder_enabled && masterOn && (
          <label className="block text-xs text-slate-400">
            Minutes before alarm
            <input
              type="number"
              min={5}
              max={60}
              value={prefs.wake_reminder_minutes_before ?? ''}
              onChange={(e) =>
                patch(
                  'wake_reminder_minutes_before',
                  e.target.value === '' ? '' : Number(e.target.value)
                )
              }
              onBlur={() =>
                patch(
                  'wake_reminder_minutes_before',
                  normalizeReminderMinutes(
                    'wake_reminder_minutes_before',
                    prefs.wake_reminder_minutes_before,
                    minutesFallback('wake_reminder_minutes_before')
                  )
                )
              }
              className="input mt-1 w-28"
              disabled={!masterOn}
            />
          </label>
        )}

        <ToggleRow
          label="Habit reminder"
          description="Nudge when consistency or streaks decline"
          checked={!!prefs.habit_alerts_enabled}
          disabled={!habitAllowed}
          onChange={(v) => patch('habit_alerts_enabled', v)}
        />

        <ToggleRow
          label="Challenge reminder"
          description="Practice nudge after a couple of days without a challenge"
          checked={!!prefs.challenge_reminders_enabled}
          disabled={!challengeAllowed}
          onChange={(v) => patch('challenge_reminders_enabled', v)}
        />

        <ToggleRow
          label="Progress update"
          description="Weekly recap of wake-ups, challenges, and streak milestones"
          checked={!!prefs.progress_updates_enabled}
          disabled={!progressAllowed}
          onChange={(v) => patch('progress_updates_enabled', v)}
        />

        <ToggleRow
          label="Daily motivational"
          description="One encouraging message per day"
          checked={!!prefs.motivational_enabled}
          disabled={!motivationalAllowed}
          onChange={(v) => patch('motivational_enabled', v)}
        />
        {prefs.motivational_enabled && motivationalAllowed && (
          <label className="block text-xs text-slate-400">
            Preferred local time
            <input
              type="time"
              value={String(prefs.motivational_time || DEFAULT_MOTIVATIONAL_TIME).slice(0, 5)}
              onChange={(e) => patch('motivational_time', e.target.value || null)}
              className="input mt-1 w-36"
              disabled={!masterOn}
            />
          </label>
        )}

        <div className="pt-2 border-t border-surface-700/40 space-y-3">
          <p className="text-sm font-medium text-slate-200">Quiet hours</p>
          <p className="text-xs text-slate-500 -mt-2">
            Scheduled notifications wait until quiet hours end.
          </p>
          <div className="grid grid-cols-2 gap-3">
            <label className="block text-xs text-slate-400">
              Start
              <input
                type="time"
                value={
                  prefs.quiet_hours_start
                    ? String(prefs.quiet_hours_start).slice(0, 5)
                    : ''
                }
                onChange={(e) => patch('quiet_hours_start', e.target.value || null)}
                className="input mt-1"
                disabled={!masterOn}
              />
            </label>
            <label className="block text-xs text-slate-400">
              End
              <input
                type="time"
                value={
                  prefs.quiet_hours_end
                    ? String(prefs.quiet_hours_end).slice(0, 5)
                    : ''
                }
                onChange={(e) => patch('quiet_hours_end', e.target.value || null)}
                className="input mt-1"
                disabled={!masterOn}
              />
            </label>
          </div>
          {(prefs.quiet_hours_start || prefs.quiet_hours_end) && (
            <button
              type="button"
              className="text-xs text-slate-400 hover:text-slate-200 underline"
              onClick={() => {
                patch('quiet_hours_start', null);
                patch('quiet_hours_end', null);
              }}
              disabled={!masterOn}
            >
              Clear quiet hours
            </button>
          )}
        </div>

        <div className="pt-2 border-t border-surface-700/40 space-y-2">
          <p className="text-sm font-medium text-slate-200">Notification sound</p>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-2" role="radiogroup" aria-label="Notification sound">
            {NOTIFICATION_SOUNDS.map((opt) => {
              const selected = (prefs.notification_sound || 'default') === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={!masterOn}
                  onClick={() => patch('notification_sound', opt.value)}
                  className={`py-2.5 rounded-xl text-sm font-medium transition-all ${selected
                    ? 'border border-primary-500 bg-primary-500/10 text-primary-300'
                    : 'border border-surface-700/50 text-slate-400 hover:border-surface-600'
                    } disabled:cursor-not-allowed`}
                >
                  {opt.label}
                </button>
              );
            })}
          </div>
        </div>

        <div className="pt-2 border-t border-surface-700/40 space-y-2">
          <p className="text-sm font-medium text-slate-200">Notification frequency</p>
          <div className="space-y-2" role="radiogroup" aria-label="Notification frequency">
            {NOTIFICATION_FREQUENCIES.map((opt) => {
              const selected = freq === opt.value;
              return (
                <button
                  key={opt.value}
                  type="button"
                  role="radio"
                  aria-checked={selected}
                  disabled={!masterOn}
                  onClick={() => patch('notification_frequency', opt.value)}
                  className={`w-full text-left px-3 py-2.5 rounded-xl transition-all ${selected
                    ? 'border border-primary-500 bg-primary-500/10'
                    : 'border border-surface-700/50 hover:border-surface-600'
                    } disabled:cursor-not-allowed`}
                >
                  <p className={`text-sm font-medium ${selected ? 'text-primary-300' : 'text-slate-200'}`}>
                    {opt.label}
                  </p>
                  <p className="text-xs text-slate-500 mt-0.5">{opt.description}</p>
                </button>
              );
            })}
          </div>
        </div>
      </div>

      <button
        type="button"
        onClick={handleSave}
        disabled={saving}
        className="btn-secondary w-full"
      >
        {saving ? 'Saving…' : 'Save Notification Preferences'}
      </button>
    </div>
  );
}
