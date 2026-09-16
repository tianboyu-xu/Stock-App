import type { AutoTuneResponse, AutoTuneStrategyResult } from '../../api/stocks';
import { readStoredCurrentPositions } from '../../utils/currentPosition';
import { areStockCodesEquivalent } from '../../utils/stockCode';

export const STRATEGY_FAMILIES = [
  { key: 'baseline', en: 'Baseline', zh: '基础', members: ['A'] },
  { key: 'trend', en: 'Trend', zh: '趋势', members: ['B', 'C', 'D'] },
  { key: 'multifactor', en: 'Multi-factor', zh: '多因子', members: ['E', 'F'] },
  { key: 'budget', en: 'Adaptive Budget', zh: '自适应预算', members: [] },
  { key: 'aces', en: 'ACES', zh: 'ACES', members: [] },
  { key: 'macro_router', en: 'MATR · Macro Router', zh: 'MATR · 宏观路由', members: [] },
] as const;
export type StrategyFamily = typeof STRATEGY_FAMILIES[number]['key'];

export function strategyFamilyForKey(key: string | null | undefined): StrategyFamily | null {
  if (!key) return null;
  if (key === 'G') return 'aces';
  if (key === 'MATR') return 'macro_router';
  return STRATEGY_FAMILIES.find(family => family.key === key || (family.members as readonly string[]).includes(key))?.key ?? null;
}

export const STRATEGY_FAMILY_COLORS: Record<StrategyFamily, string> = {
  baseline: '#2f7de1',
  trend: '#22c55e',
  multifactor: '#f97316',
  budget: '#8b5cf6',
  aces: '#ec4899',
  macro_router: '#06b6d4',
};
// S&P 500 benchmark and CAGR target are reference lines, visually distinct
// from the solid strategy NAV lines.
export const BENCHMARK_LINE_COLOR = '#94a3b8';
export const TARGET_LINE_COLOR = '#eab308';
// Narrow plots show fewer date ticks so labels never collide; the shared
// middle axis reuses these exact ticks.
export const FULL_DATE_TICK_COUNT = 7;
export const NARROW_PLOT_WIDTH_PX = 520;
export const NARROW_DATE_TICK_COUNT = 3;
export function selectDateTickCount(targetWidth: number): number {
  return targetWidth < NARROW_PLOT_WIDTH_PX
    ? Math.min(NARROW_DATE_TICK_COUNT, FULL_DATE_TICK_COUNT)
    : FULL_DATE_TICK_COUNT;
}

// Single source of truth for trade-direction colors across the technical
// price chart (markers, legend) and the executed-trade details list:
// green = buy, red = sell.
export const TRADE_SIDE_COLORS = { BUY: '#1faa3a', SELL: '#d62728' } as const;
export interface TradeMark {
  date: string; side: string; price?: number; holding?: number; budget?: number;
  score?: number | null; reason: string; status: string; pnlPct?: number | null;
}

