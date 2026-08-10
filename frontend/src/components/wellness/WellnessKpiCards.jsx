/**
 * Roster-wide KPI cards, backed by GET /coach/overview.
 *
 * Every figure is computed server-side across the coach's assigned clients for
 * the selected window. When the overview request fails the whole strip is
 * replaced with an error — a zeroed card would read as a real measurement.
 */
import React from 'react';
import { motion } from 'framer-motion';
import {
  HiOutlineChartBar,
  HiOutlineExclamationTriangle,
  HiOutlineTrophy,
  HiOutlineUsers,
} from 'react-icons/hi2';
import { PanelError, StatCard } from './primitives';
import { fadeUp } from './constants';
import { formatHabitScore } from '../../utils/habitScore';

export default function WellnessKpiCards({ overview, days, error, onRetry }) {
  if (error && !overview) {
    return (
      <motion.div id="coach-overview" {...fadeUp} transition={{ delay: 0.04 }} className="scroll-mt-6">
        <PanelError message="Roster KPIs could not be loaded." onRetry={onRetry} />
      </motion.div>
    );
  }

  const hasClients = Boolean(overview?.active_clients);

  return (
    <motion.div
      id="coach-overview"
      {...fadeUp}
      transition={{ delay: 0.04 }}
      className="grid grid-cols-2 lg:grid-cols-4 gap-4 scroll-mt-6"
    >
      <StatCard
        icon={HiOutlineUsers}
        label="Assigned Clients"
        value={overview?.active_clients ?? 0}
        color="from-violet-500 to-violet-700"
        hint="Active clients currently assigned to you"
      />
      <StatCard
        icon={HiOutlineTrophy}
        label="Average Habit Score"
        value={hasClients ? formatHabitScore(overview.avg_habit_score) : '—'}
        color="from-accent-500 to-accent-700"
        hint="Mean of the current habit scores of your active clients"
      />
      <StatCard
        icon={HiOutlineExclamationTriangle}
        label="Needs Attention"
        value={overview?.needs_attention_count ?? 0}
        color="from-orange-500 to-red-600"
        hint="Based on habit score, wake consistency, and recent wake activity"
      />
      <StatCard
        icon={HiOutlineChartBar}
        label="Engagement"
        value={hasClients ? `${Math.round(overview.engagement_rate)}%` : '—'}
        color="from-sky-500 to-indigo-600"
        hint={
          hasClients
            ? `${overview.engaged_clients} of ${overview.active_clients} active clients had wake or challenge activity in ${overview.days} days`
            : `Wake or challenge activity in the last ${overview?.days ?? days} days`
        }
      />
    </motion.div>
  );
}
