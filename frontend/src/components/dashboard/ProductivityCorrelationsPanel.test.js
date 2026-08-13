/**
 * ProductivityCorrelationsPanel render tests.
 *
 * The panel must never imply a relationship it did not measure: unmeasurable
 * pairs have to state why, and a run with no significant results must say so
 * rather than leaving the reader to assume the listed pairs matter.
 */
import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import ProductivityCorrelationsPanel from './ProductivityCorrelationsPanel';

function pair(overrides = {}) {
    return {
        id: 'snooze_vs_accuracy',
        behavior: 'snooze_count',
        behavior_label: 'daily snoozes',
        outcome: 'challenge_accuracy',
        outcome_label: 'challenge accuracy',
        expected_direction: 'negative',
        status: 'ok',
        n: 14,
        min_pairs: 5,
        pearson_r: -0.82,
        spearman_rho: -0.8,
        p_value: 0.0003,
        significant: true,
        strength: 'very_strong',
        direction: 'negative',
        interpretation: 'Very strong negative link.',
        ...overrides,
    };
}

function payload(overrides = {}) {
    return {
        status: 'ok',
        method: {
            coefficients: ['pearson', 'spearman'],
            significance_test: 'fisher_z',
            alpha: 0.05,
            min_pairs: 5,
        },
        window_days: 30,
        days_analyzed: 14,
        pairs: [pair()],
        significant_findings: ['snooze_vs_accuracy'],
        strongest: pair(),
        insights: ['Very strong negative link.'],
        ...overrides,
    };
}

describe('ProductivityCorrelationsPanel gating', () => {
    test('renders nothing without a correlations block', () => {
        const { container } = render(<ProductivityCorrelationsPanel correlations={null} />);

        expect(container).toBeEmptyDOMElement();
    });

    test('insufficient data shows the reason, not an empty chart', () => {
        render(
            <ProductivityCorrelationsPanel
                correlations={payload({
                    status: 'insufficient_data',
                    days_analyzed: 2,
                    pairs: [pair({ status: 'insufficient_data', n: 2, pearson_r: null, significant: false })],
                    significant_findings: [],
                    strongest: null,
                    insights: ['Not enough paired daily history to run correlation analysis.'],
                })}
            />
        );

        expect(
            screen.getByText(/Not enough paired daily history/i)
        ).toBeInTheDocument();
        expect(screen.getByText(/2 active days analysed/i)).toBeInTheDocument();
    });
});

describe('ProductivityCorrelationsPanel measured pairs', () => {
    test('a significant pair shows its coefficient and stats', () => {
        render(<ProductivityCorrelationsPanel correlations={payload()} />);

        expect(screen.getByText('daily snoozes')).toBeInTheDocument();
        expect(screen.getByText('challenge accuracy')).toBeInTheDocument();
        expect(screen.getByText('Significant')).toBeInTheDocument();
        expect(screen.getByText('-0.82')).toBeInTheDocument();
        expect(
            screen.getByText(/r=-0.82.*rho=-0.8.*p=0.0003.*n=14/s)
        ).toBeInTheDocument();
    });

    test('no significant results are called out explicitly', () => {
        render(
            <ProductivityCorrelationsPanel
                correlations={payload({
                    pairs: [pair({ significant: false, pearson_r: 0.12, strength: 'negligible', direction: 'positive' })],
                    significant_findings: [],
                    strongest: null,
                })}
            />
        );

        expect(
            screen.getByText(/No statistically significant relationships yet/i)
        ).toBeInTheDocument();
        expect(screen.queryByText('Significant')).not.toBeInTheDocument();
    });

    test('positive and negative coefficients are signed', () => {
        render(
            <ProductivityCorrelationsPanel
                correlations={payload({
                    pairs: [
                        pair({ id: 'a', pearson_r: 0.64, direction: 'positive' }),
                        pair({ id: 'b', pearson_r: -0.64, direction: 'negative' }),
                    ],
                })}
            />
        );

        expect(screen.getByText('+0.64')).toBeInTheDocument();
        expect(screen.getByText('-0.64')).toBeInTheDocument();
    });
});

describe('ProductivityCorrelationsPanel unmeasurable pairs', () => {
    test('insufficient-data and no-variance pairs explain themselves', () => {
        render(
            <ProductivityCorrelationsPanel
                correlations={payload({
                    pairs: [
                        pair(),
                        pair({
                            id: 'sleep_duration_vs_accuracy',
                            behavior_label: 'measured sleep duration',
                            status: 'insufficient_data',
                            n: 1,
                            pearson_r: null,
                            significant: false,
                        }),
                        pair({
                            id: 'snooze_vs_wakefulness',
                            outcome_label: 'wakefulness score',
                            status: 'no_variance',
                            n: 14,
                            pearson_r: null,
                            significant: false,
                        }),
                    ],
                })}
            />
        );

        fireEvent.click(screen.getByText(/2 pairs not measurable yet/i));

        expect(screen.getByText(/Not enough paired days yet/i)).toBeInTheDocument();
        expect(screen.getByText(/This behaviour never changed/i)).toBeInTheDocument();
    });

    test('unmeasurable pairs never render a coefficient bar', () => {
        render(
            <ProductivityCorrelationsPanel
                correlations={payload({
                    status: 'ok',
                    pairs: [
                        pair({ status: 'no_variance', pearson_r: null, significant: false }),
                    ],
                    significant_findings: [],
                    strongest: null,
                })}
            />
        );

        expect(screen.queryByText(/^[+-]?\d\.\d\d$/)).not.toBeInTheDocument();
    });

    test('the statistical method is disclosed', () => {
        render(<ProductivityCorrelationsPanel correlations={payload()} />);

        expect(screen.getByText(/Fisher\s+z-transformation/i)).toBeInTheDocument();
        expect(screen.getByText(/Correlation is not causation/i)).toBeInTheDocument();
    });
});
