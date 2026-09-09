import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { AutoTuneBudgetLedger } from '../AutoTuneBudgetLedger';

describe('AutoTuneBudgetLedger', () => {
  it('distinguishes proposed allocation from an unfunded, skipped buy in both languages', () => {
    const decisions = [{
      signalDate: '2026-01-05', date: '2026-01-05', side: 'buy' as const,
      status: 'skipped' as const, reason: 'no_cash', suggestedBudgetPct: 60,
      executedBudgetPct: 0, cashAfterPct: 0,
    }];
    const { rerender } = render(<AutoTuneBudgetLedger decisions={decisions} language="en" />);
    expect(screen.getByText('Skipped · No cash available')).toBeInTheDocument();
    expect(screen.getByText('60.00%')).toBeInTheDocument();
    expect(screen.getAllByText('0.00%')).toHaveLength(2);
    rerender(<AutoTuneBudgetLedger decisions={decisions} language="zh" />);
    expect(screen.getByText('跳过 · 预算已用完')).toBeInTheDocument();
  });
});
