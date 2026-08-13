/**
 * Presentational primitives shared by every Wellness Coach dashboard panel.
 *
 * Each panel is API-driven, so the loading / error / empty vocabulary lives
 * here once: `PanelSkeleton`, `PanelError`, `EmptyState`, and `EmptyChart`.
 * Panels never fabricate zeros for missing data — they render one of these.
 */
import React from 'react';
import {
  HiOutlineArrowPath,
  HiOutlineChevronLeft,
  HiOutlineChevronRight,
  HiOutlineExclamationTriangle,
} from 'react-icons/hi2';
import { CATEGORY_STYLES } from './constants';

export function StatCard({ icon: Icon, label, value, color, hint }) {
  return (
    <div className="stat-card" title={hint || undefined}>
      <div className={`w-10 h-10 rounded-xl bg-gradient-to-br ${color} flex items-center justify-center mb-2`}>
        <Icon className="w-5 h-5 text-white" />
      </div>
      <p className="stat-value">{value}</p>
      <p className="text-sm text-slate-400">{label}</p>
      {hint ? <p className="text-xs text-slate-500 mt-1">{hint}</p> : null}
    </div>
  );
}

export function MiniStat({ icon: Icon, label, value }) {
  return (
    <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 px-3 py-3">
      <div className="flex items-center gap-1.5 text-[10px] uppercase tracking-wider text-slate-500 mb-1">
        <Icon className="w-3.5 h-3.5" />
        {label}
      </div>
      <p className="text-sm font-semibold text-white truncate capitalize">{value}</p>
    </div>
  );
}

export function MetricBlock({ title, description, trend, TrendIcon, rows }) {
  return (
    <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 p-4">
      <div className="flex items-center justify-between gap-2 mb-1">
        <p className="text-sm font-medium text-white">{title}</p>
        {trend ? (
          <span className={`inline-flex items-center gap-1 text-[11px] flex-shrink-0 ${trend.color}`}>
            {TrendIcon ? <TrendIcon className="w-3.5 h-3.5" /> : null}
            {trend.label}
          </span>
        ) : null}
      </div>
      {description ? (
        <p className="text-xs text-slate-500 leading-relaxed mb-3">{description}</p>
      ) : null}
      <dl className="space-y-2">
        {rows.map(([label, value, hint]) => (
          <div
            key={label}
            className="flex items-center justify-between text-sm gap-3"
            title={hint || undefined}
          >
            <dt className="text-slate-400">{label}</dt>
            <dd className="text-slate-200 font-medium truncate capitalize">{value}</dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

export function ProfileField({ label, value, hint }) {
  return (
    <div>
      <dt className="text-[10px] uppercase tracking-wider text-slate-500 mb-1">{label}</dt>
      <dd className="text-sm font-medium text-white break-words">{value}</dd>
      {hint ? <p className="text-xs text-slate-500 mt-0.5">{hint}</p> : null}
    </div>
  );
}

export function PriorityBadge({ priority }) {
  const styles = {
    high: 'bg-red-500/15 text-red-400',
    medium: 'bg-amber-500/15 text-amber-400',
    low: 'bg-slate-500/20 text-slate-300',
  };
  return (
    <span className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full ${styles[priority] || styles.low}`}>
      {priority}
    </span>
  );
}

export function RecCard({ rec, emphasize = false }) {
  return (
    <div
      className={`rounded-xl border p-4 ${emphasize || rec.category === 'productivity'
        ? 'border-sky-500/30 bg-sky-500/5'
        : 'border-surface-700/50 bg-surface-900/40'
        }`}
    >
      <div className="flex flex-wrap items-center gap-2 mb-1.5">
        <span
          className={`text-[10px] uppercase tracking-wider px-2 py-0.5 rounded-full border ${CATEGORY_STYLES[rec.category] || CATEGORY_STYLES.habit
            }`}
        >
          {rec.category}
        </span>
        <PriorityBadge priority={rec.priority} />
        <p className="text-sm font-medium text-white">{rec.title}</p>
      </div>
      <p className="text-sm text-slate-400 leading-relaxed">{rec.detail}</p>
    </div>
  );
}

export function EmptyState({ icon: Icon, title, message }) {
  return (
    <div className="py-12 text-center">
      <Icon className="w-10 h-10 text-slate-600 mx-auto mb-3" />
      <p className="text-sm font-medium text-slate-300 mb-1">{title}</p>
      <p className="text-sm text-slate-500 max-w-md mx-auto">{message}</p>
    </div>
  );
}

export function EmptyChart({ message }) {
  return <p className="text-sm text-slate-500 py-10 text-center">{message}</p>;
}

/** Placeholder shown while a panel's own request is still in flight. */
export function PanelSkeleton({ rows = 3, className = '' }) {
  return (
    <div className={`animate-pulse space-y-3 ${className}`} aria-hidden="true">
      {Array.from({ length: rows }).map((_, index) => (
        <div key={index} className="h-16 rounded-xl bg-surface-800/60" />
      ))}
    </div>
  );
}

/**
 * Failure state for a single panel.
 *
 * Distinguishes "this request failed" from "this client has no data",
 * so a coach is never shown an empty chart when the fetch actually broke.
 */
export function PanelError({ message, onRetry }) {
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

export function ClientMetric({ label, value }) {
  return (
    <div className="text-right">
      <p className="text-[10px] uppercase tracking-wider text-slate-500">{label}</p>
      <p className="text-sm font-semibold text-slate-200">{value}</p>
    </div>
  );
}

export function Pagination({ page, totalPages, onPrev, onNext }) {
  return (
    <div className="flex items-center justify-between mt-4 pt-4 border-t border-surface-700/30">
      <p className="text-xs text-slate-500">
        Page {page} of {totalPages}
      </p>
      <div className="flex gap-2">
        <button
          type="button"
          onClick={onPrev}
          disabled={page <= 1}
          aria-label="Previous page"
          className="p-2 rounded-lg border border-surface-700/50 bg-surface-800 text-slate-400 hover:text-white transition disabled:opacity-40 disabled:hover:text-slate-400"
        >
          <HiOutlineChevronLeft className="w-4 h-4" />
        </button>
        <button
          type="button"
          onClick={onNext}
          disabled={page >= totalPages}
          aria-label="Next page"
          className="p-2 rounded-lg border border-surface-700/50 bg-surface-800 text-slate-400 hover:text-white transition disabled:opacity-40 disabled:hover:text-slate-400"
        >
          <HiOutlineChevronRight className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}
