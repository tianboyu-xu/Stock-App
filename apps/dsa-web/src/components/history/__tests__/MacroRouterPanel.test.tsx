import { fireEvent, render, screen, within } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import type { AutoTuneResponse, MacroRouterReport } from '../../../api/stocks';
import { MacroRouterPanel } from '../MacroRouterPanel';
import { strategyPresentation } from '../autoTunePresentation';

const report: MacroRouterReport = {
  strategyKey: 'MATR', version: 1, status: 'READY',
  current: {
    quarter: '2026Q3', featureQuarter: '2026Q2', asOf: '2026-07-01', snapshotId: 'historical-vintage-q3',
    regime: { key: 'goldilocks', factors: { growth: 0.4, inflation: -0.2 } },
    selectedStrategy: 'CASH', confidence: 'low', scoreGap: 0.001, trainingQuarters: 16,
    ranking: [{ strategyKey: 'CASH', expectedUtility: 0, analogUtility: 0 },
      { strategyKey: 'C', expectedUtility: -0.021, analogUtility: -0.014 }],
    topFeatures: ['growth', 'inflation'],
  },
  correlations: [{ feature: 'growth', strategyKey: 'C', correlation: -0.3, signStability: 0.8, sampleCount: 16 }],
  history: [{ quarter: '2026Q2', selectedStrategy: 'C', regime: 'reflation', netReturnPct: -2.1,
    spyReturnPct: 1.5, regret: 0.023, utility: -0.03,
    windows: [{ startDate: '2026-04-01', endDate: '2026-04-14', strategyKey: 'C',
      entryDate: '2026-04-02', exitDate: '2026-04-10', netReturnPct: -2.1, spyReturnPct: 0.5, utility: -0.03 }],
  }],
  diagnostics: { oosQuarters: 1, meanRegret: 0.023, totalReturnPct: -2.1,
    spyTotalReturnPct: 1.5, winRatePct: 0, beatSpyRatePct: 0 },
};

describe('MATR macro strategy report', () => {
  it('uses the router evaluation dates and SPY basis instead of the global A–F test split', () => {
    const envelope = { strategies: [], testPrices: { dates: ['2025-01-01'], values: [999] },
      macroRouter: { ...report, targetCagr: 0.2,
        testEquity: { dates: ['2021-01-04', '2021-01-05'], values: [0, 2] },
        benchmarkEquity: { dates: ['2021-01-04', '2021-01-05'], values: [0, 1] },
        testPrices: { dates: ['2021-01-04', '2021-01-05'], values: [100, 102] },
      } } as unknown as AutoTuneResponse;
    const view = strategyPresentation(envelope, 'macro_router');
    expect(view.curve.map(row => row.benchmarkNav)).toEqual([1, 1.01]);
    expect(view.prices.map(row => row.price)).toEqual([100, 102]);
    expect(view.target).toBe(0.2);
  });
  it('separates quarter-start estimates, cash choice, utility scores and realized returns', () => {
    render(<MacroRouterPanel report={report} language="en" />);
    expect(screen.getByText('Goldilocks')).toBeInTheDocument();
    expect(screen.getByText(/Prior-quarter observations.*2026Q2/)).toBeInTheDocument();
    expect(screen.getByText(/Known by 2026-07-01.*not a confirmed current economic phase/)).toBeInTheDocument();
    expect(screen.getAllByText('CASH · stay in cash')).toHaveLength(2);
    const ranking = screen.getByRole('table', { name: 'Current quarter strategy ranking' });
    expect(within(ranking).getByText('-0.021')).toBeInTheDocument();
    expect(within(ranking).queryByText('-2.10%')).not.toBeInTheDocument();
    expect(screen.getByText(/Confidence: low/)).toBeInTheDocument();
    expect(screen.getByLabelText('Out-of-sample results')).toHaveTextContent('Net return: -2.10%');
    fireEvent.click(screen.getByText('Historical quarter and two-week window results (1)'));
    fireEvent.click(screen.getByText(/2026Q2 · Strategy C/));
    expect(screen.getByRole('table', { name: '2026Q2 trade windows' })).toHaveTextContent('2026-04-02 / 2026-04-10');
    expect(screen.getByText(/at most 1 buy \+ 1 sell per window/)).toBeInTheDocument();
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });

  it('shows a missing FRED key and rerun instructions instead of inventing a phase', () => {
    render(<MacroRouterPanel report={{ strategyKey: 'MATR', version: 1, status: 'UNAVAILABLE',
      reason: 'FRED_API_KEY_MISSING', correlations: [], history: [] }} language="zh" />);
    expect(screen.getByRole('status')).toHaveTextContent('FRED_API_KEY_MISSING');
    expect(screen.getByRole('status')).toHaveTextContent('在服务端配置 FRED_API_KEY');
    expect(screen.queryByText('季初宏观阶段估计')).not.toBeInTheDocument();
  });

  it('explains an old cached report without macro data', () => {
    render(<MacroRouterPanel language="en" />);
    expect(screen.getByRole('status')).toHaveTextContent('Run Auto Tune to include MATR in the strategy comparison');
    expect(screen.queryByRole('table')).not.toBeInTheDocument();
  });

  it('shows cash abstention, realized exposure and causal family attribution separately', () => {
    render(<MacroRouterPanel language="en" report={{ ...report, version: 2,
      current: { ...report.current!, cashMargin: 0.02, confidenceThreshold: 0.003 },
      diagnostics: { ...report.diagnostics!, startDate: '2020-04-01', endDate: '2026-06-30',
        cashQuarterRatePct: 92, tradeCount: 9, activeWindowRatePct: 6.5, exposureRatePct: 4.2,
        familyComparisons: [{ strategyKey: 'A', oosQuarters: 25, totalReturnPct: 31.2,
          maxDrawdownPct: 12.3, tradeCount: 42, activeWindowRatePct: 34.5, exposureRatePct: 23.4 }],
      },
    }} />);
    const results = screen.getByLabelText('Out-of-sample results');
    expect(results).toHaveTextContent('Cash quarters: 92.0%');
    expect(results).toHaveTextContent('Trades: 9');
    expect(results).toHaveTextContent('Windows with trades: 6.5%');
    expect(results).toHaveTextContent('Sessions with exposure: 4.2%');
    expect(screen.getByText(/Advantage over cash \/ required margin/)).toHaveTextContent('0.020 / 0.003');
    expect(screen.getByText(/These totals use completed quarters/)).toBeInTheDocument();
    fireEvent.click(screen.getByText('Routing attribution: each family with the same two-week execution'));
    const table = screen.getByRole('table', { name: 'Two-week family comparisons' });
    expect(table).toHaveTextContent('Strategy A');
    expect(table).toHaveTextContent('+31.20%');
    expect(table).toHaveTextContent('12.30%');
    expect(table).toHaveTextContent('42');
  });
});
