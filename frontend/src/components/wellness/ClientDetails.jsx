/**
 * Selected-client identity, profile context, and headline metrics.
 *
 * Three blocks: the alert banner, Profile Information (GET /coach/clients/{id}
 * plus the roster row), and Core Metrics. Roster-row values are the fallback
 * for the metric cards so the panel stays populated while the deeper
 * behavioural request is still in flight.
 */
import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineExclamationTriangle,
  HiOutlineFire,
  HiOutlineMoon,
  HiOutlineSquares2X2,
  HiOutlineSun,
  HiOutlineTrophy,
  HiOutlineUsers,
} from 'react-icons/hi2';
import { PanelError, ProfileField, StatCard } from './primitives';
import { clientDisplayName, clientTimezoneOf, fadeUp } from './constants';
import { formatInTimeZone } from '../../utils/timeFormat';
import { formatHabitScore } from '../../utils/habitScore';

export function ClientBanner({ clientRow }) {
  const name = clientDisplayName(clientRow);
  return (
    <motion.div
      {...fadeUp}
      transition={{ delay: 0.08 }}
      className="card flex flex-wrap items-start justify-between gap-4"
    >
      <div className="flex items-start gap-3">
        <div className="w-11 h-11 rounded-full gradient-primary flex items-center justify-center text-base font-bold flex-shrink-0">
          {name?.[0]?.toUpperCase() || '?'}
        </div>
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="text-lg font-semibold text-white">{name}</h2>
            {clientRow?.needs_attention && (
              <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-orange-500/15 text-orange-300 border border-orange-500/25">
                Needs attention
              </span>
            )}
            {clientRow?.is_active === false && (
              <span className="text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full bg-slate-500/20 text-slate-300">
                Deactivated
              </span>
            )}
          </div>
          <p className="text-sm text-slate-400">{clientRow?.email}</p>
        </div>
      </div>
      {clientRow?.alerts?.length > 0 && (
        <ul className="space-y-1 max-w-md">
          {clientRow.alerts.map((alert, i) => (
            <li key={i} className="text-xs text-orange-300 flex gap-1.5">
              <HiOutlineExclamationTriangle className="w-3.5 h-3.5 flex-shrink-0 mt-0.5" />
              {alert}
            </li>
          ))}
        </ul>
      )}
    </motion.div>
  );
}

export default function ClientDetails({
  clientRow,
  clientDetail,
  behavioral,
  detailError,
  behavioralError,
  onRetry,
}) {
  const timezone = clientTimezoneOf(clientRow);
  const name = clientDisplayName(clientRow);
  const habits = behavioral?.habit_trends;
  const wake = behavioral?.wake_up_consistency;
  const sleep = behavioral?.sleep_schedule_adherence;

  const clientLocalTime = formatInTimeZone(new Date(), timezone, {
    hour: '2-digit',
    minute: '2-digit',
  });

  const lastVerifiedWake = useMemo(() => {
    if (!clientRow) return '—';
    if (!clientRow.last_wake_at) return 'No verified wake-up yet';
    return (
      formatInTimeZone(clientRow.last_wake_at, timezone, {
        dateStyle: 'medium',
        timeStyle: 'short',
      }) || 'No verified wake-up yet'
    );
  }, [clientRow, timezone]);

  const lastVerifiedWakeHint = useMemo(() => {
    const elapsed = clientRow?.days_since_last_wake;
    if (elapsed == null) return 'No wake verification recorded';
    if (elapsed === 0) return 'Today';
    return `${elapsed} day${elapsed === 1 ? '' : 's'} ago`;
  }, [clientRow]);

  const goals = clientDetail?.goals || [];
  const currentGoal = detailError
    ? 'Unavailable'
    : !clientDetail
      ? '—'
      : goals[0] || 'No goal saved yet';

  return (
    <>
      <motion.div {...fadeUp} transition={{ delay: 0.09 }} className="card">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2 mb-4">
          <HiOutlineUsers className="w-5 h-5 text-violet-400" />
          Profile Information
        </h2>
        {detailError ? (
          <PanelError message={detailError} onRetry={onRetry} />
        ) : (
          <dl className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-x-6 gap-y-4">
            <ProfileField label="Name" value={name || '—'} />
            <ProfileField label="Email" value={clientRow?.email || '—'} />
            <ProfileField
              label="Timezone"
              value={timezone}
              hint={clientLocalTime ? `Local time ${clientLocalTime}` : null}
            />
            <ProfileField
              label="Status"
              value={clientRow?.is_active === false ? 'Deactivated' : 'Active'}
              hint={clientRow?.needs_attention ? 'Needs attention' : 'On track'}
            />
            <ProfileField
              label="Last Verified Wake"
              value={lastVerifiedWake}
              hint={lastVerifiedWakeHint}
            />
            <ProfileField
              label="Current Goal"
              value={currentGoal}
              hint={
                goals.length > 1
                  ? `+${goals.length - 1} more goal${goals.length > 2 ? 's' : ''}`
                  : null
              }
            />
          </dl>
        )}
      </motion.div>

      <motion.div {...fadeUp} transition={{ delay: 0.1 }}>
        <h2 className="text-lg font-semibold text-white flex items-center gap-2 mb-4">
          <HiOutlineSquares2X2 className="w-5 h-5 text-accent-400" />
          Core Metrics
        </h2>
        {behavioralError && !behavioral ? (
          <PanelError message={behavioralError} onRetry={onRetry} />
        ) : (
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
            <StatCard
              icon={HiOutlineTrophy}
              label="Habit Score"
              value={formatHabitScore(habits?.current_habit_score ?? clientRow?.habit_score)}
              color="from-accent-500 to-accent-700"
              hint="Weighted composite of wake, challenge, snooze, and sleep behaviour"
            />
            <StatCard
              icon={HiOutlineSun}
              label="Wake Consistency"
              value={
                wake?.rolling_profile_score != null
                  ? Math.round(wake.rolling_profile_score)
                  : clientRow?.wake_consistency != null
                    ? Math.round(clientRow.wake_consistency)
                    : '—'
              }
              color="from-amber-500 to-orange-600"
              hint="Rolling 0–100 wake-consistency score — the same score used by the roster and alerts"
            />
            <StatCard
              icon={HiOutlineMoon}
              label="Sleep Adherence"
              value={sleep?.adherence_rate != null ? `${Math.round(sleep.adherence_rate)}%` : '—'}
              color="from-indigo-500 to-violet-600"
              hint="Days woken within tolerance of the client's preferred wake time"
            />
            <StatCard
              icon={HiOutlineFire}
              label="Day Streak"
              value={sleep?.profile_streak_days ?? clientRow?.streak_days ?? '—'}
              color="from-orange-500 to-red-600"
              hint="Consecutive days with a successful wake-up"
            />
          </div>
        )}
      </motion.div>
    </>
  );
}
