export type TriggerGroupKey =
  | 'macd'
  | 'obv'
  | 'kdj'
  | 'rsi'
  | 'boll'
  | 'cci'
  | 'dmi'
  | 'mfi'
  | 'compositeBuy'
  | 'compositeSell';

const TRIGGER_STORAGE_PREFIX = 'dsa.indicator.triggers.';

// Composite signals are on by default; single-indicator groups start off so
// the price chart stays readable until the user opts in.
export const DEFAULT_VISIBLE_TRIGGERS: Record<TriggerGroupKey, boolean> = {
  macd: false,
  obv: false,
  kdj: false,
  rsi: false,
  boll: false,
  cci: false,
  dmi: false,
  mfi: false,
  compositeBuy: true,
  compositeSell: true,
};

// Unknown or non-boolean entries fall back to the defaults so older or
// hand-edited payloads can never break the toggle row.
export function normalizeVisibleTriggers(value: unknown): Record<TriggerGroupKey, boolean> {
  const merged: Record<TriggerGroupKey, boolean> = { ...DEFAULT_VISIBLE_TRIGGERS };
  if (value && typeof value === 'object') {
    for (const key of Object.keys(DEFAULT_VISIBLE_TRIGGERS) as Array<TriggerGroupKey>) {
      if (typeof (value as Record<string, unknown>)[key] === 'boolean') {
        merged[key] = (value as Record<TriggerGroupKey, boolean>)[key];
      }
    }
  }
  return merged;
}

export function visibleTriggersStorageKey(stockCode: string): string {
  return `${TRIGGER_STORAGE_PREFIX}${stockCode.trim().toUpperCase()}`;
}

export function readStoredVisibleTriggers(stockCode: string): Record<TriggerGroupKey, boolean> {
  if (typeof window === 'undefined') return { ...DEFAULT_VISIBLE_TRIGGERS };
  try {
    const rawValue = window.localStorage.getItem(visibleTriggersStorageKey(stockCode));
    if (!rawValue) return { ...DEFAULT_VISIBLE_TRIGGERS };
    return normalizeVisibleTriggers(JSON.parse(rawValue));
  } catch {
    return { ...DEFAULT_VISIBLE_TRIGGERS };
  }
}

export function writeStoredVisibleTriggers(stockCode: string, triggers: Record<TriggerGroupKey, boolean>): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(visibleTriggersStorageKey(stockCode), JSON.stringify(triggers));
  } catch {
    // Local storage is best-effort; the toggles remain usable in memory.
  }
}
