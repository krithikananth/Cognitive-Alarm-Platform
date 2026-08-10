/**
 * Personalized Coaching — the highest-priority non-productivity guidance from
 * GET /coach/clients/{id}/recommendations.
 *
 * The rule engine that produces this is the same one that feeds the client's
 * own in-app feed, so coach and client are never advised differently.
 */
import React, { useMemo } from 'react';
import { motion } from 'framer-motion';
import { HiOutlineLightBulb } from 'react-icons/hi2';
import { PanelError, RecCard } from './primitives';
import { fadeUp } from './constants';

export default function PersonalizedCoaching({ digest, clientName, error, onRetry }) {
  const recommendations = useMemo(
    () => (digest?.recommendations || []).filter((r) => r.category !== 'productivity').slice(0, 5),
    [digest]
  );

  return (
    <motion.div {...fadeUp} transition={{ delay: 0.2 }} className="card">
      <div className="flex items-center justify-between mb-1">
        <h2 className="text-lg font-semibold text-white flex items-center gap-2">
          <HiOutlineLightBulb className="w-5 h-5 text-amber-400" />
          Personalized Coaching
        </h2>
        {digest?.summary?.top_focus_label && (
          <span className="text-xs px-2.5 py-1 rounded-full bg-surface-700 text-slate-300">
            Focus: {digest.summary.top_focus_label}
          </span>
        )}
      </div>
      <p className="text-xs text-slate-500 mb-4">
        Highest-priority guidance derived from {clientName || 'this client'}’s own wake, snooze,
        sleep, and challenge records.
      </p>

      {error && !digest ? (
        <PanelError message={error} onRetry={onRetry} />
      ) : !recommendations.length ? (
        <p className="text-sm text-slate-500 py-6 text-center">
          No data available for this period. A few verified wake-ups let the engine tailor
          sleep, wake, and habit guidance for this client.
        </p>
      ) : (
        <div className="space-y-3">
          {recommendations.map((rec) => (
            <RecCard key={rec.id} rec={rec} />
          ))}
        </div>
      )}
    </motion.div>
  );
}
