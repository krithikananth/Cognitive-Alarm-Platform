/**
 * SleepPatternsPanel — measured sleep sessions from GET /analytics/behavioral/sleep-patterns.
 *
 * Recorded nights (the user logged sleep.started / sleep.ended) are always
 * labelled separately from estimated nights, which are inferred from the last
 * app interaction before a verified wake. An estimate is never presented as
 * recorded sleep, and nights with neither source show "—" instead of a guess.
 */
import React, { useMemo, useState } from 'react';
import {
    HiOutlineMoon, HiOutlineArrowTrendingUp, HiOutlineArrowTrendingDown,
    HiOutlineMinus, HiOutlineInformationCircle, HiOutlinePlus,
} from 'react-icons/hi2';
import {
    Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts';

const CHART_TOOLTIP_STYLE = {
    contentStyle: { background: '#1e293b', border: '1px solid #334155', borderRadius: 12 },
    labelStyle: { color: '#e2e8f0' },
};

const SOURCE_BADGE = {
    recorded: { label: 'Recorded', className: 'bg-emerald-500/10 text-emerald-300 border-emerald-500/20' },
    estimated: { label: 'Estimated', className: 'bg-amber-500/10 text-amber-300 border-amber-500/20' },
};

function trendMeta(direction) {
    if (direction === 'improving') {
        return { Icon: HiOutlineArrowTrendingUp, label: 'Closer to target', color: 'text-emerald-400' };
    }
    if (direction === 'declining') {
        return { Icon: HiOutlineArrowTrendingDown, label: 'Drifting from target', color: 'text-orange-400' };
    }
    if (direction === 'stable') {
        return { Icon: HiOutlineMinus, label: 'Stable', color: 'text-slate-300' };
    }
    return { Icon: HiOutlineMinus, label: 'Not enough data', color: 'text-slate-500' };
}

function hours(value) {
    if (value == null) return '—';
    const whole = Math.floor(value);
    const minutes = Math.round((value - whole) * 60);
    return `${whole}h ${String(minutes).padStart(2, '0')}m`;
}

function Metric({ label, value, hint }) {
    return (
        <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 p-4">
            <p className="text-xs text-slate-400 mb-1">{label}</p>
            <p className="text-xl font-semibold text-white">{value}</p>
            {hint && <p className="text-[10px] text-slate-600 mt-1">{hint}</p>}
        </div>
    );
}

export default function SleepPatternsPanel({ sleep, onLogSleep, logging }) {
    const [showNights, setShowNights] = useState(false);

    const chartData = useMemo(
        () =>
            (sleep?.nights || [])
                .filter((n) => n.sleep_duration_hours != null)
                .map((n) => ({
                    date: n.date.slice(5),
                    hours: n.sleep_duration_hours,
                    source: n.source,
                })),
        [sleep]
    );

    const TrendIcon = trendMeta(sleep?.trend).Icon;
    const trend = trendMeta(sleep?.trend);
    const hasNights = (sleep?.nights_observed || 0) > 0;
    const hasDurations = (sleep?.nights_with_duration || 0) > 0;

    return (
        <div className="card">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                    <HiOutlineMoon className="w-5 h-5 text-indigo-400" />
                    Sleep Patterns
                </h2>
                <div className="flex items-center gap-3">
                    {hasDurations && (
                        <span className={`inline-flex items-center gap-1 text-[11px] ${trend.color}`}>
                            <TrendIcon className="w-3.5 h-3.5" />
                            {trend.label}
                        </span>
                    )}
                    <button
                        type="button"
                        onClick={onLogSleep}
                        disabled={logging}
                        className="inline-flex items-center gap-1 rounded-lg border border-surface-700/60 px-2.5 py-1.5 text-xs text-slate-200 transition hover:border-indigo-500/40 hover:text-white disabled:opacity-50"
                    >
                        <HiOutlinePlus className="w-3.5 h-3.5" />
                        {logging ? 'Saving…' : 'Log sleep now'}
                    </button>
                </div>
            </div>

            {!hasNights ? (
                <p className="text-sm text-slate-500 py-8 text-center">
                    No sleep history yet. Log when you go to sleep, or complete a verified
                    wake-up, and your nightly duration and regularity will appear here.
                </p>
            ) : (
                <>
                    <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3 mb-4">
                        <Metric
                            label="Avg duration"
                            value={hours(sleep.avg_sleep_duration_hours)}
                            hint={`Target ${hours(sleep.target_sleep_hours)}`}
                        />
                        <Metric label="Avg bedtime" value={sleep.avg_bedtime || '—'} />
                        <Metric label="Avg wake time" value={sleep.avg_wake_time || '—'} />
                        <Metric
                            label="Schedule regularity"
                            value={hasDurations ? `${Math.round(sleep.schedule_regularity_score)}/100` : '—'}
                            hint="Higher = more consistent clock times"
                        />
                    </div>

                    <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 p-4 mb-4">
                        <div className="flex items-start gap-2">
                            <HiOutlineInformationCircle className="w-4 h-4 text-slate-400 mt-0.5 shrink-0" />
                            <div className="text-xs text-slate-400 space-y-1">
                                <p>
                                    <span className="text-emerald-300">{sleep.nights_recorded}</span> night
                                    {sleep.nights_recorded === 1 ? '' : 's'} recorded from your own sleep logs
                                    {' · '}
                                    <span className="text-amber-300">{sleep.nights_estimated}</span> estimated
                                    from your last activity before waking.
                                </p>
                                {!sleep.has_recorded_sleep && (
                                    <p className="text-slate-500">
                                        Estimated nights are an upper bound on real sleep. Use “Log sleep now”
                                        at bedtime to record actual sleep times.
                                    </p>
                                )}
                                {sleep.nights_with_duration < sleep.nights_observed && (
                                    <p className="text-slate-500">
                                        {sleep.nights_observed - sleep.nights_with_duration} night
                                        {sleep.nights_observed - sleep.nights_with_duration === 1 ? '' : 's'} have
                                        no sleep start on record, so no duration is shown for them.
                                    </p>
                                )}
                            </div>
                        </div>
                    </div>

                    {chartData.length > 0 && (
                        <div className="mb-4">
                            <h3 className="text-sm font-semibold text-white mb-3">Nightly duration</h3>
                            <div className="h-48">
                                <ResponsiveContainer width="100%" height="100%">
                                    <BarChart data={chartData}>
                                        <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                                        <XAxis dataKey="date" stroke="#94a3b8" tick={{ fontSize: 11 }} />
                                        <YAxis stroke="#94a3b8" tick={{ fontSize: 12 }} unit="h" />
                                        <Tooltip {...CHART_TOOLTIP_STYLE} formatter={(v) => [`${v}h`, 'Slept']} />
                                        <Bar dataKey="hours" fill="#818cf8" radius={[8, 8, 0, 0]} name="Hours slept" />
                                    </BarChart>
                                </ResponsiveContainer>
                            </div>
                        </div>
                    )}

                    <div className="grid sm:grid-cols-2 lg:grid-cols-4 gap-3">
                        <Metric
                            label="Social jetlag"
                            value={sleep.social_jetlag_minutes != null ? `${Math.round(sleep.social_jetlag_minutes)} min` : '—'}
                            hint="Weekend vs weekday mid-sleep"
                        />
                        <Metric
                            label="Sleep debt"
                            value={sleep.avg_sleep_debt_hours != null ? `${sleep.avg_sleep_debt_hours > 0 ? '−' : '+'}${hours(Math.abs(sleep.avg_sleep_debt_hours))}` : '—'}
                            hint="Per night vs target"
                        />
                        <Metric label="Short nights" value={`${sleep.short_sleep_nights} under 6h`} />
                        <Metric label="Long nights" value={`${sleep.long_sleep_nights} over 9h`} />
                    </div>

                    {(sleep.nights || []).length > 0 && (
                        <div className="mt-4">
                            <button
                                type="button"
                                onClick={() => setShowNights((v) => !v)}
                                className="text-xs text-primary-300 hover:text-primary-200 transition"
                            >
                                {showNights ? 'Hide nightly breakdown' : 'Show nightly breakdown'}
                            </button>
                            {showNights && (
                                <div className="mt-3 overflow-x-auto">
                                    <table className="w-full text-xs">
                                        <thead>
                                            <tr className="text-slate-400 border-b border-surface-700/50">
                                                <th className="text-left py-2 pr-3 font-medium">Date</th>
                                                <th className="text-left py-2 pr-3 font-medium">Bedtime</th>
                                                <th className="text-left py-2 pr-3 font-medium">Wake</th>
                                                <th className="text-left py-2 pr-3 font-medium">Slept</th>
                                                <th className="text-left py-2 font-medium">Source</th>
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {sleep.nights.map((night) => {
                                                const badge = SOURCE_BADGE[night.source] || SOURCE_BADGE.estimated;
                                                return (
                                                    <tr key={night.date} className="border-b border-surface-800/50">
                                                        <td className="py-2 pr-3 text-slate-300">
                                                            {night.date} <span className="text-slate-600">{night.weekday}</span>
                                                        </td>
                                                        <td className="py-2 pr-3 text-slate-300">{night.bedtime || '—'}</td>
                                                        <td className="py-2 pr-3 text-slate-300">{night.wake_time || '—'}</td>
                                                        <td className="py-2 pr-3 text-slate-300">
                                                            {night.sleep_duration_hours != null ? hours(night.sleep_duration_hours) : '—'}
                                                        </td>
                                                        <td className="py-2">
                                                            <span className={`inline-flex rounded-md border px-1.5 py-0.5 text-[10px] ${badge.className}`}>
                                                                {badge.label}
                                                            </span>
                                                        </td>
                                                    </tr>
                                                );
                                            })}
                                        </tbody>
                                    </table>
                                </div>
                            )}
                        </div>
                    )}
                </>
            )}
        </div>
    );
}
