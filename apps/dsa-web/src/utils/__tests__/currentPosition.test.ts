import { describe, expect, it } from 'vitest';
import {
  calculateCurrentPositionMetrics,
  LONG_TERM_CAPITAL_GAINS_TAX_PCT,
  SHORT_TERM_CAPITAL_GAINS_TAX_PCT,
} from '../currentPosition';

const position = {
  purchaseDate: '2025-09-04',
  purchasePrice: 100,
  quantity: 2,
};

describe('current position calculations', () => {
  it('calculates total gain/loss and long-term after-tax CAGR', () => {
    const metrics = calculateCurrentPositionMetrics(position, 120, '2026-09-04');

    expect(metrics.currentValue).toBe(240);
    expect(metrics.gainLossAmount).toBe(40);
    expect(metrics.gainLossPct).toBeCloseTo(20, 8);
    expect(metrics.holdingDays).toBe(365);
    expect(metrics.taxRatePct).toBe(LONG_TERM_CAPITAL_GAINS_TAX_PCT);
    expect(metrics.afterTaxCagrPct).toBeCloseTo(17, 8);
  });

  it('uses the short-term tax rate before one year and does not tax losses', () => {
    const profitable = calculateCurrentPositionMetrics(
      { ...position, purchaseDate: '2026-06-04' },
      120,
      '2026-09-04',
    );
    const loss = calculateCurrentPositionMetrics(
      { ...position, purchaseDate: '2026-06-04' },
      80,
      '2026-09-04',
    );

    expect(profitable.taxRatePct).toBe(SHORT_TERM_CAPITAL_GAINS_TAX_PCT);
    expect(profitable.afterTaxCagrPct).toBeCloseTo(
      (Math.pow(1.13, 365 / 92) - 1) * 100,
      8,
    );
    expect(loss.gainLossAmount).toBe(-40);
    expect(loss.gainLossPct).toBeCloseTo(-20, 8);
    expect(loss.afterTaxCagrPct).toBeCloseTo(
      (Math.pow(0.8, 365 / 92) - 1) * 100,
      8,
    );
  });

  it('uses a zero tax rate for 401K and HSA CAGR calculations', () => {
    const retirement = calculateCurrentPositionMetrics(
      { ...position, account: '401K' },
      120,
      '2026-09-04',
    );
    const healthSavings = calculateCurrentPositionMetrics(
      { ...position, account: 'HSA' },
      120,
      '2026-09-04',
    );

    expect(retirement.taxRatePct).toBe(0);
    expect(retirement.afterTaxCagrPct).toBeCloseTo(20, 8);
    expect(healthSavings.taxRatePct).toBe(0);
    expect(healthSavings.afterTaxCagrPct).toBeCloseTo(20, 8);
  });

  it('returns unavailable metrics when the current price is missing', () => {
    const metrics = calculateCurrentPositionMetrics(position, null, '2026-09-04');

    expect(metrics.currentValue).toBeNull();
    expect(metrics.gainLossAmount).toBeNull();
    expect(metrics.gainLossPct).toBeNull();
    expect(metrics.afterTaxCagrPct).toBeNull();
  });
});
