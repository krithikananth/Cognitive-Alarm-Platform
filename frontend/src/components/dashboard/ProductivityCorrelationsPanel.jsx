/**
 * ProductivityCorrelationsPanel — renders the `correlations` block returned by
 * GET /dashboard/productivity (same payload as
 * GET /analytics/behavioral/productivity-correlation).
 *
 * Each row is a real Pearson/Spearman coefficient with a Fisher-z p-value.
 * Pairs that could not be measured say why (too few paired days, or a series
 * that never varied) instead of showing a misleading zero.
 */
import React from 'react';
import {
    HiOutlineArrowTrendingDown, HiOutlineArrowTrendingUp,
    HiOutlineInformationCircle, HiOutlineScale,
} from 'react-icons/hi2';

const STRENGTH_LABELS = {
    negligible: 'Negligible',
    weak: 'Weak',
    moderate: 'Moderate',
    strong: 'Strong',
    very_strong: 'Very strong',
    undefined: '—',
};

const UNMEASURED_REASON = {
    insufficient_data: 'Not enough paired days yet',
    no_variance: 'This behaviour never changed',
};

function CoefficientBar({ r }) {
    const magnitude = Math.min(Math.abs(r), 1);
    const positive = r > 0;
    return (
        <div className="flex items-center gap-2">
            <div className="relative h-1.5 w-24 rounded-full bg-surface-700">
                <div
                    className={`absolute top-0 h-1.5 rounded-full ${positive ? 'bg-emerald-400' : 'bg-orange-400'}`}
                    style={{
                        width: `${(magnitude / 2) * 100}%`,
                        left: positive ? '50%' : `${50 - (magnitude / 2) * 100}%`,
                    }}
                />
                <div className="absolute left-1/2 top-[-2px] h-2.5 w-px bg-surface-500" />
            </div>
            <span className={`text-xs tabular-nums ${positive ? 'text-emerald-300' : 'text-orange-300'}`}>
                {r > 0 ? '+' : ''}{r.toFixed(2)}
            </span>
        </div>
    );
}

export default function ProductivityCorrelationsPanel({ correlations }) {
    if (!correlations) return null;

    const measured = (correlations.pairs || []).filter((p) => p.status === 'ok');
    const significant = measured.filter((p) => p.significant);
    const unmeasured = (correlations.pairs || []).filter((p) => p.status !== 'ok');

    return (
        <div className="card">
            <div className="flex flex-wrap items-center justify-between gap-3 mb-4">
                <h2 className="text-lg font-semibold text-white flex items-center gap-2">
                    <HiOutlineScale className="w-5 h-5 text-teal-400" />
                    Behaviour ↔ Productivity Correlations
                </h2>
                <span className="text-[11px] text-slate-500">
                    {correlations.days_analyzed} active day{correlations.days_analyzed === 1 ? '' : 's'} analysed
                </span>
            </div>

            {correlations.status !== 'ok' ? (
                <p className="text-sm text-slate-500 py-8 text-center">
                    {correlations.insights?.[0] ||
                        'Not enough paired history yet to correlate your wake behaviour with productivity.'}
                </p>
            ) : (
                <>
                    {significant.length === 0 && (
                        <div className="rounded-xl border border-surface-700/50 bg-surface-900/30 p-4 mb-4 flex items-start gap-2">
                            <HiOutlineInformationCircle className="w-4 h-4 text-slate-400 mt-0.5 shrink-0" />
                            <p className="text-xs text-slate-400">
                                No statistically significant relationships yet (p &lt; {correlations.method?.alpha}).
                                Keep using your alarms — patterns need more days to separate from noise.
                            </p>
                        </div>
                    )}

                    <div className="space-y-2">
                        {measured.map((pair) => {
                            const Icon = pair.pearson_r > 0 ? HiOutlineArrowTrendingUp : HiOutlineArrowTrendingDown;
                            return (
                                <div
                                    key={pair.id}
                                    className={`rounded-xl border p-3 ${pair.significant
                                            ? 'border-teal-500/25 bg-teal-500/5'
                                            : 'border-surface-700/50 bg-surface-900/30'
                                        }`}
                                >
                                    <div className="flex flex-wrap items-center justify-between gap-2">
                                        <div className="flex items-center gap-2 min-w-0">
                                            <Icon
                                                className={`w-4 h-4 shrink-0 ${pair.pearson_r > 0 ? 'text-emerald-400' : 'text-orange-400'
                                                    }`}
                                            />
                                            <p className="text-sm text-slate-200 truncate">
                                                <span className="capitalize">{pair.behavior_label}</span>
                                                <span className="text-slate-500"> vs </span>
                                                {pair.outcome_label}
                                            </p>
                                        </div>
                                        <div className="flex items-center gap-3">
                                            <CoefficientBar r={pair.pearson_r} />
                                            {pair.significant && (
                                                <span className="rounded-md border border-teal-500/25 bg-teal-500/10 px-1.5 py-0.5 text-[10px] text-teal-300">
                                                    Significant
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                    <p className="mt-1.5 text-[11px] text-slate-500 pl-6">
                                        {STRENGTH_LABELS[pair.strength] || pair.strength} {pair.direction} · r={pair.pearson_r} ·
                                        {' '}rho={pair.spearman_rho} · p={pair.p_value} · n={pair.n}
                                    </p>
                                </div>
                            );
                        })}
                    </div>

                    {unmeasured.length > 0 && (
                        <details className="mt-4">
                            <summary className="cursor-pointer text-xs text-primary-300 hover:text-primary-200 transition">
                                {unmeasured.length} pair{unmeasured.length === 1 ? '' : 's'} not measurable yet
                            </summary>
                            <ul className="mt-2 space-y-1">
                                {unmeasured.map((pair) => (
                                    <li key={pair.id} className="text-[11px] text-slate-500">
                                        <span className="capitalize">{pair.behavior_label}</span> vs {pair.outcome_label} —{' '}
                                        {UNMEASURED_REASON[pair.status] || pair.status} ({pair.n}/{pair.min_pairs} days)
                                    </li>
                                ))}
                            </ul>
                        </details>
                    )}

                    <p className="mt-4 text-[10px] text-slate-600">
                        Pearson &amp; Spearman coefficients, two-sided significance via the Fisher
                        z-transformation. Correlation is not causation.
                    </p>
                </>
            )}
        </div>
    );
}
