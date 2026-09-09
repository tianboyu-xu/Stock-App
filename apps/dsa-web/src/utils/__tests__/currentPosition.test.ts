import { describe, expect, it } from 'vitest';
import {
  calculateClosedSaleProfit,
  calculateCurrentPositionMetrics,
  LONG_TERM_CAPITAL_GAINS_TAX_PCT,
  reconcileSaleDelete,
  reconcileSaleEdit,
  SHORT_TERM_CAPITAL_GAINS_TAX_PCT,
  type ClosedSale,
  type CurrentPosition,
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

describe('closed sale profit', () => {
  it('calculates profit from sell price, purchase price, and quantity', () => {
    expect(calculateClosedSaleProfit(100, 120, 2)).toBe(40);
    expect(calculateClosedSaleProfit(100, 80, 2)).toBe(-40);
  });

  it('returns null for invalid inputs', () => {
    expect(calculateClosedSaleProfit(0, 120, 2)).toBeNull();
    expect(calculateClosedSaleProfit(100, -5, 2)).toBeNull();
    expect(calculateClosedSaleProfit(100, 120, 0)).toBeNull();
    expect(calculateClosedSaleProfit(Number.NaN, 120, 2)).toBeNull();
  });
});

const closedSale: ClosedSale = {
  id: 's1',
  positionId: 'p1',
  code: 'AAPL',
  name: 'AAPL',
  purchaseDate: '2025-09-04',
  purchasePrice: 100,
  quantity: 2,
  sellDate: '2026-09-04',
  sellPrice: 120,
  profit: 40,
  account: 'Robinhood',
};

describe('trade history reconciliation', () => {
  it('recalculates profit when a sale is edited', () => {
    const reconciled = reconcileSaleEdit(closedSale, {
      sellDate: '2026-09-05',
      sellPrice: 130,
      quantity: 1,
    });

    expect(reconciled?.sale).toMatchObject({
      id: 's1',
      sellDate: '2026-09-05',
      sellPrice: 130,
      quantity: 1,
      profit: 30,
    });
    expect(reconciled?.profit).toBe(30);
  });

  it('rejects edits with a sell date before the purchase date or invalid numbers', () => {
    expect(reconcileSaleEdit(closedSale, {
      sellDate: '2025-01-01',
      sellPrice: 130,
      quantity: 1,
    })).toBeNull();
    expect(reconcileSaleEdit(closedSale, {
      sellDate: '2026-09-05',
      sellPrice: 0,
      quantity: 1,
    })).toBeNull();
    expect(reconcileSaleEdit(closedSale, {
      sellDate: '2026-09-05',
      sellPrice: 130,
      quantity: 0,
    })).toBeNull();
  });

  it('merges the sold quantity back into the original lot on revert', () => {
    const lot: CurrentPosition = {
      id: 'p1',
      code: 'AAPL',
      name: 'AAPL',
      purchaseDate: '2025-09-04',
      purchasePrice: 100,
      quantity: 1,
      account: 'Robinhood',
    };
    const reconciled = reconcileSaleDelete(closedSale, [closedSale], [lot]);

    expect(reconciled.sales).toEqual([]);
    expect(reconciled.positions).toEqual([{ ...lot, quantity: 3 }]);
  });

  it('restores a removed lot as a new position when the original lot is gone', () => {
    const reconciled = reconcileSaleDelete(closedSale, [closedSale], []);

    expect(reconciled.sales).toEqual([]);
    expect(reconciled.positions).toHaveLength(1);
    expect(reconciled.positions[0]).toMatchObject({
      id: 'p1',
      code: 'AAPL',
      purchasePrice: 100,
      quantity: 2,
    });
  });
});