const formatPercent = (value?: number | null): string =>
  typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}%` : '—';

export const formatTriggerText = (mark: TradeMark): string =>
  `${formatPercent(mark.budget)}, ${mark.score ?? '—'} (${formatPercent(mark.holding)})`;

export const isVisibleTradeMark = (mark: TradeMark): boolean =>
  // `segment_end` is the simulator's mandatory end-of-window liquidation,
  // not a strategy-generated sell trigger. Keep it in accounting/diagnostics,
  // but do not present it as a signal marker or executed trigger detail.
  mark.status === 'executed' && mark.reason !== 'segment_end'
  && typeof mark.budget === 'number' && Number.isFinite(mark.budget) && mark.budget >= 10;

// Sort executed marks chronologically and attach each sell's realized
// return versus the latest prior buy price (fees excluded). Buys and sells
// without a preceding buy carry a null pnl.
export function withTradePnL(marks: TradeMark[]): TradeMark[] {
  const ordered = marks.slice().sort((a, b) => a.date < b.date ? -1 : a.date > b.date ? 1 : 0);
  let lastBuyPrice: number | null = null;
  return ordered.map(mark => {
    if (mark.side === 'BUY') {
      if (typeof mark.price === 'number' && Number.isFinite(mark.price)) lastBuyPrice = mark.price;
      return { ...mark, pnlPct: null };
    }
    if (mark.side === 'SELL') {
      const pnl = lastBuyPrice != null && lastBuyPrice > 0
        && typeof mark.price === 'number' && Number.isFinite(mark.price)
        ? (mark.price / lastBuyPrice - 1) * 100
        : null;
      return { ...mark, pnlPct: pnl };
    }
    return { ...mark, pnlPct: null };
  });
}

// Trade dots for the NAV chart: executed marks pinned to the selected
// strategy's NAV value. Marks whose date is outside the displayed rows, or
// whose NAV is missing there, are skipped.
export interface NavTradeDot {
  date: string; nav: number; side: string;
}

export function navTradeDots(
  rows: CombinedStrategyCurvePoint[],
  marks: TradeMark[],
  family: StrategyFamily,
): NavTradeDot[] {
  const navKey = `nav:${family}` as `nav:${string}`;
  const rowByDate = new Map(rows.map(row => [row.date, row]));
  const dots: NavTradeDot[] = [];
  for (const mark of marks) {
    const nav = rowByDate.get(mark.date)?.[navKey];
    if (typeof nav === 'number' && Number.isFinite(nav)) {
      dots.push({ date: mark.date, nav, side: mark.side });
    }
  }
  return dots;
}

// Family selection uses validation only; test returns never decide the representative.
export function familyStrategy(report: AutoTuneResponse, family: StrategyFamily): AutoTuneStrategyResult | undefined {
  const members: readonly string[] = STRATEGY_FAMILIES.find(f => f.key === family)!.members;
  return report.strategies.filter(s => members.includes(s.key)).sort((a, b) =>
    (b.validationScore ?? -Infinity) - (a.validationScore ?? -Infinity) || a.key.localeCompare(b.key))[0];
}

export function strategyPresentation(report: AutoTuneResponse, family: StrategyFamily) {
  const legacy = familyStrategy(report, family);
  const macro = family === 'macro_router' ? report.macroRouter : null;
  const allocation = family === 'aces' ? report.aces : family === 'budget' ? report.allocation : null;
  // Any remaining policy row with a usable curve (excluding the passive
  // BUY_HOLD reference) is preferable to showing no line at all, e.g. when
  // a cached report predates a policy name or selection fields are stale.
  const fallbackPolicy = allocation?.policies?.find(
    p => p.name !== 'BUY_HOLD' && (p.economicCurve?.length || p.testEquity?.dates?.length),
  );
  const policy = allocation?.policies?.find(p => p.name === allocation.selectedPolicy)
    ?? (family === 'aces' ? allocation?.policies?.find(p => p.name === report.aces?.inspectedPolicy) : undefined)
    // A fixed diagnostic fallback is explicit and independent of test results.
    ?? allocation?.policies?.find(p => p.name === 'TUNED_FIXED')
    ?? allocation?.policies?.find(p => p.name === 'FIXED')
    ?? fallbackPolicy;
  const decisions = macro?.testDecisions ?? legacy?.testDecisions;
  const marks: TradeMark[] = legacy || macro ? (decisions ?? []).map(d => ({
    date: d.date, side: d.side.toUpperCase(), price: d.executionPrice, holding: d.holdingPct,
    budget: d.status === 'skipped' ? 0 : d.tradeNavPct, score: d.score, reason: d.reason, status: d.status,
  })) : (policy?.executions ?? []).map(e => ({
    date: e.date, side: e.side.toUpperCase(), price: e.executionPrice, holding: e.holdingPct,
    budget: e.tradeNavPct, score: e.score, reason: e.reason, status: 'executed',
  }));
  if (policy) {
    for (const mark of marks) {
      const transition = policy.transitions.find(t => t.executionDate === mark.date && t.execution?.side === mark.side);
      if (mark.reason === 'signal' && transition) mark.reason += ` · ${transition.policyReason}`;
    }
    for (const t of policy.transitions) {
      if (!['BUY', 'SELL'].includes(t.triggerDirection) || (t.execution && t.execution.side !== 'HOLD')) continue;
      marks.push({ date: t.executionDate ?? t.triggerDate, side: t.triggerDirection,
        price: t.execution?.after.lastPrice ?? t.portfolioBefore.lastPrice,
        holding: (t.execution?.after.currentExposure ?? t.portfolioBefore.currentExposure) * 100,
        budget: 0, score: t.triggerScore, reason: `${t.executionReason} · ${t.policyReason}`, status: 'skipped' });
    }
  }
  const equity = macro?.testEquity ?? legacy?.testEquity ?? policy?.testEquity;
  const economic = policy?.economicCurve;
  // Use the exact-date, adjusted SPY curve. Never silently substitute the price-only index.
  const benchmark = macro
    ? new Map((macro.benchmarkEquity?.dates ?? []).map((date, i) => [date, 1 + macro.benchmarkEquity!.values[i] / 100]))
    : new Map((economic ?? report.allocation?.policies?.find(p => p.economicCurve?.length)?.economicCurve
      ?? report.aces?.policies?.find(p => p.economicCurve?.length)?.economicCurve ?? []).map(p => [p.date, p.benchmarkNav]));
  const target = macro?.targetCagr ?? policy?.metrics.test.targetCagr ?? report.allocation?.policies?.find(p => p.economicCurve?.length)?.metrics.test.targetCagr ?? .3;
  const origin = equity?.dates[0];
  const curve = economic ?? (equity?.dates ?? []).map((date, i) => ({
    date, strategyNav: 1 + equity!.values[i] / 100, benchmarkNav: benchmark.get(date) ?? null,
    requiredNav: (1 + target) ** ((Date.parse(date) - Date.parse(origin!)) / 86400000 / 365.25), cagrDeficit: 0,
  }));
  const dates = new Set(curve.map(p => p.date));
  const priceSeries = macro ? macro.testPrices : report.testPrices;
  const prices = (priceSeries?.dates ?? []).flatMap((date, i) => dates.has(date)
    ? [{ date, price: priceSeries!.values[i] }] : []);
  return { legacy, policy, marks, curve, prices, target,
    diagnostic: !!allocation && !allocation.selectedPolicy,
    unavailable: family === 'macro_router'
      ? !curve.length ? macro?.reason ?? 'MATR_NOT_RUN' : null
      : family === 'aces' ? (!policy ? report.aces?.error ?? 'ACES_NOT_RUN' : null) : !legacy && !policy ? 'NO_RESULT' : null,
    simulationMode: family === 'aces' ? report.aces?.simulationMode : undefined,
    simulationNotes: family === 'aces' ? report.aces?.warnings : undefined,
    readiness: family === 'aces' ? report.aces?.readiness : undefined,
    riskStatus: allocation?.testRiskStatus,
  };
}

/**
 * Older cached results may not contain all strategy families. Keep the
 * requested dropdown value intact, but choose the saved strategy curve for
 * rendering when that family is unavailable.
 */
export function strategyFamilyForView(
  report: AutoTuneResponse,
  requested: StrategyFamily,
  preferredKey?: string | null,
): StrategyFamily {
  // Router signals must never be replaced with another family's history.
  if (requested === 'macro_router') return requested;
  const hasCurve = (family: StrategyFamily) => {
    const view = strategyPresentation(report, family);
    return view.unavailable == null && view.curve.length > 0;
  };
  if (hasCurve(requested)) return requested;
  const preferredFamily = strategyFamilyForKey(preferredKey);
  if (preferredFamily && hasCurve(preferredFamily)) return preferredFamily;
  return STRATEGY_FAMILIES.find(family => hasCurve(family.key))?.key ?? requested;
}

export interface CombinedStrategyCurvePoint {
  date: string;
  benchmarkNav: number | null;
  requiredNav: number | null;
  [strategyNav: `nav:${string}`]: number | string | null;
}

// Different engines can have different evaluation periods and NAV origins.
// Compare only their overlapping history, starting on an actual shared sample,
// and rebase every line there. Internal missing samples stay missing.
export function combinedStrategyCurves(report: AutoTuneResponse, families: readonly StrategyFamily[]) {
  const views = families.map(family => ({ family, view: strategyPresentation(report, family) }));
  const validNav = (value: number | null | undefined): value is number =>
    typeof value === 'number' && Number.isFinite(value) && value > 0;
  const available = views.map(({ family, view }) => ({ family,
    points: new Map(view.curve.filter(point => Number.isFinite(point.strategyNav) && point.strategyNav >= 0)
      .map(point => [point.date, point])),
  })).filter(({ points }) => points.size > 0);
  const target = views.find(v => v.view.target != null)?.view.target ?? .3;
  const empty = { views, rows: [] as CombinedStrategyCurvePoint[], target,
    hasBenchmark: false, anchorDate: null as string | null, endDate: null as string | null };
  if (!available.length) return empty;
  const starts = available.map(({ points }) => [...points.keys()].sort()[0]);
  const ends = available.map(({ points }) => [...points.keys()].sort().at(-1)!);
  const firstDate = starts.sort().at(-1)!;
  const lastDate = ends.sort()[0];
  const dates = [...new Set(available.flatMap(({ points }) => [...points.keys()]))]
    .filter(date => date >= firstDate && date <= lastDate).sort();
  const anchorDate = dates.find(date => available.every(({ points }) => validNav(points.get(date)?.strategyNav)));
  if (!anchorDate) return empty;
  const comparisonDates = dates.filter(date => date >= anchorDate);
  // Use one adjusted SPY source across the interval, never stitch differently
  // based benchmark curves together or fill missing dates with another price.
  const benchmarkSource = available.filter(({ points }) => validNav(points.get(anchorDate)?.benchmarkNav))
    .sort((a, b) => comparisonDates.filter(date => validNav(b.points.get(date)?.benchmarkNav)).length
      - comparisonDates.filter(date => validNav(a.points.get(date)?.benchmarkNav)).length)[0];
  const benchmarkAnchor = benchmarkSource?.points.get(anchorDate)?.benchmarkNav;
  const rows = comparisonDates.map(date => {
    const benchmark = benchmarkSource?.points.get(date)?.benchmarkNav;
    const row: CombinedStrategyCurvePoint = { date,
      benchmarkNav: validNav(benchmark) && validNav(benchmarkAnchor) ? benchmark / benchmarkAnchor : null,
      requiredNav: (1 + target) ** ((Date.parse(date) - Date.parse(anchorDate)) / 86400000 / 365.25),
    };
    for (const { family, points } of available) {
      const point = points.get(date);
      row[`nav:${family}`] = point ? point.strategyNav / points.get(anchorDate)!.strategyNav : null;
    }
    return row;
  });
  return { views, rows, target, anchorDate, endDate: rows.at(-1)?.date ?? null,
    hasBenchmark: rows.some(row => row.benchmarkNav != null) };
}

export interface HoldingAnchor {
  code: string;
  purchaseDate: string;
  purchasePrice: number;
  quantity: number;
}

function toDayMs(value: string): number {
  const trimmed = value.trim();
  const ms = /^\d{4}-\d{2}-\d{2}$/.test(trimmed) ? Date.parse(`${trimmed}T00:00:00Z`) : Date.parse(trimmed);
  return Number.isFinite(ms) ? ms : NaN;
}

// All Current-position lots for a stock (homepage lots, matched with the
// same code equivalence used by the position table), earliest purchase
// first. Used to mark every bought point on the price chart line.
export function findHoldingLots(stockCode: string): HoldingAnchor[] {
  if (!stockCode.trim()) return [];
  return readStoredCurrentPositions()
    .filter(position => areStockCodesEquivalent(position.code, stockCode)
      && Number.isFinite(toDayMs(position.purchaseDate)))
    .slice()
    .sort((a, b) => toDayMs(a.purchaseDate) - toDayMs(b.purchaseDate))
    .map(lot => ({
      code: lot.code,
      purchaseDate: lot.purchaseDate,
      purchasePrice: lot.purchasePrice,
      quantity: lot.quantity,
    }));
}

// Detect whether the selected stock is held in Current positions (homepage
// lots, matched with the same code equivalence used by the position table).
// With several lots, the earliest purchase wins so the comparison window is
// the longest available one.
export function findHoldingAnchor(stockCode: string): HoldingAnchor | null {
  return findHoldingLots(stockCode)[0] ?? null;
}

export interface AnchoredCurveResult {
  rows: CombinedStrategyCurvePoint[];
  anchorDate: string | null;
}

// Slice rows from the first date on/after purchaseDate and rebase every
// numeric series to its own anchor value, so all NAV lines restart from 1.0
// at the holding's buy date (the cost basis). Series with no usable anchor
// value become null instead of inventing a start point.
export function rebaseRowsFromPurchaseDate(
  rows: CombinedStrategyCurvePoint[],
  purchaseDate: string,
): AnchoredCurveResult {
  const anchorMs = toDayMs(purchaseDate);
  if (!Number.isFinite(anchorMs)) return { rows, anchorDate: null };
  const anchorIndex = rows.findIndex(row => Number.isFinite(toDayMs(row.date)) && toDayMs(row.date) >= anchorMs);
  if (anchorIndex < 0) return { rows: [], anchorDate: null };
  const sliced = rows.slice(anchorIndex);
  const keys = new Set<string>();
  for (const row of sliced) {
    for (const key of Object.keys(row)) {
      if (key !== 'date') keys.add(key);
    }
  }
  const divisors = new Map<string, number>();
  for (const key of keys) {
    for (const row of sliced) {
      const value = (row as unknown as Record<string, number | string | null>)[key];
      if (typeof value === 'number' && Number.isFinite(value) && value !== 0) {
        divisors.set(key, value);
        break;
      }
    }
  }
  const rebased = sliced.map(row => {
    const next: CombinedStrategyCurvePoint = { ...row };
    const record = next as unknown as Record<string, number | string | null>;
    for (const key of keys) {
      const divisor = divisors.get(key);
      const value = record[key];
      record[key] = divisor != null && typeof value === 'number' && Number.isFinite(value)
        ? value / divisor
        : null;
    }
    return next;
  });
  return { rows: rebased, anchorDate: sliced[0].date };
}
