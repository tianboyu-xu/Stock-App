import type { IndicatorThresholds } from '../api/stocks';

const THRESHOLD_STORAGE_PREFIX = 'dsa.indicator.thresholds.';

// Defaults mirror src/services/indicator_service.py DEFAULT_THRESHOLDS.
export const DEFAULT_INDICATOR_THRESHOLDS: IndicatorThresholds = {
  bolConstant: 0.1,
  macdBuy: 0.7,
  macdSell: 0.99,
  kdjBuy: 40,
  kdjSell: 70,
  rsiBuy: 10,
  rsiSell: 70,
  compositeBuyThreshold: 6,
  compositeSellThreshold: 6,
  macdLookback: 120,
  macdLowPercentile: 15,
  macdHighPercentile: 85,
  rsiLow: 15,
  rsiHigh: 85,
  kdjLow: 40,
  kdjHigh: 70,
  trendPeriod: 200,
  bollBuyLevel: 0.1,
  bollSellLevel: 0.9,
  bollWeight: 0,
  cciBuyLevel: -100,
  cciSellLevel: 100,
  cciWeight: 0,
  adxMinLevel: 20,
  dmiWeight: 0,
  mfiBuyLevel: 20,
  mfiSellLevel: 80,
  mfiWeight: 0,
  volumeConfirmLevel: 1.5,
  volumeWeight: 0,
  range52HighLevel: 0.95,
  range52LowLevel: 1.05,
  range52Weight: 0,
};

// Fill any missing keys with defaults so older stored/backend threshold
// payloads (7 keys) keep working with the composite thresholds.
export function normalizeIndicatorThresholds(
  partial: Partial<IndicatorThresholds> | null | undefined,
): IndicatorThresholds {
  const merged: IndicatorThresholds = { ...DEFAULT_INDICATOR_THRESHOLDS };
  if (partial) {
    for (const key of Object.keys(DEFAULT_INDICATOR_THRESHOLDS) as Array<keyof IndicatorThresholds>) {
      const value = partial[key];
      if (typeof value === 'number' && Number.isFinite(value)) {
        merged[key] = value;
      }
    }
  }
  return merged;
}

export function indicatorThresholdStorageKey(stockCode: string): string {
  return `${THRESHOLD_STORAGE_PREFIX}${stockCode.trim().toUpperCase()}`;
}

export function readStoredIndicatorThresholds(stockCode: string): IndicatorThresholds | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    const rawValue = window.localStorage.getItem(indicatorThresholdStorageKey(stockCode));
    if (!rawValue) {
      return null;
    }
    const parsed = JSON.parse(rawValue) as Partial<IndicatorThresholds>;
    const requiredKeys: Array<keyof IndicatorThresholds> = [
      'bolConstant', 'macdBuy', 'macdSell', 'kdjBuy', 'kdjSell', 'rsiBuy', 'rsiSell',
    ];
    for (const key of requiredKeys) {
      const value = parsed[key];
      if (typeof value !== 'number' || !Number.isFinite(value)) {
        return null;
      }
    }
    return normalizeIndicatorThresholds(parsed);
  } catch {
    return null;
  }
}

export function writeStoredIndicatorThresholds(stockCode: string, thresholds: IndicatorThresholds): void {
  if (typeof window === 'undefined') {
    return;
  }
  try {
    window.localStorage.setItem(indicatorThresholdStorageKey(stockCode), JSON.stringify(thresholds));
  } catch {
    // Local storage is best-effort; keep the in-memory values working.
  }
}

export const INDICATOR_THRESHOLDS_CHANGED_EVENT = 'dsa-indicator-thresholds-changed';

export interface IndicatorThresholdsChangedDetail {
  stockCode: string;
}

// Notify the app that a stock's indicator thresholds were updated (manual
// edit, auto-tune apply, or restore defaults) so live consumers such as the
// home Summary board can refetch with the fresh thresholds.
export function notifyIndicatorThresholdsChanged(stockCode: string): void {
  if (typeof window === 'undefined') {
    return;
  }
  window.dispatchEvent(
    new CustomEvent<IndicatorThresholdsChangedDetail>(INDICATOR_THRESHOLDS_CHANGED_EVENT, {
      detail: { stockCode },
    }),
  );
}
