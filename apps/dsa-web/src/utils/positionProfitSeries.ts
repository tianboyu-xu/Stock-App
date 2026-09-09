import type { KLineData } from '../api/stocks';
import { normalizeStockCode } from './stockCode';
import type { ClosedSale, CurrentPosition } from './currentPosition';

export type ProfitPoint = {
  date: string;
  profit: number;
  realized: number | null;
};

export type PositionHistoryResult = {
  key: string;
  data: KLineData[];
  failed: boolean;
};

function positionKey(code: string): string {
  return normalizeStockCode(code).toUpperCase();
}

export function buildProfitSeries(
  positions: CurrentPosition[],
  histories: PositionHistoryResult[],
  closedSales: ClosedSale[] = [],
): ProfitPoint[] {
  const historyByKey = new Map(histories.map((item) => [item.key, item.data]));
  const dateKeys = new Set<string>();
  for (const history of histories) {
    for (const bar of history.data) {
      dateKeys.add(bar.date.slice(0, 10));
    }
  }
  for (const sale of closedSales) {
    dateKeys.add(sale.sellDate.slice(0, 10));
  }

  const realizedByDate = new Map<string, number>();
  for (const sale of closedSales) {
    const key = sale.sellDate.slice(0, 10);
    realizedByDate.set(key, (realizedByDate.get(key) ?? 0) + sale.profit);
  }
  let cumulativeRealized = 0;
  let realizedStarted = false;

  return Array.from(dateKeys)
    .sort()
    .map((date) => {
      let profit = 0;
      let activeLots = 0;
      for (const position of positions) {
        if (date < position.purchaseDate) continue;
        const bar = historyByKey.get(positionKey(position.code))?.find((item) => item.date.slice(0, 10) === date);
        if (!bar) continue;
        activeLots += 1;
        profit += (bar.close - position.purchasePrice) * position.quantity;
      }
      const realizedToday = realizedByDate.get(date);
      if (realizedToday !== undefined) {
        realizedStarted = true;
        cumulativeRealized += realizedToday;
      }
      if (activeLots === 0 && !realizedStarted) return null;
      return {
        date,
        profit,
        realized: realizedStarted ? cumulativeRealized : null,
      };
    })
    .filter((item): item is ProfitPoint => item !== null);
}
