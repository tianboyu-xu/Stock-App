export const DEFAULT_ACES_FIELDS = { budget: 10000, cagr: 30, exposure: 100, drawdown: 25,
  volatility: true, gap: true, opportunity: true, mode: 'COMPARE', buy: '6,7,8', sell: '-6,-7,-8', folds: 3, advanced: '{}' };

export function buildACESConfig(next: typeof DEFAULT_ACES_FIELDS, zh: boolean): Record<string, unknown> {
  const buys = next.buy.split(',').map(Number), sells = next.sell.split(',').map(Number);
  if (!(next.budget > 0 && next.budget <= 1e12) || ![next.cagr, next.exposure, next.drawdown].every(v => Number.isFinite(v) && v >= 0 && v <= 100)
    || !Number.isInteger(next.folds) || next.folds < 2 || next.folds > 5
    || ![buys, sells].every(a => a.length >= 1 && a.length <= 7 && new Set(a).size === a.length)
    || !buys.every(v => Number.isInteger(v) && v > 0 && v <= 30) || !sells.every(v => Number.isInteger(v) && v < 0 && v >= -30))
    throw new Error(zh ? '请检查预算、阈值及风险范围。' : 'Check budget, thresholds and risk ranges.');
  const overrides = JSON.parse(next.advanced) as Record<string, unknown>;
  if (!overrides || Array.isArray(overrides) || typeof overrides !== 'object') throw new Error('Advanced settings must be an object.');
  const allocation = (overrides.allocation ?? {}) as Record<string, unknown>;
  const risk = (overrides.risk ?? {}) as Record<string, unknown>;
  const execution = (overrides.execution ?? {}) as Record<string, unknown>;
  return { ...overrides, version: 1, enabled: true, initial_budget: next.budget,
    policy_mode: next.mode, buy_thresholds: buys, sell_thresholds: sells,
    allocation: { ...allocation, validation_folds: next.folds, lambda_opportunity: next.opportunity ? .25 : 0,
      economic: { ...(allocation.economic as object ?? {}), target_cagr: next.cagr / 100, allowed_max_drawdown: next.drawdown / 100 } },
    risk: { ...risk, maximum_exposure: next.exposure / 100, volatility_control: next.volatility },
    execution: { ...execution, max_entry_gap_atr: next.gap ? 1 : null } };
}

export function defaultACESConfig(): Record<string, unknown> {
  return buildACESConfig(DEFAULT_ACES_FIELDS, false);
}
