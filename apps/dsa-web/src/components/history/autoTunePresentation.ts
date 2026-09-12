import type { AutoTuneResponse, AutoTuneStrategyResult } from '../../api/stocks';

export const STRATEGY_FAMILIES = [
  { key: 'baseline', en: 'Baseline', zh: '基础', members: ['A'] },
  { key: 'trend', en: 'Trend', zh: '趋势', members: ['B', 'C', 'D'] },
  { key: 'multifactor', en: 'Multi-factor', zh: '多因子', members: ['E', 'F'] },
  { key: 'budget', en: 'Adaptive Budget', zh: '自适应预算', members: [] },
  { key: 'aces', en: 'ACES', zh: 'ACES', members: [] },
] as const;
export type StrategyFamily = typeof STRATEGY_FAMILIES[number]['key'];

export function strategyFamilyForKey(key: string | null | undefined): StrategyFamily | null {
  if (!key) return null;
  if (key === 'G') return 'aces';
  return STRATEGY_FAMILIES.find(family => family.key === key || (family.members as readonly string[]).includes(key))?.key ?? null;
}

export const STRATEGY_FAMILY_COLORS: Record<StrategyFamily, string> = {
  baseline: '#38bdf8',
  trend: '#34d399',
  multifactor: '#fb923c',
  budget: '#2dd4bf',
  aces: '#f472b6',
};
export interface TradeMark {
  date: string; side: string; price?: number; holding?: number; budget?: number;
  score?: number | null; reason: string; status: string;
}

const formatPercent = (value?: number | null): string =>
  typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(1)}%` : '—';

export const formatTriggerText = (mark: TradeMark): string =>
  `${formatPercent(mark.budget)}, ${mark.score ?? '—'} (${formatPercent(mark.holding)})`;

export const isVisibleTradeMark = (mark: TradeMark): boolean =>
  mark.status === 'executed' && typeof mark.budget === 'number' && Number.isFinite(mark.budget) && mark.budget >= 10;

// Family selection uses validation only; test returns never decide the representative.
export function familyStrategy(report: AutoTuneResponse, family: StrategyFamily): AutoTuneStrategyResult | undefined {
  const members: readonly string[] = STRATEGY_FAMILIES.find(f => f.key === family)!.members;
  return report.strategies.filter(s => members.includes(s.key)).sort((a, b) =>
    (b.validationScore ?? -Infinity) - (a.validationScore ?? -Infinity) || a.key.localeCompare(b.key))[0];
}

export function strategyPresentation(report: AutoTuneResponse, family: StrategyFamily) {
  const legacy = familyStrategy(report, family);
  const allocation = family === 'aces' ? report.aces : family === 'budget' ? report.allocation : null;
  const policy = allocation?.policies?.find(p => p.name === allocation.selectedPolicy)
    ?? (family === 'aces' ? allocation?.policies?.find(p => p.name === report.aces?.inspectedPolicy) : undefined)
    // A fixed diagnostic fallback is explicit and independent of test results.
    ?? allocation?.policies?.find(p => p.name === 'TUNED_FIXED')
    ?? allocation?.policies?.find(p => p.name === 'FIXED');
  const marks: TradeMark[] = legacy ? (legacy.testDecisions ?? []).map(d => ({
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
  const equity = legacy?.testEquity ?? policy?.testEquity;
  const economic = policy?.economicCurve;
  // Use the exact-date, adjusted SPY curve. Never silently substitute the price-only index.
  const benchmark = new Map((economic ?? report.allocation?.policies?.find(p => p.economicCurve?.length)?.economicCurve
    ?? report.aces?.policies?.find(p => p.economicCurve?.length)?.economicCurve ?? []).map(p => [p.date, p.benchmarkNav]));
  const target = policy?.metrics.test.targetCagr ?? report.allocation?.policies?.find(p => p.economicCurve?.length)?.metrics.test.targetCagr ?? .3;
  const origin = equity?.dates[0];
  const curve = economic ?? (equity?.dates ?? []).map((date, i) => ({
    date, strategyNav: 1 + equity!.values[i] / 100, benchmarkNav: benchmark.get(date) ?? null,
    requiredNav: (1 + target) ** ((Date.parse(date) - Date.parse(origin!)) / 86400000 / 365.25), cagrDeficit: 0,
  }));
  const dates = new Set(curve.map(p => p.date));
  const prices = (report.testPrices?.dates ?? []).flatMap((date, i) => dates.has(date)
    ? [{ date, price: report.testPrices!.values[i] }] : []);
  return { legacy, policy, marks, curve, prices, target,
    diagnostic: !!allocation && !allocation.selectedPolicy,
    unavailable: family === 'aces' ? (!policy ? report.aces?.error ?? 'ACES_NOT_RUN' : null) : !legacy && !policy ? 'NO_RESULT' : null,
    simulationMode: family === 'aces' ? report.aces?.simulationMode : undefined,
    simulationNotes: family === 'aces' ? report.aces?.warnings : undefined,
    readiness: family === 'aces' ? report.aces?.readiness : undefined,
    riskStatus: allocation?.testRiskStatus,
  };
}

/**
 * Older cached results may not contain all five strategy families. Keep the
 * requested dropdown value intact, but choose the saved strategy curve for
 * rendering when that family is unavailable.
 */
export function strategyFamilyForView(
  report: AutoTuneResponse,
  requested: StrategyFamily,
  preferredKey?: string | null,
): StrategyFamily {
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

// Merge every visible family's NAV curve onto one shared date axis so the
// combined chart can draw all strategy lines at once. Benchmark and growth
// target come from the first family that provides them.
export function combinedStrategyCurves(report: AutoTuneResponse, families: readonly StrategyFamily[]) {
  const views = families.map(family => ({ family, view: strategyPresentation(report, family) }));
  const dates: string[] = [];
  const seen = new Set<string>();
  for (const { view } of views) for (const p of view.curve) {
    if (!seen.has(p.date)) { seen.add(p.date); dates.push(p.date); }
  }
  dates.sort();
  const byDate = new Map<string, CombinedStrategyCurvePoint>();
  for (const date of dates) byDate.set(date, { date, benchmarkNav: null, requiredNav: null });
  for (const { family, view } of views) {
    for (const p of view.curve) {
      const row = byDate.get(p.date)!;
      row[`nav:${family}`] = p.strategyNav;
      if (row.benchmarkNav == null && p.benchmarkNav != null) row.benchmarkNav = p.benchmarkNav;
      if (row.requiredNav == null && p.requiredNav != null) row.requiredNav = p.requiredNav;
    }
  }
  const target = views.find(v => v.view.target != null)?.view.target ?? .3;
  return { views, rows: [...byDate.values()], target,
    hasBenchmark: [...byDate.values()].some(r => r.benchmarkNav != null) };
}
