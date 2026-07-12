/**
 * Dashboard — main user home screen with stats, upcoming alarms, quick actions.
 */
import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import toast from 'react-hot-toast';
import { motion } from 'framer-motion';
import {
  HiOutlineClock, HiOutlineTrophy, HiOutlineFire,
  HiOutlineChartBar, HiOutlinePuzzlePiece, HiOutlinePlus,
  HiOutlineBolt, HiOutlineMoon, HiOutlineSun,
} from 'react-icons/hi2';
import useAuthStore from '../store/authStore';
import useAlarmStore from '../store/alarmStore';
import { userAPI } from '../services/api';

const fadeUp = {
  initial: { opacity: 0, y: 20 },
  animate: { opacity: 1, y: 0 },
};

export default function Dashboard() {
  const { user } = useAuthStore();
  const { alarms, fetchAlarms, upcoming, fetchUpcoming } = useAlarmStore();
  const [stats, setStats] = useState(null);

  useEffect(() => {
    fetchAlarms();
    fetchUpcoming();
    userAPI.getStats().then(res => setStats(res.data)).catch(() => {});
  }, []);

  const greeting = () => {
    const hour = new Date().getHours();
    if (hour < 12) return { text: 'Good Morning', icon: HiOutlineSun, color: 'text-amber-400' };
    if (hour < 17) return { text: 'Good Afternoon', icon: HiOutlineSun, color: 'text-orange-400' };
    return { text: 'Good Evening', icon: HiOutlineMoon, color: 'text-indigo-400' };
  };

  const g = greeting();
  const GIcon = g.icon;

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
            {user?.full_name || user?.username}, here's your alarm overview
          </p>
        </div>
        <Link to="/alarms" className="btn-primary flex items-center gap-2 text-sm">
          <HiOutlinePlus className="w-4 h-4" />
          New Alarm
        </Link>
      </motion.div>

      {/* ─── Stats Row ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.1 }} className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          icon={HiOutlineClock}
          label="Active Alarms"
          value={stats?.active_alarms != null ? stats.active_alarms : '—'}
          color="from-primary-500 to-primary-700"
        />
        <StatCard
          icon={HiOutlineTrophy}
          label="Habit Score"
          value={stats?.current_habit_score != null ? `${Math.round(stats.current_habit_score)}%` : '—'}
          color="from-accent-500 to-accent-700"
        />
        <StatCard
          icon={HiOutlineFire}
          label="Day Streak"
          value={stats?.current_streak != null ? stats.current_streak : '—'}
          color="from-orange-500 to-red-600"
        />
        <StatCard
          icon={HiOutlineChartBar}
          label="Success Rate"
          value={stats?.wakeup_success_rate != null ? `${Math.round(stats.wakeup_success_rate)}%` : '—'}
          color="from-emerald-500 to-teal-600"
        />
      </motion.div>

      {/* ─── Wake-up Goal Tracker ─── */}
      <motion.div {...fadeUp} transition={{ delay: 0.15 }} className="card">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <HiOutlineSun className="w-5 h-5 text-amber-400" />
            Wake-up Goal Tracker
          </h2>
          {stats?.preferred_wakeup_time && (
            <span className="text-sm text-slate-400">
              Goal: <span className="text-primary-400 font-semibold">{stats.preferred_wakeup_time?.slice(0, 5)}</span>
            </span>
          )}
        </div>

        {/* Weekly Progress Bar */}
        <div className="mb-4">
          <div className="flex items-center justify-between mb-2">
            <span className="text-sm text-slate-400">This Week's Progress</span>
            <span className="text-sm font-semibold text-white">
              {stats?.weekly_on_time ?? 0} <span className="text-slate-400">/ {stats?.weekly_total ?? 7} days on time</span>
            </span>
          </div>
          <div className="w-full bg-surface-700 rounded-full h-3">
            <div
              className="h-3 rounded-full bg-gradient-to-r from-emerald-500 to-teal-400 transition-all duration-1000"
              style={{ width: `${((stats?.weekly_on_time ?? 0) / 7) * 100}%` }}
            />
          </div>
        </div>

        {/* Daily Tracker */}
        <div className="grid grid-cols-7 gap-2">
          {(stats?.weekly_tracker || [
            { day: 'Mon', status: 'pending' }, { day: 'Tue', status: 'pending' },
            { day: 'Wed', status: 'pending' }, { day: 'Thu', status: 'pending' },
            { day: 'Fri', status: 'pending' }, { day: 'Sat', status: 'pending' },
            { day: 'Sun', status: 'pending' },
          ]).map((day, i) => (
            <div key={i} className="flex flex-col items-center gap-1.5">
              <span className="text-[10px] text-slate-500 uppercase font-medium">{day.day}</span>
              <div className={`w-9 h-9 rounded-xl flex items-center justify-center text-xs font-bold transition-all ${
                day.status === 'on_time'
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/40'
                  : day.status === 'late'
                  ? 'bg-amber-500/20 text-amber-400 border border-amber-500/40'
                  : day.status === 'missed'
                  ? 'bg-red-500/15 text-red-400/60 border border-red-500/20'
                  : 'bg-surface-700/50 text-slate-500 border border-surface-600/30'
              }`}>
                {day.status === 'on_time' ? '✓' : day.status === 'late' ? '!' : day.status === 'missed' ? '✗' : '·'}
              </div>
            </div>
          ))}
        </div>

        {/* Legend */}
        <div className="flex items-center gap-4 mt-4 pt-3 border-t border-surface-700/30">
          <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
            <span className="w-2.5 h-2.5 rounded-full bg-emerald-500" /> On Time
          </span>
          <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
            <span className="w-2.5 h-2.5 rounded-full bg-amber-500" /> Late
          </span>
          <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
            <span className="w-2.5 h-2.5 rounded-full bg-red-500/60" /> Missed
          </span>
          <span className="flex items-center gap-1.5 text-[11px] text-slate-400">
            <span className="w-2.5 h-2.5 rounded-full bg-surface-600" /> Pending
          </span>
        </div>
      </motion.div>

      {/* ─── Two Column Layout ─── */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Upcoming Alarms */}
        <motion.div {...fadeUp} transition={{ delay: 0.2 }} className="lg:col-span-2 card">
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
              <p className="text-slate-400 mb-4">No alarms set yet</p>
              <Link to="/alarms" className="btn-primary text-sm inline-flex items-center gap-2">
                <HiOutlinePlus className="w-4 h-4" /> Create Your First Alarm
              </Link>
            </div>
          ) : (
            <div className="space-y-3">
              {alarms.filter(a => a.is_active).slice(0, 5).map((alarm) => (
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

        {/* Quick Actions */}
        <motion.div {...fadeUp} transition={{ delay: 0.3 }} className="card">
          <h2 className="text-lg font-semibold text-white mb-4 flex items-center gap-2">
            <HiOutlineBolt className="w-5 h-5 text-amber-400" />
            Quick Actions
          </h2>
          <div className="space-y-3">
            <QuickAction icon={HiOutlinePlus} label="Create Alarm" to="/alarms" color="primary" />
            <QuickAction icon={HiOutlinePuzzlePiece} label="Practice Challenge" onClick={() => toast.success('Practice mode coming soon!')} color="accent" />
            <QuickAction icon={HiOutlineChartBar} label="View Analytics" to="/analytics" color="emerald" />
            <QuickAction icon={HiOutlineTrophy} label="Habit Tracker" to="/profile" color="orange" />
          </div>

          {/* Mini Habit Score Gauge */}
          <div className="mt-6 p-4 rounded-xl gradient-card border border-surface-700/30">
            <p className="text-xs text-slate-400 uppercase tracking-wider mb-2">Today's Habit Score</p>
            <div className="flex items-end gap-2">
              <span className="text-4xl font-bold gradient-accent bg-clip-text text-transparent">
                {stats?.current_habit_score ? Math.round(stats.current_habit_score) : 0}
              </span>
              <span className="text-slate-400 text-lg mb-1">/ 100</span>
            </div>
            <div className="w-full bg-surface-700 rounded-full h-2 mt-3">
              <div
                className="h-2 rounded-full gradient-accent transition-all duration-1000"
                style={{ width: `${stats?.current_habit_score || 0}%` }}
              />
            </div>
          </div>
        </motion.div>
      </div>
    </div>
  );
}

// ─── Sub-components ───

function StatCard({ icon: Icon, label, value, color }) {
  return (
    <div className="stat-card">
      <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${color} flex items-center justify-center mb-2`}>
        <Icon className="w-5 h-5 text-white" />
      </div>
      <p className="stat-value">{value}</p>
      <p className="text-sm text-slate-400">{label}</p>
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
    <Link
      to={to}
      className={className}
    >
      <Icon className="w-5 h-5" />
      <span className="text-sm font-medium text-white">{label}</span>
    </Link>
  );
}
