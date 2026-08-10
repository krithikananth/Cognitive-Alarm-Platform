/**
 * Dashboard header: coach identity, section jump links, the 7/30/90-day
 * reporting-period selector, and refresh.
 *
 * The period selector is the single source of truth for every analytics panel
 * below it — changing it re-requests the roster and the selected client.
 */
import React from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineArrowPath,
  HiOutlineArrowRightOnRectangle,
  HiOutlineChartBar,
  HiOutlineMoon,
  HiOutlineSparkles,
  HiOutlineSquares2X2,
  HiOutlineSun,
  HiOutlineUserGroup,
} from 'react-icons/hi2';
import { WINDOW_OPTIONS, fadeUp } from './constants';

const SECTIONS = [
  { href: '#coach-overview', label: 'Overview', Icon: HiOutlineSquares2X2 },
  { href: '#coach-clients', label: 'Clients', Icon: HiOutlineUserGroup },
  { href: '#coach-analytics', label: 'Analytics', Icon: HiOutlineChartBar },
];

function greeting() {
  const hour = new Date().getHours();
  if (hour < 12) return { text: 'Good Morning', icon: HiOutlineSun, color: 'text-amber-400' };
  if (hour < 17) return { text: 'Good Afternoon', icon: HiOutlineSun, color: 'text-orange-400' };
  return { text: 'Good Evening', icon: HiOutlineMoon, color: 'text-indigo-400' };
}

export default function WellnessHeader({ user, days, onDaysChange, onRefresh, refreshing, onLogout }) {
  const g = greeting();
  const GIcon = g.icon;

  return (
    <motion.header
      {...fadeUp}
      className="overflow-hidden border border-surface-700/50 bg-surface-900/55 shadow-xl shadow-black/10"
    >
      <div className="flex flex-wrap items-center justify-between gap-5 px-5 py-5 sm:px-6">
        <div className="min-w-0">
          <div className="flex items-center gap-2 mb-1.5">
            <GIcon className={`w-5 h-5 ${g.color}`} />
            <span className="text-xs font-medium uppercase tracking-wider text-slate-400">
              {g.text}
            </span>
          </div>
          <h1 className="text-2xl font-bold text-white font-display flex items-center gap-2">
            <HiOutlineSparkles className="w-7 h-7 text-violet-400" />
            Wellness Coach Dashboard
          </h1>
          <p className="mt-1 text-sm text-slate-400">
            Monitor client wellbeing, routines, and coaching outcomes.
          </p>
        </div>

        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-full gradient-primary flex items-center justify-center text-sm font-bold flex-shrink-0">
            {(user?.full_name || user?.username || '?')[0].toUpperCase()}
          </div>
          <div className="min-w-0 hidden sm:block">
            <p className="text-sm font-semibold text-white truncate">
              {user?.full_name || user?.username}
            </p>
            <p className="text-xs text-slate-400 truncate">{user?.email}</p>
          </div>
          <span className="hidden md:inline-flex text-[10px] uppercase tracking-wider px-2 py-1 border border-emerald-500/25 bg-emerald-500/10 text-emerald-300">
            Wellness Coach
          </span>
          <button
            type="button"
            onClick={onLogout}
            title="Log out"
            className="inline-flex items-center gap-2 px-3 py-2 text-sm border border-surface-700/60 text-slate-300 hover:border-red-500/30 hover:bg-red-500/10 hover:text-red-300 transition"
          >
            <HiOutlineArrowRightOnRectangle className="w-4 h-4" />
            <span className="hidden sm:inline">Logout</span>
          </button>
        </div>
      </div>

      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-surface-700/40 px-4 py-3 sm:px-6">
        <nav className="flex items-center gap-1" aria-label="Dashboard navigation">
          {SECTIONS.map(({ href, label, Icon }) => (
            <a
              key={href}
              href={href}
              className="inline-flex items-center gap-1.5 px-2.5 py-2 text-xs font-medium text-slate-400 hover:bg-surface-800 hover:text-white transition"
            >
              <Icon className="w-4 h-4" />
              {label}
            </a>
          ))}
        </nav>

        <div className="flex items-center gap-2">
          <span className="hidden sm:inline text-xs text-slate-500">Reporting period</span>
          <div
            className="flex gap-1.5"
            role="group"
            aria-label="Reporting time range"
            data-testid="coach-time-range"
          >
            {WINDOW_OPTIONS.map((option) => (
              <button
                key={option}
                type="button"
                onClick={() => onDaysChange(option)}
                aria-pressed={days === option}
                data-testid={`coach-range-${option}`}
                title={`Report on the last ${option} days`}
                className={`text-xs px-3 py-1.5 rounded-lg border transition ${
                  days === option
                    ? 'bg-violet-500/20 text-violet-200 border-violet-500/40'
                    : 'bg-surface-800 text-slate-400 border-surface-700/50 hover:text-white'
                }`}
              >
                {option} Days
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={onRefresh}
            disabled={refreshing}
            title="Refresh coaching data"
            aria-label="Refresh wellness coach dashboard"
            className="p-2 rounded-xl border border-surface-700/50 bg-surface-800 text-slate-400 hover:text-white transition disabled:opacity-50"
          >
            <HiOutlineArrowPath className={`w-5 h-5 ${refreshing ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>
    </motion.header>
  );
}
