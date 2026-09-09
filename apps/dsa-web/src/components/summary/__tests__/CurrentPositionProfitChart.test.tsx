import { describe, expect, it } from 'vitest';
import { buildProfitSeries } from '../../../utils/positionProfitSeries';
import type { ClosedSale, CurrentPosition } from '../../../utils/currentPosition';

const position: CurrentPosition = {
  id: 'p1',
  code: 'AAPL',
  name: 'AAPL',
  purchaseDate: '2026-08-01',
  purchasePrice: 100,
  quantity: 2,
  account: 'Robinhood',
};

const histories = [
  {
    key: 'AAPL',
    failed: false,
    data: [
      { date: '2026-08-10', open: 100, high: 101, low: 99, close: 110 },
      { date: '2026-08-11', open: 110, high: 112, low: 109, close: 120 },
      { date: '2026-08-12', open: 120, high: 121, low: 119, close: 115 },
    ],
  },
];

function makeSale(overrides: Partial<ClosedSale> = {}): ClosedSale {
  return {
    id: 's1',
    positionId: 'p1',
    code: 'AAPL',
    name: 'AAPL',
    purchaseDate: '2026-08-01',
    purchasePrice: 100,
    quantity: 2,
    sellDate: '2026-08-11',
    sellPrice: 120,
    profit: 40,
    account: 'Robinhood',
    ...overrides,
  };
}

describe('buildProfitSeries realized axis', () => {
  it('keeps unrealized series unchanged when there are no sales', () => {
    const series = buildProfitSeries([position], histories);

    expect(series).toEqual([
      { date: '2026-08-10', profit: 20, realized: null },
      { date: '2026-08-11', profit: 40, realized: null },
      { date: '2026-08-12', profit: 30, realized: null },
    ]);
  });

  it('adds a cumulative realized series starting on the sell date', () => {
    const series = buildProfitSeries([position], histories, [
      makeSale({ id: 's1', sellDate: '2026-08-11', profit: 40 }),
      makeSale({ id: 's2', sellDate: '2026-08-12', profit: -10 }),
    ]);

    expect(series).toEqual([
      { date: '2026-08-10', profit: 20, realized: null },
      { date: '2026-08-11', profit: 40, realized: 40 },
      { date: '2026-08-12', profit: 30, realized: 30 },
    ]);
  });

  it('accumulates multiple sales on the same day', () => {
    const series = buildProfitSeries([position], histories, [
      makeSale({ id: 's1', sellDate: '2026-08-11', profit: 40 }),
      makeSale({ id: 's2', sellDate: '2026-08-11', profit: 10 }),
    ]);

    expect(series.find((point) => point.date === '2026-08-11')?.realized).toBe(50);
  });

  it('renders realized-only points after all positions are sold', () => {
    const series = buildProfitSeries([], [], [makeSale()]);

    expect(series).toEqual([{ date: '2026-08-11', profit: 0, realized: 40 }]);
  });
});
