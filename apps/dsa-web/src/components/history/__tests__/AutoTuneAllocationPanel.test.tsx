import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { AllocationMetrics, AllocationReport } from '../../../api/stocks';
import { AutoTuneAllocationPanel } from '../AutoTuneAllocationPanel';

function report(): AllocationReport {
  const metrics = { initialNav: 1, finalNav: 1.08, totalReturnPct: 8, cagrPct: 5, sharpe: .7,
    maxDrawdownPct: -3, turnover: 1.4, tradeCount: 4, transactionCost: .0014, averageExposurePct: 60,
    fallbackPct: 25 } as AllocationMetrics;
  const portfolio = { cash: .4, shares: .006, nav: 1, stockValue: .6, currentExposure: .6,
    averageCost: 100, unrealizedPnlPct: 0, lastPrice: 100 };
  const state = { triggerBucket: 'STRONG_BUY', exposureBucket: .6, pnlBucket: 'FLAT', regime: 'UNKNOWN' };
  return {
    selectedPolicy: 'TUNED_FIXED', selectionBasis: 'validation_log_return', uniqueStatesVisited: 1,
    config: { policyMode: 'AUTO', simplicityTolerance: .01, q: { episodes: 500 }, state: {} },
    policies: ['TUNED_FIXED', 'Q_LEARNING'].map(name => ({ name, metrics: { train: metrics, validation: metrics, test: metrics },
      testEquity: { dates: [], values: [] }, executions: [], transitions: [{
        triggerDate: '2026-01-01', triggerDirection: 'BUY', triggerScore: 7,
        stateBefore: state, portfolioBefore: portfolio, requestedTargetExposure: .8,
        policyReason: 'LOW_SAMPLE_FALLBACK', executionReason: 'TRADE_COOLDOWN',
        executionDate: '2026-01-02', execution: { actualTargetExposure: .6, side: 'HOLD', tradeValue: 0, transactionCost: 0, after: portfolio },
        nextTriggerDate: '2026-01-05', navAtNextTrigger: 1.08, durationDays: 4, marketMove: .08,
        reward: .076961, qValue: null, visitCount: 3,
      }] })),
    qTable: [{ state, targetExposure: .8, qValue: .07, visitCount: 3, updateCount: 500,
      validAtBucket: true, recommendedAtBucket: true, recommendationReason: 'LOW_SAMPLE_FALLBACK' }],
  };
}

describe('AutoTuneAllocationPanel', () => {
  it('separates validation selection from test performance and requested from actual exposure', () => {
    render(<AutoTuneAllocationPanel report={report()} language="en" />);
    expect(screen.getByRole('heading', { name: 'Allocation policy · Tuned Fixed' })).toBeInTheDocument();
    expect(screen.getByText('Train return')).toBeInTheDocument();
    expect(screen.getByText('Validation return')).toBeInTheDocument();
    expect(screen.getByText('Test return')).toBeInTheDocument();
    expect(screen.getByText('80.0% → 60.0%')).toBeInTheDocument();
    expect(screen.getByText('0.076961')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Q-learning' }));
    expect(screen.getByRole('heading', { name: 'Test budget / exposure timeline · Q-learning' })).toBeInTheDocument();
    expect(screen.getByText('3 / 500')).toBeInTheDocument();
    fireEvent.change(screen.getByLabelText('Filter Q states'), { target: { value: 'STRONG_SELL' } });
    expect(screen.queryByText('3 / 500')).not.toBeInTheDocument();
  });

  it('renders the Chinese labels', () => {
    render(<AutoTuneAllocationPanel report={report()} language="zh" />);
    expect(screen.getByText('验证收益')).toBeInTheDocument();
    expect(screen.getByLabelText('筛选 Q 状态')).toBeInTheDocument();
  });

  it('shows joint fold selection and opportunity diagnostics separately from actual return', () => {
    const data = report();
    data.jointThresholds = { original: { buy: 6, sell: -6 }, selected: { buy: 5, sell: -6 },
      candidatesEvaluated: 9, thresholdStability: { buyStd: .5, sellStd: 0 },
      selectedValidation: { medianValidationReturn: .1, worstValidationReturn: -.02,
        medianValidationRegret: .03, positiveFolds: 2 }, folds: [{}, {}, {}], candidates: [] };
    data.policies[0].metrics.test.opportunityRegret = .07;
    data.policies[0].scoreObservations = [{ date: '2025-01-03', buyScore: 5, sellScore: 0,
      buyThreshold: 6, sellThreshold: -6, missedBuyRegret: .02, missedSellRegret: 0,
      opportunityReason: 'THRESHOLD_MISSED_TRIGGER', assetForwardReturn: .1 }];
    const apply = vi.fn();
    render(<AutoTuneAllocationPanel report={data} language="en" onApplyThresholds={apply} />);
    expect(screen.getByText('Joint threshold optimization')).toBeInTheDocument();
    expect(screen.getByLabelText('Opportunity Analysis')).toBeInTheDocument();
    expect(screen.getAllByText('7.00 log points').length).toBeGreaterThan(0);
    expect(screen.getByText(/Largest threshold miss/)).toHaveTextContent('2025-01-03');
    expect(screen.getByText(/not a realized loss/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Apply joint trigger thresholds' }));
    expect(apply).toHaveBeenCalledWith(5, -6);
  });
});


describe('economic reward safeguards', () => {
  it('shows missing benchmark explicitly and suppresses immature CAGR', () => {
    const data = report();
    data.benchmarkStatus = 'BENCHMARK_DATA_MISSING';
    data.policies.forEach(p => { p.metrics.test.actualCagr = null; });
    render(<AutoTuneAllocationPanel report={data} language="en" />);
    expect(screen.getByRole('status')).toHaveTextContent('unknown, not zero');
    expect(screen.getAllByText('Immature')).toHaveLength(2);
  });

  it('blocks applying a frozen selection after a test risk breach', () => {
    const data = report();
    data.testRiskStatus = 'BREACH';
    data.jointThresholds = { original: { buy: 6, sell: -6 }, selected: { buy: 5, sell: -6 },
      candidatesEvaluated: 9, thresholdStability: { buyStd: 0, sellStd: 0 },
      selectedValidation: null, folds: [], candidates: [] };
    const apply = vi.fn();
    render(<AutoTuneAllocationPanel report={data} language="en" onApplyThresholds={apply} />);
    expect(screen.getByRole('status')).toHaveTextContent('test did not select a replacement');
    expect(screen.queryByRole('button', { name: 'Apply joint trigger thresholds' })).not.toBeInTheDocument();
    expect(apply).not.toHaveBeenCalled();
  });

  it('renders no eligible candidate without suggesting an application', () => {
    const data = report();
    data.selectedPolicy = null;
    render(<AutoTuneAllocationPanel report={data} language="en" onApplyThresholds={vi.fn()} />);
    expect(screen.getByRole('heading', { name: /No selected candidate/ })).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Apply joint trigger thresholds' })).not.toBeInTheDocument();
  });
});
