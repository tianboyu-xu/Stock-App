import type React from 'react';
import { AutoTuneBudgetLedger } from './AutoTuneBudgetLedger';
import { AutoTuneAllocationPanel } from './AutoTuneAllocationPanel';
import { ACESResults, ACESSetup } from './ACESPanel';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AUTO_TUNE_METHODOLOGY_VERSION, stocksApi, type AutoTuneBenchmark, type AutoTuneResponse, type AutoTuneStrategyResult, type AutoTuneTestConfidence, type CompositeBreakdown, type FineTuneSweepPosition, type IndicatorThresholds, type StockIndicatorsResponse } from '../../api/stocks';
import type { UiTextKey } from '../../i18n/uiText';
import {
  DEFAULT_INDICATOR_THRESHOLDS,
  normalizeIndicatorThresholds,
  notifyIndicatorThresholdsChanged,
  readStoredIndicatorThresholds,
  writeStoredIndicatorThresholds,
} from '../../utils/indicatorThresholds';
import { Button, Card } from '../common';
import { DashboardStateBlock } from '../dashboard';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

const DAY_OPTIONS = [7, 14, 30, 60, 90, 180, 365, 730, 1095, 1460, 1825];
const AUTO_TUNE_TEST_YEAR_OPTIONS = [1, 2, 3, 4, 5];
// 双端滑杆使用 0~1000 的千分比刻度，两端最小间隔约 2%，避免贴合成一个点。
const TRAIN_RANGE_SCALE = 1000;
const TRAIN_RANGE_MIN_GAP = 20;

const DAY_MS = 24 * 60 * 60 * 1000;
const parseDayMs = (value: string) => new Date(`${value}T00:00:00Z`).getTime();
const formatDayMs = (ms: number) => new Date(ms).toISOString().slice(0, 10);

// Auto Tune strategy / benchmark line colors for the cumulative-profit plot.
const AUTO_TUNE_STRATEGY_COLORS: Record<string, string> = {
  A: '#2f7de1',
  B: '#22c55e',
  C: '#f59e0b',
  D: '#a78bfa',
  E: '#f97316',
  F: '#06b6d4',
};
const AUTO_TUNE_BENCHMARK_COLORS: Record<string, string> = {
  sp500_buy_hold: '#ef4444',
  stock_buy_hold: '#94a3b8',
  strategy_on_sp500: '#14b8a6',
};

const PLOT_HEIGHT = 340;
const PADDING = { top: 16, right: 60, bottom: 40, left: 12 };
const DATE_TICK_COUNT = 5;

type TriggerGroupKey =
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

const TRIGGER_GROUPS: Array<{
  key: TriggerGroupKey;
  label: string;
  labelKey?: 'priceHistory.compositeBuy' | 'priceHistory.compositeSell';
}> = [
  { key: 'compositeBuy', label: 'BUY', labelKey: 'priceHistory.compositeBuy' },
  { key: 'compositeSell', label: 'SELL', labelKey: 'priceHistory.compositeSell' },
  { key: 'macd', label: 'MACD' },
  { key: 'obv', label: 'OBV' },
  { key: 'kdj', label: 'KDJ' },
  { key: 'rsi', label: 'RSI' },
  { key: 'boll', label: 'BOLL' },
  { key: 'cci', label: 'CCI' },
  { key: 'dmi', label: 'DMI' },
  { key: 'mfi', label: 'MFI' },
];

// Colors and shapes for the extension-factor trigger groups (BOLL/CCI/DMI/MFI).
const EXTRA_GROUP_STYLES: Record<
  'boll' | 'cci' | 'dmi' | 'mfi',
  { buyColor: string; sellColor: string; buyShape: 'circle' | 'square' | 'triangleUp' | 'cross'; sellShape: 'circle' | 'square' | 'triangleDown' | 'cross' }
> = {
  boll: { buyColor: '#a78bfa', sellColor: '#7c3aed', buyShape: 'circle', sellShape: 'circle' },
  cci: { buyColor: '#fbbf24', sellColor: '#d97706', buyShape: 'square', sellShape: 'square' },
  dmi: { buyColor: '#2dd4bf', sellColor: '#0d9488', buyShape: 'triangleUp', sellShape: 'triangleDown' },
  mfi: { buyColor: '#f472b6', sellColor: '#db2777', buyShape: 'cross', sellShape: 'cross' },
};

// Composite score breakdown factor keys, rendered in display order with
// bilingual labels (classic factors first, extension factors after).
const COMPOSITE_FACTOR_ROWS: Array<{ key: keyof CompositeBreakdown; labelKey: string }> = [
  { key: 'macd', labelKey: 'priceHistory.factor.macd' },
  { key: 'kdj', labelKey: 'priceHistory.factor.kdj' },
  { key: 'rsi', labelKey: 'priceHistory.factor.rsi' },
  { key: 'regime', labelKey: 'priceHistory.factor.regime' },
  { key: 'momentum', labelKey: 'priceHistory.factor.momentum' },
  { key: 'boll', labelKey: 'priceHistory.factor.boll' },
  { key: 'cci', labelKey: 'priceHistory.factor.cci' },
  { key: 'dmi', labelKey: 'priceHistory.factor.dmi' },
  { key: 'mfi', labelKey: 'priceHistory.factor.mfi' },
  { key: 'volume', labelKey: 'priceHistory.factor.volume' },
  { key: 'range52', labelKey: 'priceHistory.factor.range52' },
];

// Series colors matching the reference image.
const COLOR_CLOSE = '#2f7de1';
const COLOR_SMA200 = '#d62728';
// Bollinger Bands (BOLL): solid upper/lower/mid lines, light-blue band fill.
const COLOR_BOLL = '#c084fc';
const COLOR_BOLL_FILL = '#87ceeb';

// Rainbow gradient: shorter SMA → redder, longer SMA → bluer.
// Keys: 5, 10, 20, 30, 40, 60, 120
const SMA_COLORS: Record<string, string> = {
  '5': '#ff4444',     // strong red
  '10': '#ff8800',    // orange-red
  '20': '#ffdd00',    // yellow
  '30': '#88cc00',    // lime green
  '40': '#00cccc',    // cyan
  '60': '#0066ff',    // blue
  '120': '#0022aa',   // deep blue
};

const SMA_DOTTED: Array<{ key: string; color: string }> = [
  { key: '5', color: SMA_COLORS['5'] },
  { key: '10', color: SMA_COLORS['10'] },
  { key: '20', color: SMA_COLORS['20'] },
  { key: '30', color: SMA_COLORS['30'] },
  { key: '40', color: SMA_COLORS['40'] },
  { key: '60', color: SMA_COLORS['60'] },
  { key: '120', color: SMA_COLORS['120'] },
];

const BUY = '#1faa3a';
const SELL = '#d62728';

// Per-stock threshold persistence (localStorage).
// Defaults mirror src/services/indicator_service.py DEFAULT_THRESHOLDS.
const DEFAULT_THRESHOLDS: IndicatorThresholds = DEFAULT_INDICATOR_THRESHOLDS;

// Fill any missing keys with defaults so older stored/backend threshold
// payloads (7 keys) keep working with the composite thresholds.
function normalizeThresholds(partial: Partial<IndicatorThresholds> | null | undefined): IndicatorThresholds {
  return normalizeIndicatorThresholds(partial);
}

function readStoredThresholds(stockCode: string): IndicatorThresholds | null {
  return readStoredIndicatorThresholds(stockCode);
}

function writeStoredThresholds(stockCode: string, thresholds: IndicatorThresholds): void {
  writeStoredIndicatorThresholds(stockCode, thresholds);
  notifyIndicatorThresholdsChanged(stockCode);
}

// ---------------------------------------------------------------------------
// Auto-tune result & preset persistence (localStorage, per-stock).
// ---------------------------------------------------------------------------
const AUTOTUNE_STORAGE_PREFIX = 'dsa.autotune.';
const AUTOTUNE_PRESETS_STORAGE_KEY = 'dsa.autotune.presets';

function hasCurrentMethodology(result: AutoTuneResponse): boolean {
  return result.methodologyVersion === AUTO_TUNE_METHODOLOGY_VERSION
    && (!result.fineTune || result.fineTune.selectionBasis === 'validation');
}

interface AutoTunePreset {
  id: string;
  name: string;
  timestamp: number;
  result: AutoTuneResponse;
  selectedStrategyKey: string | null;
  settings: {
    transactionWindow: number;
    autoTuneYears: number;
    autoTuneTestYears: number;
    trainRangePct: [number, number] | null;
    fineTuneEnabled: boolean;
    fineTuneDays: number;
  };
}

interface StoredAutoTuneState {
  result: AutoTuneResponse;
  selectedStrategyKey: string | null;
  settings: {
    transactionWindow: number;
    autoTuneYears: number;
    autoTuneTestYears: number;
    trainRangePct: [number, number] | null;
    fineTuneEnabled: boolean;
    fineTuneDays: number;
  };
}

function autoTuneStorageKey(stockCode: string): string {
  return `${AUTOTUNE_STORAGE_PREFIX}${stockCode.trim().toUpperCase()}`;
}

function readStoredAutoTune(stockCode: string): StoredAutoTuneState | null {
  if (typeof window === 'undefined') return null;
  try {
    const raw = window.localStorage.getItem(autoTuneStorageKey(stockCode));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as StoredAutoTuneState;
    if (parsed?.result?.strategies && Array.isArray(parsed.result.strategies)) {
      return parsed;
    }
    return null;
  } catch {
    return null;
  }
}

function writeStoredAutoTune(stockCode: string, state: StoredAutoTuneState): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(autoTuneStorageKey(stockCode), JSON.stringify(state));
  } catch {
    // best-effort
  }
}

function readStoredPresets(): AutoTunePreset[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(AUTOTUNE_PRESETS_STORAGE_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function writeStoredPresets(presets: AutoTunePreset[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(AUTOTUNE_PRESETS_STORAGE_KEY, JSON.stringify(presets));
  } catch {
    // best-effort
  }
}

// --- Auto Tune duration calibration ---------------------------------------
// The backend runs the whole optimization in a single request, so the
// progress bar estimates completion from elapsed time. Durations observed
// on previous runs (per parameter signature) are stored to make the
// estimate increasingly accurate.
const AUTOTUNE_DURATION_STORAGE_KEY = 'dsa.autotune.durations';

function readStoredDurations(): Record<string, number> {
  if (typeof window === 'undefined') return {};
  try {
    const raw = window.localStorage.getItem(AUTOTUNE_DURATION_STORAGE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch {
    return {};
  }
}

function recordAutoTuneDuration(signature: string, durationMs: number): void {
  if (typeof window === 'undefined') return;
  try {
    const map = readStoredDurations();
    const prev = map[signature];
    map[signature] = prev == null ? Math.round(durationMs) : Math.round(prev * 0.4 + durationMs * 0.6);
    window.localStorage.setItem(AUTOTUNE_DURATION_STORAGE_KEY, JSON.stringify(map));
  } catch {
    // best-effort
  }
}

function estimateAutoTuneDuration(
  years: number,
  testYears: number,
  fineTuneWindows: number,
  clippedRatio: number,
): number {
  const fetchMs = 8000;
  const trainYears = Math.max(1, (years - testYears) * clippedRatio);
  // Initial estimate allows for up to three chronological validation folds.
  // Completed runs replace this rough allowance with measured durations.
  const optimizeMs = (5000 + trainYears * 2200) * 3;
  // Sweep windows cover ~the full train span with step = window/5, so total
  // sweep cost is roughly a few times a single full-train optimization.
  const fineTuneMs = fineTuneWindows > 0 ? optimizeMs * Math.min(6, fineTuneWindows) * 0.8 : 0;
  return Math.round(fetchMs + optimizeMs + fineTuneMs);
}

interface ThresholdField {
  key: keyof IndicatorThresholds;
  labelKey:
    | 'priceHistory.thresholdBol'
    | 'priceHistory.thresholdMacdBuy'
    | 'priceHistory.thresholdMacdSell'
    | 'priceHistory.thresholdKdjBuy'
    | 'priceHistory.thresholdKdjSell'
    | 'priceHistory.thresholdRsiBuy'
    | 'priceHistory.thresholdRsiSell'
    | 'priceHistory.thresholdCompositeBuy'
    | 'priceHistory.thresholdCompositeSell'
    | 'priceHistory.thresholdMacdLookback'
    | 'priceHistory.thresholdMacdLowPercentile'
    | 'priceHistory.thresholdMacdHighPercentile'
    | 'priceHistory.thresholdRsiLow'
    | 'priceHistory.thresholdRsiHigh'
    | 'priceHistory.thresholdTrendPeriod'
    | 'priceHistory.thresholdBollBuyLevel'
    | 'priceHistory.thresholdBollSellLevel'
    | 'priceHistory.thresholdBollWeight'
    | 'priceHistory.thresholdCciBuyLevel'
    | 'priceHistory.thresholdCciSellLevel'
    | 'priceHistory.thresholdCciWeight'
    | 'priceHistory.thresholdAdxMinLevel'
    | 'priceHistory.thresholdDmiWeight'
    | 'priceHistory.thresholdMfiBuyLevel'
    | 'priceHistory.thresholdMfiSellLevel'
    | 'priceHistory.thresholdMfiWeight'
    | 'priceHistory.thresholdVolumeConfirmLevel'
    | 'priceHistory.thresholdVolumeWeight'
    | 'priceHistory.thresholdRange52HighLevel'
    | 'priceHistory.thresholdRange52LowLevel'
    | 'priceHistory.thresholdRange52Weight';
}

const THRESHOLD_FIELDS: ThresholdField[] = [
  { key: 'bolConstant', labelKey: 'priceHistory.thresholdBol' },
  { key: 'macdBuy', labelKey: 'priceHistory.thresholdMacdBuy' },
  { key: 'macdSell', labelKey: 'priceHistory.thresholdMacdSell' },
  { key: 'kdjBuy', labelKey: 'priceHistory.thresholdKdjBuy' },
  { key: 'kdjSell', labelKey: 'priceHistory.thresholdKdjSell' },
  { key: 'rsiBuy', labelKey: 'priceHistory.thresholdRsiBuy' },
  { key: 'rsiSell', labelKey: 'priceHistory.thresholdRsiSell' },
];

// Composite score thresholds grouped by role, so the UI renders them as visual clusters.
const COMPOSITE_SCORE_FIELDS: ThresholdField[] = [
  { key: 'compositeBuyThreshold', labelKey: 'priceHistory.thresholdCompositeBuy' },
  { key: 'compositeSellThreshold', labelKey: 'priceHistory.thresholdCompositeSell' },
];

const COMPOSITE_MACD_FIELDS: ThresholdField[] = [
  { key: 'macdLookback', labelKey: 'priceHistory.thresholdMacdLookback' },
  { key: 'macdLowPercentile', labelKey: 'priceHistory.thresholdMacdLowPercentile' },
  { key: 'macdHighPercentile', labelKey: 'priceHistory.thresholdMacdHighPercentile' },
];

const COMPOSITE_REGIME_FIELDS: ThresholdField[] = [
  { key: 'rsiLow', labelKey: 'priceHistory.thresholdRsiLow' },
  { key: 'rsiHigh', labelKey: 'priceHistory.thresholdRsiHigh' },
  { key: 'trendPeriod', labelKey: 'priceHistory.thresholdTrendPeriod' },
];

// Extension-factor thresholds (BOLL %B / CCI / DMI / MFI / volume / 52-week range).
// Weights are integer points; 0 disables the factor in the composite score.
const EXTRA_FACTOR_FIELDS: ThresholdField[] = [
  { key: 'bollBuyLevel', labelKey: 'priceHistory.thresholdBollBuyLevel' },
  { key: 'bollSellLevel', labelKey: 'priceHistory.thresholdBollSellLevel' },
  { key: 'bollWeight', labelKey: 'priceHistory.thresholdBollWeight' },
  { key: 'cciBuyLevel', labelKey: 'priceHistory.thresholdCciBuyLevel' },
  { key: 'cciSellLevel', labelKey: 'priceHistory.thresholdCciSellLevel' },
  { key: 'cciWeight', labelKey: 'priceHistory.thresholdCciWeight' },
  { key: 'adxMinLevel', labelKey: 'priceHistory.thresholdAdxMinLevel' },
  { key: 'dmiWeight', labelKey: 'priceHistory.thresholdDmiWeight' },
  { key: 'mfiBuyLevel', labelKey: 'priceHistory.thresholdMfiBuyLevel' },
  { key: 'mfiSellLevel', labelKey: 'priceHistory.thresholdMfiSellLevel' },
  { key: 'mfiWeight', labelKey: 'priceHistory.thresholdMfiWeight' },
  { key: 'volumeConfirmLevel', labelKey: 'priceHistory.thresholdVolumeConfirmLevel' },
  { key: 'volumeWeight', labelKey: 'priceHistory.thresholdVolumeWeight' },
  { key: 'range52HighLevel', labelKey: 'priceHistory.thresholdRange52HighLevel' },
  { key: 'range52LowLevel', labelKey: 'priceHistory.thresholdRange52LowLevel' },
  { key: 'range52Weight', labelKey: 'priceHistory.thresholdRange52Weight' },
];

function ThresholdFieldInput({
  field,
  value,
  onChange,
}: {
  field: ThresholdField;
  value: number | undefined;
  onChange: (key: keyof IndicatorThresholds, raw: string) => void;
}) {
  const { t } = useUiLanguage();
  return (
    <label className="flex flex-col gap-1 text-xs text-secondary-text">
      <span>{t(field.labelKey)}</span>
      <input
        type="number"
        step="any"
        value={value ?? ''}
        onChange={(event) => onChange(field.key, event.target.value)}
        className="w-20 rounded-md border border-border/70 bg-card px-2 py-1 text-xs text-foreground focus:border-primary/50 focus:outline-none"
      />
    </label>
  );
}

// Auto Tune 推荐参数的展示标签（key 为后端 snake_case 参数名）。
const AUTO_TUNE_PARAM_LABEL_KEYS: Record<string, string> = {
  composite_buy_threshold: 'priceHistory.autoTune.param.compositeBuyThreshold',
  composite_sell_threshold: 'priceHistory.autoTune.param.compositeSellThreshold',
  rsi_low: 'priceHistory.autoTune.param.rsiLow',
  rsi_high: 'priceHistory.autoTune.param.rsiHigh',
  kdj_low: 'priceHistory.autoTune.param.kdjLow',
  kdj_high: 'priceHistory.autoTune.param.kdjHigh',
  macd_lookback: 'priceHistory.autoTune.param.macdLookback',
  macd_low_percentile: 'priceHistory.autoTune.param.macdLowPercentile',
  macd_high_percentile: 'priceHistory.autoTune.param.macdHighPercentile',
  trend_period: 'priceHistory.autoTune.param.trendPeriod',
  stop_multiple_atr: 'priceHistory.autoTune.param.stopAtr',
  trail_multiple_atr: 'priceHistory.autoTune.param.trailAtr',
  boll_buy_level: 'priceHistory.autoTune.param.bollBuyLevel',
  boll_sell_level: 'priceHistory.autoTune.param.bollSellLevel',
  boll_weight: 'priceHistory.autoTune.param.bollWeight',
  cci_buy_level: 'priceHistory.autoTune.param.cciBuyLevel',
  cci_sell_level: 'priceHistory.autoTune.param.cciSellLevel',
  cci_weight: 'priceHistory.autoTune.param.cciWeight',
  adx_min_level: 'priceHistory.autoTune.param.adxMinLevel',
  dmi_weight: 'priceHistory.autoTune.param.dmiWeight',
  mfi_buy_level: 'priceHistory.autoTune.param.mfiBuyLevel',
  mfi_sell_level: 'priceHistory.autoTune.param.mfiSellLevel',
  mfi_weight: 'priceHistory.autoTune.param.mfiWeight',
  volume_confirm_level: 'priceHistory.autoTune.param.volumeConfirmLevel',
  volume_weight: 'priceHistory.autoTune.param.volumeWeight',
  range52_high_level: 'priceHistory.autoTune.param.range52HighLevel',
  range52_low_level: 'priceHistory.autoTune.param.range52LowLevel',
  range52_weight: 'priceHistory.autoTune.param.range52Weight',
};

// Display order for the selected strategy's tuned parameters.
const AUTO_TUNE_PARAM_ORDER = [
  'composite_buy_threshold',
  'composite_sell_threshold',
  'rsi_low',
  'rsi_high',
  'kdj_low',
  'kdj_high',
  'macd_lookback',
  'macd_low_percentile',
  'macd_high_percentile',
  'trend_period',
  'stop_multiple_atr',
  'trail_multiple_atr',
  'boll_buy_level',
  'boll_sell_level',
  'boll_weight',
  'cci_buy_level',
  'cci_sell_level',
  'cci_weight',
  'adx_min_level',
  'dmi_weight',
  'mfi_buy_level',
  'mfi_sell_level',
  'mfi_weight',
  'volume_confirm_level',
  'volume_weight',
  'range52_high_level',
  'range52_low_level',
  'range52_weight',
];

// Map Auto Tune threshold param keys to chart IndicatorThresholds keys,
// so the default value can be shown next to each tuned parameter.
const AUTO_TUNE_PARAM_THRESHOLD_KEYS: Record<string, keyof IndicatorThresholds> = {
  composite_buy_threshold: 'compositeBuyThreshold',
  composite_sell_threshold: 'compositeSellThreshold',
  rsi_low: 'rsiLow',
  rsi_high: 'rsiHigh',
  kdj_low: 'kdjLow',
  kdj_high: 'kdjHigh',
  macd_lookback: 'macdLookback',
  macd_low_percentile: 'macdLowPercentile',
  macd_high_percentile: 'macdHighPercentile',
  trend_period: 'trendPeriod',
  boll_buy_level: 'bollBuyLevel',
  boll_sell_level: 'bollSellLevel',
  boll_weight: 'bollWeight',
  cci_buy_level: 'cciBuyLevel',
  cci_sell_level: 'cciSellLevel',
  cci_weight: 'cciWeight',
  adx_min_level: 'adxMinLevel',
  dmi_weight: 'dmiWeight',
  mfi_buy_level: 'mfiBuyLevel',
  mfi_sell_level: 'mfiSellLevel',
  mfi_weight: 'mfiWeight',
  volume_confirm_level: 'volumeConfirmLevel',
  volume_weight: 'volumeWeight',
  range52_high_level: 'range52HighLevel',
  range52_low_level: 'range52LowLevel',
  range52_weight: 'range52Weight',
};

const AUTO_TUNE_REASON_KEYS: Record<string, string> = {
  baseline_sufficient: 'priceHistory.autoTune.reason.baseline_sufficient',
  best_validation: 'priceHistory.autoTune.reason.best_validation',
  simplicity_preference: 'priceHistory.autoTune.reason.simplicity_preference',
  insufficient_validation_trades: 'priceHistory.autoTune.reason.insufficient_validation_trades',
};

const formatAutoTuneValue = (value: number | null | undefined): string =>
  typeof value === 'number' && Number.isFinite(value) ? String(Number(value.toFixed(4))) : '--';

const formatEquityPct = (value: number): string =>
  `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;

const formatPrice = (value?: number | null): string =>
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(2) : '--';

// Catmull-Rom spline through finite points, producing a single smooth path.
const buildSmoothLinePath = (
  values: Array<number | null>,
  x: (i: number) => number,
  y: (v: number) => number,
): string => {
  const points: Array<{ px: number; py: number }> = [];
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    if (typeof v === 'number' && Number.isFinite(v)) {
      points.push({ px: x(i), py: y(v) });
    }
  }
  if (points.length === 0) return '';
  if (points.length === 1) return `M ${points[0].px} ${points[0].py}`;
  let d = `M ${points[0].px} ${points[0].py}`;
  for (let i = 0; i < points.length - 1; i += 1) {
    const p0 = points[Math.max(0, i - 1)];
    const p1 = points[i];
    const p2 = points[i + 1];
    const p3 = points[Math.min(points.length - 1, i + 2)];
    const c1x = p1.px + (p2.px - p0.px) / 6;
    const c1y = p1.py + (p2.py - p0.py) / 6;
    const c2x = p2.px - (p3.px - p1.px) / 6;
    const c2y = p2.py - (p3.py - p1.py) / 6;
    d += ` C ${c1x} ${c1y}, ${c2x} ${c2y}, ${p2.px} ${p2.py}`;
  }
  return d;
};

interface LinePath {
  d: string;
  color: string;
  width: number;
  dashed?: boolean;
}

const buildLinePath = (
  values: Array<number | null>,
  x: (i: number) => number,
  y: (v: number) => number,
): string => {
  let d = '';
  let started = false;
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    if (typeof v !== 'number' || !Number.isFinite(v)) {
      started = false;
      continue;
    }
    const px = x(i);
    const py = y(v);
    d += started ? ` L ${px} ${py}` : `M ${px} ${py}`;
    started = true;
  }
  return d;
};

// Bollinger middle band = (BOLU + BOLD) / 2, where both bands are finite.
const buildBollMidPath = (
  bolu: Array<number | null>,
  bold: Array<number | null>,
  x: (i: number) => number,
  y: (v: number) => number,
): string => {
  let d = '';
  let started = false;
  for (let i = 0; i < bolu.length; i += 1) {
    const upper = bolu[i];
    const lower = bold[i];
    if (
      typeof upper !== 'number' || !Number.isFinite(upper)
      || typeof lower !== 'number' || !Number.isFinite(lower)
    ) {
      started = false;
      continue;
    }
    const px = x(i);
    const py = y((upper + lower) / 2);
    d += started ? ` L ${px} ${py}` : `M ${px} ${py}`;
    started = true;
  }
  return d;
};

// Closed band between two series (e.g. BOLL upper/lower) for area fills.
// Emits one closed subpath per contiguous run of finite points.
const buildBandPath = (
  upper: Array<number | null>,
  lower: Array<number | null>,
  x: (i: number) => number,
  y: (v: number) => number,
): string => {
  let d = '';
  let segment: Array<{ ux: number; uy: number; lx: number; ly: number }> = [];
  const flush = () => {
    if (segment.length === 0) return;
    const first = segment[0];
    const last = segment[segment.length - 1];
    let path = `M ${first.ux} ${first.uy}`;
    for (let i = 1; i < segment.length; i += 1) {
      path += ` L ${segment[i].ux} ${segment[i].uy}`;
    }
    path += ` L ${last.lx} ${last.ly}`;
    for (let i = segment.length - 2; i >= 0; i -= 1) {
      path += ` L ${segment[i].lx} ${segment[i].ly}`;
    }
    path += ' Z';
    d += (d ? ' ' : '') + path;
    segment = [];
  };
  for (let i = 0; i < upper.length; i += 1) {
    const u = upper[i];
    const l = lower[i];
    if (
      typeof u !== 'number' || !Number.isFinite(u)
      || typeof l !== 'number' || !Number.isFinite(l)
    ) {
      flush();
      continue;
    }
    segment.push({ ux: x(i), uy: y(u), lx: x(i), ly: y(l) });
  }
  flush();
  return d;
};

interface Marker {
  index: number;
  value: number;
}

const collectMarkers = (series: Array<number | null>): Marker[] => {
  const out: Marker[] = [];
  for (let i = 0; i < series.length; i += 1) {
    const v = series[i];
    if (typeof v === 'number' && Number.isFinite(v)) {
      out.push({ index: i, value: v });
    }
  }
  return out;
};

// ---------------------------------------------------------------------------
// Fine Tune sweep chart: simple bar chart of OOS CAGR by window position.
// ---------------------------------------------------------------------------
interface FineTuneSweepChartProps {
  sweep: FineTuneSweepPosition[];
  bestIndex: number;
}

function FineTuneSweepChart({ sweep, bestIndex }: FineTuneSweepChartProps) {
  const { t } = useUiLanguage();
  if (!sweep.length) return null;
  const WIDTH = 600;
  const HEIGHT = 120;
  const PAD = { top: 10, right: 50, bottom: 24, left: 10 };
  const plotW = WIDTH - PAD.left - PAD.right;
  const plotH = HEIGHT - PAD.top - PAD.bottom;
  const slotW = plotW / sweep.length;
  const barW = Math.min(30, slotW * 0.8);
  const scores = sweep.map((p) => p.validationScore);
  const maxVal = Math.max(...scores, 1);
  const minVal = Math.min(...scores, 0);
  const range = maxVal - minVal || 1;
  const zeroY = PAD.top + (maxVal / range) * plotH;
  const yScale = (v: number) => PAD.top + ((maxVal - v) / range) * plotH;

  return (
    <svg role="img" aria-label={t('priceHistory.autoTune.fineTune.scoreTitle')} width={WIDTH} viewBox={`0 0 ${WIDTH} ${HEIGHT}`} className="block w-full" style={{ maxWidth: WIDTH }}>
      {/* Zero line */}
      <line x1={PAD.left} x2={WIDTH - PAD.right} y1={zeroY} y2={zeroY} stroke="var(--border)" strokeOpacity="0.5" />
      {/* Bars */}
      {sweep.map((pos, i) => {
        const x = PAD.left + i * slotW + (slotW - barW) / 2;
        const val = pos.validationScore;
        const barTop = val >= 0 ? yScale(val) : zeroY;
        const barH = Math.abs(yScale(val) - zeroY);
        const isBest = pos.positionIndex === bestIndex;
        return (
          <g key={pos.positionIndex}>
            <rect
              x={x}
              y={barTop}
              width={barW}
              height={Math.max(barH, 1)}
              rx={2}
              fill={isBest ? 'var(--color-primary, #22c55e)' : val >= 0 ? '#4ade80' : '#f87171'}
              opacity={isBest ? '1' : '0.65'}
            />
            {/* Value label */}
            {slotW >= 28 || isBest ? <text
              x={x + barW / 2}
              y={val >= 0 ? barTop - 3 : barTop + barH + 10}
              fontSize="9"
              fill={isBest ? '#ffffff' : '#9ca3af'}
              textAnchor="middle"
              fontWeight={isBest ? 'bold' : 'normal'}
            >
              {val.toFixed(2)}
            </text> : null}
            {/* Position label */}
            {slotW >= 20 || isBest ? <text x={x + barW / 2} y={HEIGHT - 4} fontSize="8" fill="#6b7280" textAnchor="middle">
              {pos.positionIndex + 1}
            </text> : null}
          </g>
        );
      })}
    </svg>
  );
}

export interface StockIndicatorChartProps {
  stockCode: string;
  stockName?: string;
}

function TestConfidence({ confidence }: { confidence: AutoTuneTestConfidence }) {
  const { t } = useUiLanguage();
  return (
    <div className="mt-2 text-xs text-secondary-text" data-testid="test-confidence">
      {confidence.available ? (
        <>
          <span>{t('priceHistory.autoTune.confidence.interval', {
            level: String(Math.round(confidence.confidenceLevel * 100)),
            lower: formatAutoTuneValue(confidence.sharpeCiLower),
            upper: formatAutoTuneValue(confidence.sharpeCiUpper),
          })}</span>
          <span>{' · '}{t('priceHistory.autoTune.confidence.positiveShare', {
            percent: formatAutoTuneValue((confidence.positiveSharpeFraction ?? 0) * 100),
          })}</span>
        </>
      ) : (
        <span>{t('priceHistory.autoTune.confidence.insufficient')}</span>
      )}
      <p className="mt-1">{t('priceHistory.autoTune.confidence.note')}</p>
    </div>
  );
}

export const StockIndicatorChart: React.FC<StockIndicatorChartProps> = ({ stockCode, stockName }) => {
  const { t, language } = useUiLanguage();
  const [days, setDays] = useState(180);
  const [thresholds, setThresholds] = useState<IndicatorThresholds | null>(null);
  const [result, setResult] = useState<StockIndicatorsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [transactionWindow, setTransactionWindow] = useState(90);
  const [transactionWindowRaw, setTransactionWindowRaw] = useState('90');
  const [autoTuneYears, setAutoTuneYears] = useState(10);
  const [autoTuneYearsRaw, setAutoTuneYearsRaw] = useState('10');
  const [autoTuneTestYears, setAutoTuneTestYears] = useState(3);
  const [fineTuneEnabled, setFineTuneEnabled] = useState(false);
  const [fineTuneDays, setFineTuneDays] = useState(360);
  const [fineTuneDaysRaw, setFineTuneDaysRaw] = useState('360');
  const [trainRangePct, setTrainRangePct] = useState<[number, number] | null>(null);
  const [isTuning, setIsTuning] = useState(false);
  const [trainRangeExpanded, setTrainRangeExpanded] = useState(true);
  const [fineTuneTableExpanded, setFineTuneTableExpanded] = useState(false);
  const [tuneProgress, setTuneProgress] = useState<{
    startMs: number;
    estimateMs: number;
    fineTuneWindows: number;
  } | null>(null);
  const [progressTick, setProgressTick] = useState(0);
  const [autoTuneResult, setAutoTuneResult] = useState<AutoTuneResponse | null>(null);
  const [acesConfig, setACESConfig] = useState<Record<string, unknown> | undefined>();
  const [acesValid, setACESValid] = useState(true);
  const [selectedStrategyKey, setSelectedStrategyKey] = useState<string | null>(null);
  const [equityHoverIndex, setEquityHoverIndex] = useState<number | null>(null);
  const [autoTuneError, setAutoTuneError] = useState<string | null>(null);
  const [presets, setPresets] = useState<AutoTunePreset[]>([]);
  const [presetNameInput, setPresetNameInput] = useState('');
  const [showPresetInput, setShowPresetInput] = useState(false);
  const requestSeqRef = useRef(0);
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [visibleTriggers, setVisibleTriggers] = useState<Record<TriggerGroupKey, boolean>>({
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
  });
  const [showCompositeDebug, setShowCompositeDebug] = useState(false);

  // Keep the chart sized to its container so the lines fit the current window.
  // The measured div only renders after data loads, so re-run once isLoading
  // settles and the chart is mounted.
  useEffect(() => {
    const el = chartContainerRef.current;
    if (!el) return;
    const update = () => {
      setContainerWidth(el.clientWidth);
    };
    update();
    if (typeof ResizeObserver === 'undefined') {
      window.addEventListener('resize', update);
      return () => window.removeEventListener('resize', update);
    }
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [isLoading]);

  const load = useCallback(
    async (windowDays: number, th: IndicatorThresholds | null) => {
      const seq = ++requestSeqRef.current;
      setIsLoading(true);
      setError(null);
      try {
        const response = await stocksApi.getIndicators(stockCode, {
          period: 'daily',
          days: windowDays,
          ...(th ?? {}),
        });
        if (seq !== requestSeqRef.current) return;
        setResult(response);
        if (!th) {
          setThresholds(normalizeThresholds(response.thresholds));
        }
      } catch (err) {
        if (seq !== requestSeqRef.current) return;
        setError(err);
      } finally {
        if (seq === requestSeqRef.current) setIsLoading(false);
      }
    },
    [stockCode],
  );

  useEffect(() => {
    const stored = readStoredThresholds(stockCode);
    setThresholds(stored);
    void load(days, stored);
  }, [load, days, stockCode]);

  // Load saved auto-tune results and presets on mount / stock change.
  useEffect(() => {
    setPresets(readStoredPresets());
    const saved = readStoredAutoTune(stockCode);
    if (saved) {
      setAutoTuneResult(saved.result);
      setSelectedStrategyKey(saved.selectedStrategyKey);
      setTransactionWindow(saved.settings.transactionWindow);
      setTransactionWindowRaw(String(saved.settings.transactionWindow));
      setAutoTuneYears(saved.settings.autoTuneYears);
      setAutoTuneYearsRaw(String(saved.settings.autoTuneYears));
      setAutoTuneTestYears(saved.settings.autoTuneTestYears ?? 3);
      setFineTuneEnabled(saved.settings.fineTuneEnabled ?? false);
      setFineTuneDays(saved.settings.fineTuneDays ?? 360);
      setFineTuneDaysRaw(String(saved.settings.fineTuneDays ?? 360));
      setTrainRangePct(saved.settings.trainRangePct);
    } else {
      setAutoTuneResult(null);
      setSelectedStrategyKey(null);
    }
    setEquityHoverIndex(null);
    setAutoTuneError(null);
  }, [stockCode]);

  const handleThresholdChange = useCallback((key: keyof IndicatorThresholds, raw: string) => {
    const parsed = Number(raw);
    setThresholds((prev) => {
      if (!prev) return prev;
      const next = { ...prev, [key]: Number.isFinite(parsed) ? parsed : prev[key] };
      writeStoredThresholds(stockCode, next);
      if (Number.isFinite(parsed)) {
        void load(days, next);
      }
      return next;
    });
  }, [days, load, stockCode]);

  // 训练段滑杆的可用区间：历史起点 ~ 验证段开始前一日（验证/测试位置不受裁剪影响）。
  const trainDomain = useMemo(() => {
    if (!autoTuneResult) return null;
    const validationStart = autoTuneResult.split.validation?.startDate;
    if (!validationStart) return null;
    const startMs = parseDayMs(autoTuneResult.history.startDate);
    const endMs = parseDayMs(validationStart) - DAY_MS;
    if (!(endMs > startMs)) return null;
    return { startMs, endMs };
  }, [autoTuneResult]);

  const trainRangeDates = useMemo(() => {
    if (!trainDomain) return null;
    const [lo, hi] = trainRangePct ?? [0, TRAIN_RANGE_SCALE];
    const span = trainDomain.endMs - trainDomain.startMs;
    return {
      start: formatDayMs(trainDomain.startMs + Math.round((lo / TRAIN_RANGE_SCALE) * span)),
      end: formatDayMs(trainDomain.startMs + Math.round((hi / TRAIN_RANGE_SCALE) * span)),
    };
  }, [trainDomain, trainRangePct]);

  // 历史/测试段长度变化会改变可训练区间，旧的裁剪范围不再有意义。
  useEffect(() => {
    setTrainRangePct(null);
  }, [autoTuneYears, autoTuneTestYears, stockCode]);

  const handleTrainRangeChange = useCallback((which: 'start' | 'end', raw: number) => {
    setTrainRangePct((prev) => {
      const [lo, hi] = prev ?? [0, TRAIN_RANGE_SCALE];
      if (which === 'start') {
        return [Math.min(Math.max(0, raw), hi - TRAIN_RANGE_MIN_GAP), hi];
      }
      return [lo, Math.max(Math.min(TRAIN_RANGE_SCALE, raw), lo + TRAIN_RANGE_MIN_GAP)];
    });
  }, []);

  const runAutoTune = useCallback(async () => {
    setIsTuning(true);
    setAutoTuneError(null);
    const clipped =
      trainRangePct != null && (trainRangePct[0] !== 0 || trainRangePct[1] !== TRAIN_RANGE_SCALE);
    const fineTuneWindows =
      fineTuneEnabled && fineTuneDays > 0
        ? Math.max(1, Math.floor(((autoTuneYears - autoTuneTestYears) * 365 - fineTuneDays) / Math.max(1, Math.floor(fineTuneDays / 5))) + 1)
        : 0;
    const durationSignature = `${AUTO_TUNE_METHODOLOGY_VERSION}|${autoTuneYears}|${autoTuneTestYears}|${fineTuneWindows}|${clipped ? 'clipped' : 'full'}`;
    const calibratedMs = readStoredDurations()[durationSignature];
    const estimateMs = calibratedMs ?? estimateAutoTuneDuration(autoTuneYears, autoTuneTestYears, fineTuneWindows, clipped ? 0.7 : 1);
    const startedAt = Date.now();
    setTuneProgress({ startMs: startedAt, estimateMs, fineTuneWindows });
    try {
      const response = await stocksApi.autoTune(stockCode, {
        acesConfig,
        windowDays: transactionWindow,
        years: autoTuneYears,
        testYears: autoTuneTestYears,
        ...(clipped && trainRangeDates
          ? { trainStartDate: trainRangeDates.start, trainEndDate: trainRangeDates.end }
          : {}),
        ...(fineTuneEnabled && fineTuneDays > 0
          ? { fineTuneWindowDays: fineTuneDays }
          : {}),
      });
      recordAutoTuneDuration(durationSignature, Date.now() - startedAt);
      setAutoTuneResult(response);
      setSelectedStrategyKey(null);
      setEquityHoverIndex(null);
      // Persist results so they survive stock switch / page reload.
      writeStoredAutoTune(stockCode, {
        result: response,
        selectedStrategyKey: null,
        settings: {
          transactionWindow,
          autoTuneYears,
          autoTuneTestYears,
          trainRangePct: clipped ? trainRangePct : null,
          fineTuneEnabled,
          fineTuneDays,
        },
      });
    } catch (err) {
      setAutoTuneResult(null);
      setAutoTuneError(err instanceof Error ? err.message : String(err));
    } finally {
      setIsTuning(false);
      setTuneProgress(null);
    }
  }, [autoTuneTestYears, autoTuneYears, stockCode, transactionWindow, trainRangeDates, trainRangePct, fineTuneEnabled, fineTuneDays, acesConfig]);

  // Tick while tuning so the progress bar/elapsed time re-renders.
  useEffect(() => {
    if (!tuneProgress) return;
    const id = window.setInterval(() => setProgressTick((v) => v + 1), 250);
    return () => window.clearInterval(id);
  }, [tuneProgress]);

  const tuneProgressInfo = useMemo(() => {
    if (!tuneProgress) return null;
    void progressTick;
    const elapsedMs = Date.now() - tuneProgress.startMs;
    const frac = Math.min(0.97, elapsedMs / Math.max(1000, tuneProgress.estimateMs));
    const fetchEnd = 0.12;
    const optimizeEnd = tuneProgress.fineTuneWindows > 0 ? 0.55 : 0.99;
    let stage: 'fetching' | 'optimizing' | 'fineTuning' = 'fetching';
    if (frac >= optimizeEnd) {
      stage = 'fineTuning';
    } else if (frac >= fetchEnd) {
      stage = 'optimizing';
    }
    let fineTuneCurrent = 0;
    if (stage === 'fineTuning' && tuneProgress.fineTuneWindows > 0) {
      const ftFrac = (frac - optimizeEnd) / Math.max(0.01, 0.99 - optimizeEnd);
      fineTuneCurrent = Math.min(tuneProgress.fineTuneWindows, Math.floor(ftFrac * tuneProgress.fineTuneWindows) + 1);
    }
    return {
      percent: Math.max(1, Math.round(frac * 100)),
      stage,
      fineTuneCurrent,
      fineTuneTotal: tuneProgress.fineTuneWindows,
      elapsedSeconds: Math.floor(elapsedMs / 1000),
      etaSeconds: Math.max(0, Math.ceil((tuneProgress.estimateMs - elapsedMs) / 1000)),
    };
  }, [tuneProgress, progressTick]);

  // Persist selected strategy key whenever it changes (after user clicks a row).
  useEffect(() => {
    if (!autoTuneResult) return;
    const saved = readStoredAutoTune(stockCode);
    if (saved) {
      writeStoredAutoTune(stockCode, { ...saved, selectedStrategyKey });
    }
  }, [selectedStrategyKey, autoTuneResult, stockCode]);

  const applyAutoTunedThresholds = useCallback(() => {
    if (!autoTuneResult || !hasCurrentMethodology(autoTuneResult)) return;
    const selectedKey = selectedStrategyKey ?? autoTuneResult.recommended.strategyKey;
    const selected = autoTuneResult.strategies.find((strategy) => strategy.key === selectedKey);
    if (!selected) return;
    const next = normalizeThresholds({
      ...(thresholds ?? {}),
      ...selected.params.thresholds,
    });
    setThresholds(next);
    writeStoredThresholds(stockCode, next);
    void load(days, next);
  }, [autoTuneResult, days, load, selectedStrategyKey, stockCode, thresholds]);

  const restoreDefaultThresholds = useCallback(() => {
    const next: IndicatorThresholds = { ...DEFAULT_THRESHOLDS };
    setThresholds(next);
    writeStoredThresholds(stockCode, next);
    void load(days, next);
  }, [days, load, stockCode]);

  const applyJointThresholds = useCallback((buy: number, sell: number) => {
    if (!autoTuneResult || !hasCurrentMethodology(autoTuneResult)) return;
    const next = normalizeThresholds({ ...DEFAULT_THRESHOLDS,
      compositeBuyThreshold: buy, compositeSellThreshold: -sell });
    setThresholds(next);
    writeStoredThresholds(stockCode, next);
    void load(days, next);
  }, [autoTuneResult, days, load, stockCode]);

  // --- Preset management ---------------------------------------------------
  const savePreset = useCallback(() => {
    if (!autoTuneResult || !hasCurrentMethodology(autoTuneResult) || !presetNameInput.trim()) return;
    const preset: AutoTunePreset = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      name: presetNameInput.trim(),
      timestamp: Date.now(),
      result: autoTuneResult,
      selectedStrategyKey,
      settings: {
        transactionWindow,
        autoTuneYears,
        autoTuneTestYears,
        trainRangePct,
        fineTuneEnabled,
        fineTuneDays,
      },
    };
    const next = [...presets, preset];
    setPresets(next);
    writeStoredPresets(next);
    setPresetNameInput('');
    setShowPresetInput(false);
  }, [autoTuneResult, presetNameInput, presets, selectedStrategyKey, transactionWindow, autoTuneYears, autoTuneTestYears, trainRangePct, fineTuneEnabled, fineTuneDays]);

  const loadPreset = useCallback((preset: AutoTunePreset) => {
    setAutoTuneResult(preset.result);
    setSelectedStrategyKey(preset.selectedStrategyKey);
    setTransactionWindow(preset.settings.transactionWindow);
    setTransactionWindowRaw(String(preset.settings.transactionWindow));
    setAutoTuneYears(preset.settings.autoTuneYears);
    setAutoTuneYearsRaw(String(preset.settings.autoTuneYears));
    setAutoTuneTestYears(preset.settings.autoTuneTestYears);
    setTrainRangePct(preset.settings.trainRangePct);
    setFineTuneEnabled(preset.settings.fineTuneEnabled ?? false);
    setFineTuneDays(preset.settings.fineTuneDays ?? 360);
    setFineTuneDaysRaw(String(preset.settings.fineTuneDays ?? 360));
    setEquityHoverIndex(null);
    setAutoTuneError(null);
    // Also persist as the "last" state for this stock.
    writeStoredAutoTune(stockCode, {
      result: preset.result,
      selectedStrategyKey: preset.selectedStrategyKey,
      settings: preset.settings,
    });
  }, [stockCode]);

  const deletePreset = useCallback((presetId: string) => {
    const next = presets.filter((p) => p.id !== presetId);
    setPresets(next);
    writeStoredPresets(next);
  }, [presets]);

  // Strategy rows are selectable by mouse click or keyboard
  // (Enter/Space selects, ArrowUp/ArrowDown moves the selection).
  const handleStrategyRowKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLTableRowElement>, index: number) => {
      if (!autoTuneResult) return;
      const strategies = autoTuneResult.strategies;
      if (event.key === 'Enter' || event.key === ' ') {
        event.preventDefault();
        setSelectedStrategyKey(strategies[index].key);
      } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
        event.preventDefault();
        const delta = event.key === 'ArrowDown' ? 1 : -1;
        const nextIndex = Math.min(strategies.length - 1, Math.max(0, index + delta));
        setSelectedStrategyKey(strategies[nextIndex].key);
      }
    },
    [autoTuneResult],
  );

  const selectedAutoTuneKey = selectedStrategyKey
    ?? autoTuneResult?.recommended.strategyKey
    ?? null;
  const isCurrentAutoTune = autoTuneResult != null && hasCurrentMethodology(autoTuneResult);
  const selectedAutoTuneStrategy = autoTuneResult?.strategies.find(
    (strategy) => strategy.key === selectedAutoTuneKey,
  ) ?? null;

  // Live parameter display for the currently selected strategy.
  const selectedParamDisplay = useMemo(() => {
    if (!selectedAutoTuneStrategy) {
      return [] as Array<{ key: string; value: number; default: number | null }>;
    }
    const rows: Array<{ key: string; value: number; default: number | null }> = [];
    for (const key of AUTO_TUNE_PARAM_ORDER) {
      let value: number | null | undefined;
      if (key === 'stop_multiple_atr') {
        value = selectedAutoTuneStrategy.params.stopMultipleAtr;
      } else if (key === 'trail_multiple_atr') {
        value = selectedAutoTuneStrategy.params.trailMultipleAtr;
      } else {
        const camelKey = key.replace(/_([a-z])/g, (_match, char: string) => char.toUpperCase());
        value = (
          selectedAutoTuneStrategy.params.thresholds as Record<string, number | null | undefined>
        )[camelKey];
      }
      if (typeof value !== 'number' || !Number.isFinite(value)) continue;
      const thresholdKey = AUTO_TUNE_PARAM_THRESHOLD_KEYS[key];
      const defaultValue = thresholdKey ? DEFAULT_THRESHOLDS[thresholdKey] : null;
      rows.push({
        key,
        value,
        default: typeof defaultValue === 'number' ? defaultValue : null,
      });
    }
    return rows;
  }, [selectedAutoTuneStrategy]);

  // Cumulative-profit curves over the test window for all strategies + benchmarks.
  const autoTuneEquityPlot = useMemo(() => {
    if (!autoTuneResult) return null;
    const seriesList: Array<{
      key: string;
      label: string;
      color: string;
      dashed: boolean;
      values: number[];
    }> = [];
    for (const strategy of autoTuneResult.strategies) {
      if (strategy.testEquity && strategy.testEquity.values.length > 1) {
        seriesList.push({
          key: strategy.key,
          label: (language === 'zh' ? strategy.nameZh : strategy.nameEn) || strategy.key,
          color: AUTO_TUNE_STRATEGY_COLORS[strategy.key] ?? '#8884d8',
          dashed: false,
          values: strategy.testEquity.values,
        });
      }
    }
    for (const benchmark of autoTuneResult.benchmarks) {
      if (benchmark.available && benchmark.testEquity && benchmark.testEquity.values.length > 1) {
        seriesList.push({
          key: benchmark.key,
          label: (language === 'zh' ? benchmark.nameZh : benchmark.nameEn) || benchmark.key,
          color: AUTO_TUNE_BENCHMARK_COLORS[benchmark.key] ?? '#94a3b8',
          dashed: true,
          values: benchmark.testEquity.values,
        });
      }
    }
    if (seriesList.length === 0) return null;

    const allValues = seriesList.flatMap((series) => series.values);
    let min = Math.min(0, ...allValues);
    let max = Math.max(0, ...allValues);
    const span = max - min || 1;
    min -= span * 0.06;
    max += span * 0.06;

    const width = containerWidth > 0 ? containerWidth : 720;
    const left = 12;
    const right = 60;
    const top = 8;
    const plotHeight = 120;
    const axisY = top + plotHeight + 16;
    const x = (index: number, length: number) =>
      left + (length > 1 ? index / (length - 1) : 0) * (width - left - right);
    const y = (value: number) => top + ((max - value) / (max - min)) * plotHeight;

    const dates = autoTuneResult.strategies.find(
      (strategy) => strategy.testEquity && strategy.testEquity.dates.length > 0,
    )?.testEquity?.dates ?? [];
    const tickCount = dates.length > 1 ? Math.min(5, dates.length) : dates.length;
    const dateTicks = Array.from({ length: tickCount }, (_unused, i) => {
      const index = tickCount > 1
        ? Math.round((i / (tickCount - 1)) * (dates.length - 1))
        : 0;
      return { x: x(index, dates.length), label: dates[index]?.slice(0, 7) ?? '' };
    });

    // Nice round horizontal gridlines between min and max.
    const rawStep = (max - min) / 4;
    const magnitude = 10 ** Math.floor(Math.log10(rawStep));
    const step = Math.ceil(rawStep / magnitude) * magnitude;
    const gridTicks: number[] = [];
    for (let value = Math.ceil(min / step) * step; value <= max; value += step) {
      gridTicks.push(Math.round(value * 100) / 100);
    }

    return {
      seriesList,
      width,
      left,
      right,
      top,
      plotWidth: width - left - right,
      refLength: seriesList[0]?.values.length ?? dates.length,
      dates,
      x,
      y,
      dateTicks,
      gridTicks,
      axisY,
    };
  }, [autoTuneResult, containerWidth, language]);

  const toggleTrigger = useCallback((key: TriggerGroupKey) => {
    setVisibleTriggers((prev) => ({ ...prev, [key]: !prev[key] }));
  }, []);

  const geometry = useMemo(() => {
    if (!result || result.dates.length === 0) return null;
    const n = result.dates.length;
    const targetWidth = containerWidth > 0 ? containerWidth : 720;
    // Always fit the container width (no horizontal scrollbar, incl. 365D).
    const step = (targetWidth - PADDING.left - PADDING.right) / Math.max(n, 1);
    const width = Math.max(targetWidth, n * step + PADDING.left + PADDING.right);

    const allValues: number[] = [];
    const pushSeries = (series?: Array<number | null>) => {
      series?.forEach((v) => {
        if (typeof v === 'number' && Number.isFinite(v)) allValues.push(v);
      });
    };
    pushSeries(result.close);
    pushSeries(result.bolu);
    pushSeries(result.bold);
    SMA_DOTTED.forEach(({ key }) => pushSeries(result.sma[key]));
    pushSeries(result.sma['200']);

    let min = allValues.length ? Math.min(...allValues) : 0;
    let max = allValues.length ? Math.max(...allValues) : 1;
    if (min === max) {
      min -= 1;
      max += 1;
    }
    const pad = (max - min) * 0.06;
    min -= pad;
    max += pad;

    const x = (i: number): number => PADDING.left + i * step + step / 2;
    const y = (v: number): number =>
      PADDING.top + PLOT_HEIGHT - ((v - min) / (max - min)) * PLOT_HEIGHT;

    const ticks = [0, 0.25, 0.5, 0.75, 1].map((ratio) => {
      const value = max - ratio * (max - min);
      return { value, y: PADDING.top + ratio * PLOT_HEIGHT };
    });

    const dateIndices = Array.from(
      new Set(
        Array.from({ length: DATE_TICK_COUNT }, (_, i) =>
          Math.round(((n - 1) * i) / (DATE_TICK_COUNT - 1)),
        ),
      ),
    );
    const dateTicks = dateIndices.map((index) => ({
      index,
      x: x(index),
      label: result.dates[index] ?? '',
    }));

    return { n, step, width, x, y, ticks, dateTicks, min, max };
  }, [result, containerWidth]);

  const linePaths = useMemo<LinePath[]>(() => {
    if (!result || !geometry) return [];
    const paths: LinePath[] = [];
    // Bollinger Bands drawn beneath the SMAs / close line.
    // Upper/lower band strokes are intentionally omitted; only the mid
    // line and the band fill are rendered.
    const bollMid = buildBollMidPath(result.bolu ?? [], result.bold ?? [], geometry.x, geometry.y);
    if (bollMid) paths.push({ d: bollMid, color: COLOR_BOLL, width: 1.4 });
    for (const { key, color } of SMA_DOTTED) {
      const d = buildLinePath(result.sma[key] ?? [], geometry.x, geometry.y);
      if (d) paths.push({ d, color, width: 1.2, dashed: true });
    }
    const sma200 = buildLinePath(result.sma['200'] ?? [], geometry.x, geometry.y);
    if (sma200) paths.push({ d: sma200, color: COLOR_SMA200, width: 1.8 });
    const closePath = buildLinePath(result.close, geometry.x, geometry.y);
    if (closePath) paths.push({ d: closePath, color: COLOR_CLOSE, width: 2.2 });
    return paths;
  }, [result, geometry]);

  const bollBandPath = useMemo(() => {
    if (!result || !geometry) return '';
    return buildBandPath(result.bolu ?? [], result.bold ?? [], geometry.x, geometry.y);
  }, [result, geometry]);

  const markers = useMemo(() => {
    if (!result) return null;
    const collect = (series?: Array<number | null>): Marker[] => collectMarkers(series ?? []);
    return {
      macdBuy: collect(result.triggers.macdBuy),
      macdSell: collect(result.triggers.macdSell),
      obvBuy: collect(result.triggers.obvBuy),
      obvSell: collect(result.triggers.obvSell),
      kdjBuy: collect(result.triggers.kdjBuy),
      kdjSell: collect(result.triggers.kdjSell),
      rsiBuy: collect(result.triggers.rsiBuy),
      rsiSell: collect(result.triggers.rsiSell),
      bollBuy: collect(result.triggers.bollBuy),
      bollSell: collect(result.triggers.bollSell),
      cciBuy: collect(result.triggers.cciBuy),
      cciSell: collect(result.triggers.cciSell),
      dmiBuy: collect(result.triggers.dmiBuy),
      dmiSell: collect(result.triggers.dmiSell),
      mfiBuy: collect(result.triggers.mfiBuy),
      mfiSell: collect(result.triggers.mfiSell),
    };
  }, [result]);

  const compositeMarkers = useMemo(() => {
    const composite = result?.composite;
    if (!composite) return null;
    const buy: Array<{ marker: Marker; score: number }> = [];
    const sell: Array<{ marker: Marker; score: number }> = [];
    const buySignal = composite.buySignal ?? [];
    const sellSignal = composite.sellSignal ?? [];
    const buyScore = composite.buyScore ?? [];
    const sellScore = composite.sellScore ?? [];
    for (let i = 0; i < buySignal.length; i += 1) {
      const v = buySignal[i];
      if (typeof v === 'number' && Number.isFinite(v)) {
        buy.push({ marker: { index: i, value: v }, score: buyScore[i] ?? 0 });
      }
    }
    for (let i = 0; i < sellSignal.length; i += 1) {
      const v = sellSignal[i];
      if (typeof v === 'number' && Number.isFinite(v)) {
        sell.push({ marker: { index: i, value: v }, score: sellScore[i] ?? 0 });
      }
    }
    return { buy, sell };
  }, [result]);

  const latestComposite = useMemo(() => {
    const composite = result?.composite;
    if (!composite || composite.buyScore.length === 0) return null;
    const i = composite.buyScore.length - 1;
    return {
      buyScore: composite.buyScore[i] ?? 0,
      sellScore: composite.sellScore[i] ?? 0,
      buyBreakdown: composite.buyBreakdown?.[i],
      sellBreakdown: composite.sellBreakdown?.[i],
      maxBuyScore: composite.maxBuyScore,
      maxSellScore: composite.maxSellScore,
    };
  }, [result]);

  const latest = result && result.close.length ? result.close[result.close.length - 1] : null;
  const hoveredPoint = result && geometry && hoveredIndex !== null
    ? {
      index: hoveredIndex,
      value: result.close[hoveredIndex],
      x: geometry.x(hoveredIndex),
      y: geometry.y(result.close[hoveredIndex]),
      date: result.dates[hoveredIndex] ?? '--',
    }
    : null;
  const rangeLabel =
    result && result.dates.length > 1
      ? `${result.dates[0]} ~ ${result.dates[result.dates.length - 1]}`
      : result?.dates[0] ?? '--';

  const renderMarker = (marker: Marker, kind: 'circle' | 'triangleUp' | 'triangleDown' | 'square' | 'cross', color: string, label?: boolean) => {
    if (!geometry) return null;
    const cx = geometry.x(marker.index);
    const cy = geometry.y(marker.value);
    const key = `${kind}-${marker.index}-${marker.value}`;
    const size = 6;
    let shape: React.ReactNode = null;
    if (kind === 'circle') {
      shape = <circle cx={cx} cy={cy} r={size} fill={color} stroke="#fff" strokeWidth={1} />;
    } else if (kind === 'cross') {
      shape = (
        <g stroke={color} strokeWidth={2} strokeLinecap="round">
          <line x1={cx - size - 1} y1={cy - size - 1} x2={cx + size + 1} y2={cy + size + 1} />
          <line x1={cx - size - 1} y1={cy + size + 1} x2={cx + size + 1} y2={cy - size - 1} />
        </g>
      );
    } else if (kind === 'square') {
      shape = (
        <rect x={cx - size} y={cy - size} width={size * 2} height={size * 2} fill={color} stroke="#fff" strokeWidth={1} />
      );
    } else if (kind === 'triangleUp') {
      shape = (
        <polygon
          points={`${cx},${cy - size - 2} ${cx - size - 1},${cy + size} ${cx + size + 1},${cy + size}`}
          fill={color}
          stroke="#fff"
          strokeWidth={1}
        />
      );
    } else {
      shape = (
        <polygon
          points={`${cx},${cy + size + 2} ${cx - size - 1},${cy - size} ${cx + size + 1},${cy - size}`}
          fill={color}
          stroke="#fff"
          strokeWidth={1}
        />
      );
    }
    return (
      <g key={key}>
        {shape}
        {label ? (
          <text x={cx + size + 2} y={cy - size - 2} fontSize="10" fill={color} fontWeight={600}>
            {formatPrice(marker.value)}
          </text>
        ) : null}
      </g>
    );
  };

  const renderCompositeMarker = (marker: Marker, score: number, kind: 'buy' | 'sell') => {
    if (!geometry) return null;
    const cx = geometry.x(marker.index);
    const cy = geometry.y(marker.value);
    const color = kind === 'buy' ? BUY : SELL;
    const size = 5;
    const key = `composite-${kind}-${marker.index}-${marker.value}`;
    const shape = kind === 'buy' ? (
      <polygon
        points={`${cx},${cy - size - 2} ${cx - size - 1},${cy + size} ${cx + size + 1},${cy + size}`}
        fill={color}
        stroke="#fff"
        strokeWidth={1}
      />
    ) : (
      <polygon
        points={`${cx},${cy + size + 2} ${cx - size - 1},${cy - size} ${cx + size + 1},${cy - size}`}
        fill={color}
        stroke="#fff"
        strokeWidth={1}
      />
    );
    return (
      <g key={key}>
        {shape}
        <text x={cx + size + 2} y={cy - size - 2} fontSize="10" fill={color} fontWeight={700}>
          {kind === 'buy' ? `BUY ${score}` : `SELL ${score}`}
        </text>
      </g>
    );
  };

  return (
    <Card variant="bordered" padding="md" className="home-panel-card flex flex-col">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-foreground">{t('priceHistory.indicatorTitle')}</h2>
          <p className="mt-0.5 text-sm text-secondary-text">
            {stockName || result?.stockName || stockCode} · {stockCode}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="ml-2 text-base font-semibold tabular-nums text-foreground">
            {formatPrice(latest)}
          </span>
        </div>
      </div>

      {thresholds ? (
        <div className="order-3">
        <>
        <div className="mb-4 rounded-xl border border-border/60 bg-background/40 p-3">
          <div className="flex items-center justify-between gap-2">
            <div className="text-xs font-medium text-secondary-text">{t('priceHistory.thresholds')}</div>
            <Button variant="secondary" size="sm" onClick={restoreDefaultThresholds}>
              {t('priceHistory.autoTune.restoreDefault')}
            </Button>
          </div>
          <div className="mt-2 flex flex-wrap items-end gap-x-3 gap-y-2">
            {THRESHOLD_FIELDS.map((field) => (
              <ThresholdFieldInput
                key={field.key}
                field={field}
                value={thresholds[field.key]}
                onChange={handleThresholdChange}
              />
            ))}
          </div>
          <div className="my-3 h-px bg-border/40" aria-hidden />
          <div className="text-xs font-medium text-secondary-text">{t('priceHistory.compositeThresholds')}</div>
          <div className="mt-2 flex flex-wrap items-end gap-x-4 gap-y-2">
            <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
              {COMPOSITE_SCORE_FIELDS.map((field) => (
                <ThresholdFieldInput
                  key={field.key}
                  field={field}
                  value={thresholds[field.key]}
                  onChange={handleThresholdChange}
                />
              ))}
            </div>
            <span className="hidden h-9 w-px self-center bg-border/60 sm:block" aria-hidden />
            <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
              {COMPOSITE_MACD_FIELDS.map((field) => (
                <ThresholdFieldInput
                  key={field.key}
                  field={field}
                  value={thresholds[field.key]}
                  onChange={handleThresholdChange}
                />
              ))}
            </div>
            <span className="hidden h-9 w-px self-center bg-border/60 sm:block" aria-hidden />
            <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
              {COMPOSITE_REGIME_FIELDS.map((field) => (
                <ThresholdFieldInput
                  key={field.key}
                  field={field}
                  value={thresholds[field.key]}
                  onChange={handleThresholdChange}
                />
              ))}
            </div>
          </div>
          <div className="mt-2 flex flex-wrap items-end gap-x-4 gap-y-2">
            <span className="text-xs font-medium text-secondary-text">{t('priceHistory.extraFactorThresholds')}</span>
            <div className="flex flex-wrap items-end gap-x-3 gap-y-2">
              {EXTRA_FACTOR_FIELDS.map((field) => (
                <ThresholdFieldInput
                  key={field.key}
                  field={field}
                  value={thresholds[field.key]}
                  onChange={handleThresholdChange}
                />
              ))}
            </div>
          </div>
        </div>
        <div className="mb-4 rounded-xl border border-border/60 bg-background/40 p-3">
          <div className="text-xs font-medium text-secondary-text">{t('priceHistory.autoTune.title')}</div>
          <div className="mt-2 flex flex-wrap items-center gap-x-4 gap-y-2">
            <label className="flex items-center gap-1 text-xs text-secondary-text">
              <span>{t('priceHistory.autoTune.windowLabel')}</span>
              <input
                type="number"
                min="10"
                max="365"
                value={transactionWindowRaw}
                onChange={(event) => setTransactionWindowRaw(event.target.value)}
                onBlur={() => {
                  if (transactionWindowRaw.trim() === '') {
                    setTransactionWindowRaw(String(transactionWindow));
                    return;
                  }
                  const parsed = Number(transactionWindowRaw);
                  const clamped = Math.min(365, Math.max(10, isNaN(parsed) ? 90 : parsed));
                  setTransactionWindow(clamped);
                  setTransactionWindowRaw(String(clamped));
                }}
                className="w-16 rounded-md border border-border/70 bg-card px-2 py-1 text-xs text-foreground"
              />
              <span>D</span>
            </label>
            <label className="flex items-center gap-1 text-xs text-secondary-text">
              <span>{t('priceHistory.autoTune.history')}</span>
              <input
                type="number"
                min="3"
                max="20"
                value={autoTuneYearsRaw}
                onChange={(event) => setAutoTuneYearsRaw(event.target.value)}
                onBlur={() => {
                  if (autoTuneYearsRaw.trim() === '') {
                    setAutoTuneYearsRaw(String(autoTuneYears));
                    return;
                  }
                  const parsed = Number(autoTuneYearsRaw);
                  const clamped = Math.min(20, Math.max(3, isNaN(parsed) ? 10 : parsed));
                  setAutoTuneYears(clamped);
                  setAutoTuneYearsRaw(String(clamped));
                }}
                className="w-12 rounded-md border border-border/70 bg-card px-2 py-1 text-xs text-foreground"
              />
              <span>Y</span>
            </label>
            <label className="flex items-center gap-1 text-xs text-secondary-text">
              <span>{t('priceHistory.autoTune.testPeriod')}</span>
              <select
                value={autoTuneTestYears}
                onChange={(event) => setAutoTuneTestYears(Number(event.target.value))}
                className="rounded-md border border-border/70 bg-card px-1.5 py-1 text-xs text-foreground"
              >
                {AUTO_TUNE_TEST_YEAR_OPTIONS.map((years) => (
                  <option key={years} value={years}>
                    {years}{t('priceHistory.yearsSuffix')}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex items-center gap-1 text-xs text-secondary-text">
              <input
                type="checkbox"
                checked={fineTuneEnabled}
                onChange={(e) => setFineTuneEnabled(e.target.checked)}
                className="h-3 w-3"
              />
              <span>{t('priceHistory.autoTune.fineTune')}</span>
              <input
                type="number"
                min="60"
                max="3000"
                value={fineTuneDaysRaw}
                disabled={!fineTuneEnabled}
                onChange={(e) => setFineTuneDaysRaw(e.target.value)}
                onBlur={() => {
                  const parsed = Number(fineTuneDaysRaw);
                  const clamped = Math.min(3000, Math.max(60, isNaN(parsed) ? 360 : parsed));
                  setFineTuneDays(clamped);
                  setFineTuneDaysRaw(String(clamped));
                }}
                className="w-14 rounded-md border border-border/70 bg-card px-2 py-1 text-xs text-foreground disabled:opacity-40"
              />
              <span>D</span>
            </label>
            {presets.length > 0 ? (
              <select
                onChange={(e) => {
                  const preset = presets.find((p) => p.id === e.target.value);
                  if (preset) loadPreset(preset);
                  e.target.value = '';
                }}
                defaultValue=""
                className="rounded-md border border-border/70 bg-card px-1.5 py-1 text-xs text-foreground"
              >
                <option value="" disabled>
                  {t('priceHistory.autoTune.presets.loadPlaceholder')}
                </option>
                {presets.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.name}{hasCurrentMethodology(p.result) ? '' : ` · ${t('priceHistory.autoTune.presets.outdated')}`}
                  </option>
                ))}
              </select>
            ) : null}
            <Button variant="primary" size="sm" className="sm:ml-auto" onClick={() => void runAutoTune()} disabled={isTuning || !acesValid}>
              {isTuning ? t('priceHistory.autoTune.running') : t('priceHistory.autoTune.button')}
            </Button>
          </div>
        </div>
        <ACESSetup language={language} disabled={isTuning} onChange={(config, valid) => { setACESConfig(config); setACESValid(valid); }} />
        {isTuning && tuneProgressInfo ? (
          <div className="mt-2">
            <div className="mb-1 flex flex-wrap items-center justify-between gap-x-3 gap-y-0.5 text-xs text-secondary-text">
              <span>
                {tuneProgressInfo.stage === 'fetching'
                  ? t('priceHistory.autoTune.progress.fetching')
                  : tuneProgressInfo.stage === 'optimizing'
                    ? t('priceHistory.autoTune.progress.optimizing')
                    : t('priceHistory.autoTune.progress.fineTuning', {
                        current: String(tuneProgressInfo.fineTuneCurrent),
                        total: String(tuneProgressInfo.fineTuneTotal),
                      })}
              </span>
              <span className="tabular-nums">
                {tuneProgressInfo.percent}%
                {' · '}
                {t('priceHistory.autoTune.progress.elapsed', { seconds: String(tuneProgressInfo.elapsedSeconds) })}
                {' · '}
                {t('priceHistory.autoTune.progress.eta', { seconds: String(tuneProgressInfo.etaSeconds) })}
              </span>
            </div>
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-border/50">
              <div
                className="h-full rounded-full bg-primary transition-[width] duration-300 ease-linear"
                style={{ width: `${tuneProgressInfo.percent}%` }}
              />
            </div>
          </div>
        ) : null}
        </>
        </div>
      ) : null}

      {autoTuneResult ? (
        <div className="order-4 mb-4 rounded-xl border border-border/60 bg-background/40 p-3">
          {!isCurrentAutoTune ? (
            <p role="alert" className="mb-3 rounded-md border border-amber-500/40 bg-amber-500/10 p-2 text-xs text-amber-500">
              {t('priceHistory.autoTune.outdatedResult')}
            </p>
          ) : null}
          {isCurrentAutoTune && autoTuneResult.walkForward ? (
            <p className="mb-2 text-xs text-secondary-text">
              {t('priceHistory.autoTune.walkForward', { count: String(autoTuneResult.walkForward.folds.length) })}
            </p>
          ) : null}
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="text-sm font-semibold text-foreground">{t('priceHistory.autoTune.title')}</div>
            <div className="text-xs text-secondary-text">
              {autoTuneResult.history.bars} bars · {autoTuneResult.history.startDate} ~ {autoTuneResult.history.endDate}
              {' · '}{t('priceHistory.autoTune.windowLabel')} {autoTuneResult.windowDays}D
              {autoTuneResult.history.testYearsUsed != null
                ? ` · ${t('priceHistory.autoTune.testPeriod')} ${autoTuneResult.history.testYearsUsed}${t('priceHistory.yearsSuffix')}`
                : ''}
              {' · '}{t('priceHistory.autoTune.costNote', { cost: String(autoTuneResult.assumptions.costPctPerSide ?? '') })}
            </div>
          </div>
          <div className="mb-2 flex flex-wrap gap-x-4 gap-y-0.5 text-xs text-secondary-text">
            {(['train', 'validation', 'test'] as const).map((segment) => {
              const range = autoTuneResult.split[segment];
              if (!range) return null;
              return (
                <span key={segment}>
                  {t(`priceHistory.autoTune.split.${segment}` as UiTextKey)}: {range.startDate} ~ {range.endDate} ({range.bars})
                </span>
              );
            })}
          </div>
          {trainDomain && trainRangeDates ? (
            <div className="mb-3">
              <button
                type="button"
                onClick={() => setTrainRangeExpanded((prev) => !prev)}
                className="mb-1 flex w-full items-center justify-between text-xs text-secondary-text hover:text-foreground"
              >
                <span>{t('priceHistory.autoTune.trainRange')}</span>
                <span className="flex items-center gap-2">
                  <span className="tabular-nums">{trainRangeDates.start} ~ {trainRangeDates.end}</span>
                  <span className="text-[10px]">{trainRangeExpanded ? '▲' : '▼'}</span>
                </span>
              </button>
              {trainRangeExpanded ? (
                <div className="relative h-5">
                  <div className="pointer-events-none absolute inset-x-0 top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-border/70" />
                  <div
                    className="pointer-events-none absolute top-1/2 h-1.5 -translate-y-1/2 rounded-full bg-primary/40"
                    style={{
                      left: `${((trainRangePct?.[0] ?? 0) / TRAIN_RANGE_SCALE) * 100}%`,
                      width: `${(((trainRangePct?.[1] ?? TRAIN_RANGE_SCALE) - (trainRangePct?.[0] ?? 0)) / TRAIN_RANGE_SCALE) * 100}%`,
                    }}
                  />
                  <input
                    type="range"
                    min={0}
                    max={TRAIN_RANGE_SCALE}
                    value={trainRangePct?.[0] ?? 0}
                    onChange={(event) => handleTrainRangeChange('start', Number(event.target.value))}
                    aria-label={t('priceHistory.autoTune.trainRangeStart')}
                    className="pointer-events-none absolute inset-x-0 top-0 h-5 w-full appearance-none bg-transparent [&::-moz-range-thumb]:pointer-events-auto [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border [&::-moz-range-thumb]:border-primary/70 [&::-moz-range-thumb]:bg-card [&::-webkit-slider-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-primary/70 [&::-webkit-slider-thumb]:bg-card"
                  />
                  <input
                    type="range"
                    min={0}
                    max={TRAIN_RANGE_SCALE}
                    value={trainRangePct?.[1] ?? TRAIN_RANGE_SCALE}
                    onChange={(event) => handleTrainRangeChange('end', Number(event.target.value))}
                    aria-label={t('priceHistory.autoTune.trainRangeEnd')}
                    className="pointer-events-none absolute inset-x-0 top-0 h-5 w-full appearance-none bg-transparent [&::-moz-range-thumb]:pointer-events-auto [&::-moz-range-thumb]:h-4 [&::-moz-range-thumb]:w-4 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border [&::-moz-range-thumb]:border-primary/70 [&::-moz-range-thumb]:bg-card [&::-webkit-slider-thumb]:pointer-events-auto [&::-webkit-slider-thumb]:h-4 [&::-webkit-slider-thumb]:w-4 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-primary/70 [&::-webkit-slider-thumb]:bg-card"
                  />
                </div>
              ) : null}
            </div>
          ) : null}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-xs">
              <thead>
                <tr className="border-b border-border/60 text-secondary-text">
                  <th className="py-1 pr-2 font-medium">{t('priceHistory.autoTune.strategy')}</th>
                  <th className="py-1 pr-2 font-medium">CAGR</th>
                  <th className="py-1 pr-2 font-medium">{t('priceHistory.autoTune.colAfterTaxCagr')}</th>
                  <th className="py-1 pr-2 font-medium">Sharpe</th>
                  <th className="py-1 pr-2 font-medium">Max DD</th>
                  <th className="py-1 pr-2 font-medium">PF</th>
                  <th className="py-1 pr-2 font-medium">{t('priceHistory.autoTune.trades')}</th>
                  <th className="py-1 pr-2 font-medium">{t('priceHistory.autoTune.avgTrade')}</th>
                  <th className="py-1 font-medium">{t('priceHistory.autoTune.oos')}</th>
                </tr>
              </thead>
              <tbody>
                {autoTuneResult.strategies.map((strategy: AutoTuneStrategyResult, index: number) => {
                  const tv = strategy.metrics.trainValidation;
                  const test = strategy.metrics.test;
                  const recommended = strategy.key === autoTuneResult.recommended.strategyKey;
                  const selected = strategy.key === selectedAutoTuneKey;
                  return (
                    <tr
                      key={strategy.key}
                      tabIndex={0}
                      aria-selected={selected}
                      onClick={() => setSelectedStrategyKey(strategy.key)}
                      onKeyDown={(event) => handleStrategyRowKeyDown(event, index)}
                      className={`cursor-pointer border-b border-border/40 outline-none transition-colors focus-visible:ring-1 focus-visible:ring-primary ${
                        selected ? 'bg-primary/10' : 'hover:bg-primary/5'
                      }`}
                    >
                      <td className="py-1 pr-2">
                        <span className={`font-semibold ${selected ? 'text-primary' : 'text-foreground'}`}>
                          {(language === 'zh' ? strategy.nameZh : strategy.nameEn) || strategy.key}
                        </span>
                        {recommended ? (
                          <span className="ml-1 text-[10px] text-primary">{t('priceHistory.autoTune.recommendedTag')}</span>
                        ) : null}
                        {!strategy.tuned ? (
                          <span className="ml-1 text-[10px] text-secondary-text">{t('priceHistory.autoTune.baselineTag')}</span>
                        ) : null}
                      </td>
                      <td className="py-1 pr-2 tabular-nums text-foreground">{formatAutoTuneValue(tv?.cagrPct)}%</td>
                      <td className="py-1 pr-2 tabular-nums text-foreground">{formatAutoTuneValue(tv?.afterTaxCagrPct)}%</td>
                      <td className="py-1 pr-2 tabular-nums text-foreground">{formatAutoTuneValue(tv?.sharpe)}</td>
                      <td className="py-1 pr-2 tabular-nums text-foreground">{formatAutoTuneValue(tv?.maxDrawdownPct)}%</td>
                      <td className="py-1 pr-2 tabular-nums text-foreground">{formatAutoTuneValue(tv?.profitFactor)}</td>
                      <td className="py-1 pr-2 tabular-nums text-foreground">{tv?.trades ?? '--'}</td>
                      <td className="py-1 pr-2 tabular-nums text-foreground">{formatAutoTuneValue(tv?.avgTradePct)}%</td>
                      <td className="py-1 tabular-nums text-foreground">{formatAutoTuneValue(test?.cagrPct)}%</td>
                    </tr>
                  );
                })}
                {autoTuneResult.benchmarks.map((benchmark: AutoTuneBenchmark) => {
                  const tv = benchmark.metrics.trainValidation;
                  const test = benchmark.metrics.test;
                  return (
                    <tr key={benchmark.key} className="border-b border-border/40 last:border-b-0">
                      <td className="py-1 pr-2">
                        <span className="text-secondary-text">
                          {(language === 'zh' ? benchmark.nameZh : benchmark.nameEn) || benchmark.key}
                        </span>
                        <span className="ml-1 text-[10px] text-secondary-text">{t('priceHistory.autoTune.benchmarkTag')}</span>
                      </td>
                      <td className="py-1 pr-2 tabular-nums text-secondary-text">{formatAutoTuneValue(tv?.cagrPct)}%</td>
                      <td className="py-1 pr-2 tabular-nums text-secondary-text">{formatAutoTuneValue(tv?.afterTaxCagrPct)}%</td>
                      <td className="py-1 pr-2 tabular-nums text-secondary-text">{formatAutoTuneValue(tv?.sharpe)}</td>
                      <td className="py-1 pr-2 tabular-nums text-secondary-text">{formatAutoTuneValue(tv?.maxDrawdownPct)}%</td>
                      <td className="py-1 pr-2 tabular-nums text-secondary-text">{formatAutoTuneValue(tv?.profitFactor)}</td>
                      <td className="py-1 pr-2 tabular-nums text-secondary-text">{tv?.trades ?? '--'}</td>
                      <td className="py-1 pr-2 tabular-nums text-secondary-text">{formatAutoTuneValue(tv?.avgTradePct)}%</td>
                      <td className="py-1 tabular-nums text-secondary-text">{formatAutoTuneValue(test?.cagrPct)}%</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <div className="mt-1 text-[11px] text-secondary-text">
            {t('priceHistory.autoTune.taxNote', {
              long: String(autoTuneResult.assumptions.capitalGainsTaxLongTermPct ?? ''),
              short: String(autoTuneResult.assumptions.capitalGainsTaxShortTermPct ?? ''),
            })}
          </div>
          <AutoTuneBudgetLedger decisions={selectedAutoTuneStrategy?.testDecisions} language={language} />
          <AutoTuneAllocationPanel report={autoTuneResult.allocation} language={language} onApplyThresholds={isCurrentAutoTune ? applyJointThresholds : undefined} />
          <ACESResults report={autoTuneResult.aces} language={language} />
          {autoTuneEquityPlot ? (
            <div className="mt-3">
              <div className="mb-1 text-xs font-medium text-secondary-text">
                {t('priceHistory.autoTune.cumulativeTitle')}
              </div>
              <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                {autoTuneEquityPlot.seriesList.map((series) => {
                  const isSelected = series.key === selectedAutoTuneKey;
                  const lastValue = series.values[series.values.length - 1];
                  return (
                    <span
                      key={series.key}
                      className={`flex items-center gap-1.5 ${isSelected ? 'font-semibold text-foreground' : 'text-secondary-text'}`}
                    >
                      <span
                        className="inline-block h-0.5 w-5"
                        style={{
                          background: series.dashed ? 'transparent' : series.color,
                          backgroundImage: series.dashed
                            ? `repeating-linear-gradient(to right, ${series.color} 0 4px, transparent 4px 7px)`
                            : undefined,
                        }}
                      />
                      {series.label}
                      {typeof lastValue === 'number' && Number.isFinite(lastValue) ? (
                        <span className={`tabular-nums ${lastValue >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                          {formatEquityPct(lastValue)}
                        </span>
                      ) : null}
                    </span>
                  );
                })}
              </div>
              <div className="relative">
                <svg
                  width={autoTuneEquityPlot.width}
                  viewBox={`0 0 ${autoTuneEquityPlot.width} 160`}
                  role="img"
                  aria-label={t('priceHistory.autoTune.cumulativeTitle')}
                  className="block h-40 w-full"
                  onMouseMove={(event) => {
                    const rect = event.currentTarget.getBoundingClientRect();
                    if (rect.width <= 0) return;
                    const px = ((event.clientX - rect.left) / rect.width) * autoTuneEquityPlot.width;
                    const ratio = (px - autoTuneEquityPlot.left) / Math.max(autoTuneEquityPlot.plotWidth, 1);
                    const index = Math.round(ratio * Math.max(autoTuneEquityPlot.refLength - 1, 0));
                    setEquityHoverIndex(index >= 0 && index < autoTuneEquityPlot.refLength ? index : null);
                  }}
                  onMouseLeave={() => setEquityHoverIndex(null)}
                >
                  {autoTuneEquityPlot.gridTicks.map((value) => (
                    <g key={`equity-tick-${value}`}>
                      <line
                        x1={autoTuneEquityPlot.left}
                        x2={autoTuneEquityPlot.width - autoTuneEquityPlot.right}
                        y1={autoTuneEquityPlot.y(value)}
                        y2={autoTuneEquityPlot.y(value)}
                        stroke="var(--border)"
                        strokeOpacity={Math.abs(value) < 1e-9 ? '0.6' : '0.35'}
                      />
                      <text
                        x={autoTuneEquityPlot.width - autoTuneEquityPlot.right + 6}
                        y={autoTuneEquityPlot.y(value) + 3}
                        fontSize="10"
                        fill="#ffffff"
                      >
                        {value}%
                      </text>
                    </g>
                  ))}
                  {equityHoverIndex !== null ? (
                    <line
                      x1={autoTuneEquityPlot.x(equityHoverIndex, autoTuneEquityPlot.refLength)}
                      x2={autoTuneEquityPlot.x(equityHoverIndex, autoTuneEquityPlot.refLength)}
                      y1={autoTuneEquityPlot.top}
                      y2={autoTuneEquityPlot.axisY}
                      stroke="var(--border)"
                      strokeOpacity="0.9"
                      strokeDasharray="3 3"
                    />
                  ) : null}
                  {autoTuneEquityPlot.dateTicks.map((tick, index) => (
                    <text
                      key={`equity-date-${index}`}
                      x={tick.x}
                      y={autoTuneEquityPlot.axisY + 12}
                      fontSize="10"
                      fill="#ffffff"
                      textAnchor={
                        index === 0 ? 'start' : index === autoTuneEquityPlot.dateTicks.length - 1 ? 'end' : 'middle'
                      }
                    >
                      {tick.label}
                    </text>
                  ))}
                  {autoTuneEquityPlot.seriesList.map((series) => {
                    const isSelected = series.key === selectedAutoTuneKey;
                    return (
                      <path
                        key={`equity-${series.key}`}
                        d={buildSmoothLinePath(
                          series.values,
                          (i) => autoTuneEquityPlot.x(i, series.values.length),
                          autoTuneEquityPlot.y,
                        )}
                        fill="none"
                        stroke={series.color}
                        strokeWidth={isSelected ? '3' : series.dashed ? '1.5' : '2'}
                        strokeDasharray={series.dashed ? '6 4' : undefined}
                        strokeLinejoin="round"
                        strokeLinecap="round"
                        opacity={isSelected ? '1' : series.dashed ? '0.7' : '0.85'}
                      />
                    );
                  })}
                  {equityHoverIndex !== null
                    ? autoTuneEquityPlot.seriesList.map((series) => {
                        const value = series.values[equityHoverIndex];
                        if (typeof value !== 'number' || !Number.isFinite(value)) return null;
                        return (
                          <circle
                            key={`equity-dot-${series.key}`}
                            cx={autoTuneEquityPlot.x(equityHoverIndex, series.values.length)}
                            cy={autoTuneEquityPlot.y(value)}
                            r={series.key === selectedAutoTuneKey ? 4 : 3}
                            fill={series.color}
                          />
                        );
                      })
                    : null}
                </svg>
                {equityHoverIndex !== null && autoTuneEquityPlot.dates[equityHoverIndex] ? (
                  <div
                    className="pointer-events-none absolute top-1 z-10 min-w-[150px] rounded-lg border border-border/70 bg-card/95 p-2 text-xs shadow-lg"
                    style={{
                      left: `${(autoTuneEquityPlot.x(equityHoverIndex, autoTuneEquityPlot.refLength) / autoTuneEquityPlot.width) * 100}%`,
                      transform:
                        equityHoverIndex > autoTuneEquityPlot.refLength * 0.55
                          ? 'translateX(calc(-100% - 10px))'
                          : 'translateX(10px)',
                    }}
                  >
                    <div className="mb-1 font-medium text-secondary-text">
                      {autoTuneEquityPlot.dates[equityHoverIndex]}
                    </div>
                    {autoTuneEquityPlot.seriesList.map((series) => {
                      const value = series.values[equityHoverIndex];
                      if (typeof value !== 'number' || !Number.isFinite(value)) return null;
                      return (
                        <div key={`equity-tip-${series.key}`} className="flex items-center gap-1.5 whitespace-nowrap">
                          <span className="inline-block h-2 w-2 shrink-0 rounded-full" style={{ background: series.color }} />
                          <span className="truncate text-secondary-text">{series.label}</span>
                          <span className={`ml-auto pl-2 font-medium tabular-nums ${value >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {formatEquityPct(value)}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                ) : null}
              </div>
            </div>
          ) : null}
          <div className="mt-2 text-xs text-secondary-text">
            {t('priceHistory.autoTune.recommended')}
            {': '}
            <span className="font-semibold text-foreground">
              {(language === 'zh'
                ? autoTuneResult.strategies.find((s) => s.key === autoTuneResult.recommended.strategyKey)?.nameZh
                : autoTuneResult.strategies.find((s) => s.key === autoTuneResult.recommended.strategyKey)?.nameEn)
                ?? autoTuneResult.recommended.strategyKey}
            </span>
            {' · '}
            {AUTO_TUNE_REASON_KEYS[autoTuneResult.recommended.reasonCode]
              ? t(AUTO_TUNE_REASON_KEYS[autoTuneResult.recommended.reasonCode] as UiTextKey)
              : autoTuneResult.recommended.reasonCode}
          </div>
          <div className="mt-2 text-xs text-secondary-text">
            {t('priceHistory.autoTune.selected')}
            {': '}
            <span className="font-semibold text-primary">
              {(language === 'zh' ? selectedAutoTuneStrategy?.nameZh : selectedAutoTuneStrategy?.nameEn)
                || selectedAutoTuneKey}
            </span>
          </div>
          {isCurrentAutoTune && selectedAutoTuneStrategy?.validationScore != null ? (
            <p className="mt-1 text-xs text-secondary-text">
              {t('priceHistory.autoTune.fineTune.validationScore')}: {formatAutoTuneValue(selectedAutoTuneStrategy.validationScore)}
              {' · '}{t('priceHistory.autoTune.validationDispersion')}: {formatAutoTuneValue(selectedAutoTuneStrategy.validationScoreDispersion)}
              {selectedAutoTuneStrategy.validationPositiveFolds != null ? (
                <span>{' · '}{t('priceHistory.autoTune.validationEvidence', {
                  positive: String(selectedAutoTuneStrategy.validationPositiveFolds),
                  total: String(selectedAutoTuneStrategy.validationFolds?.length ?? 0),
                  eligible: String(selectedAutoTuneStrategy.validationEligibleFolds ?? 0),
                  worst: formatAutoTuneValue(selectedAutoTuneStrategy.validationWorstCagrPct),
                })}</span>
              ) : null}
            </p>
          ) : null}
          {isCurrentAutoTune && selectedAutoTuneStrategy?.testConfidence ? (
            <TestConfidence confidence={selectedAutoTuneStrategy.testConfidence} />
          ) : null}
          <div className="mt-2 flex flex-wrap items-end gap-x-4 gap-y-2">
            {selectedParamDisplay.map((param) => (
              <label key={param.key} className="flex flex-col gap-0.5 text-xs text-secondary-text">
                <span>
                  {AUTO_TUNE_PARAM_LABEL_KEYS[param.key]
                    ? t(AUTO_TUNE_PARAM_LABEL_KEYS[param.key] as UiTextKey)
                    : param.key}
                </span>
                <span className="font-semibold tabular-nums text-foreground">
                  {formatAutoTuneValue(param.value)}
                  {typeof param.default === 'number' && param.default !== param.value ? (
                    <span className="ml-1 font-normal text-secondary-text">({formatAutoTuneValue(param.default)})</span>
                  ) : null}
                </span>
              </label>
            ))}
          </div>
          <div className="mt-2 flex flex-wrap items-center justify-between gap-2">
            <span className="text-xs text-secondary-text">{t('priceHistory.autoTune.fixedParams')}</span>
            <div className="flex flex-wrap gap-2">
              <Button variant="primary" size="sm" onClick={applyAutoTunedThresholds} disabled={!isCurrentAutoTune}>
                {t('priceHistory.autoTune.applySelected')}
              </Button>
            </div>
          </div>
          {/* Save preset / preset list */}
          <div className="mt-3 border-t border-border/40 pt-2">
            {showPresetInput ? (
              <div className="flex items-center gap-2">
                <input
                  type="text"
                  value={presetNameInput}
                  onChange={(e) => setPresetNameInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') savePreset();
                    if (e.key === 'Escape') { setShowPresetInput(false); setPresetNameInput(''); }
                  }}
                  placeholder={t('priceHistory.autoTune.presets.namePlaceholder')}
                  className="flex-1 rounded-md border border-border/70 bg-card px-2 py-1 text-xs text-foreground"
                  autoFocus
                />
                <Button variant="primary" size="sm" onClick={savePreset} disabled={!isCurrentAutoTune || !presetNameInput.trim()}>
                  {t('priceHistory.autoTune.presets.save')}
                </Button>
                <Button variant="secondary" size="sm" onClick={() => { setShowPresetInput(false); setPresetNameInput(''); }}>
                  {t('priceHistory.autoTune.presets.cancel')}
                </Button>
              </div>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <Button variant="secondary" size="sm" onClick={() => setShowPresetInput(true)} disabled={!isCurrentAutoTune}>
                  {t('priceHistory.autoTune.presets.saveAs')}
                </Button>
                {presets.length > 0 ? (
                  <span className="text-xs text-secondary-text">
                    {t('priceHistory.autoTune.presets.saved')}:
                  </span>
                ) : null}
                {presets.map((p) => (
                  <span
                    key={p.id}
                    className="inline-flex items-center gap-1 rounded-md border border-border/50 bg-card/60 px-2 py-0.5 text-xs text-foreground"
                  >
                    <button
                      type="button"
                      onClick={() => loadPreset(p)}
                      className="hover:text-primary"
                      title={t('priceHistory.autoTune.presets.loadTooltip')}
                    >
                      {p.name}{hasCurrentMethodology(p.result) ? '' : ` · ${t('priceHistory.autoTune.presets.outdated')}`}
                    </button>
                    <button
                      type="button"
                      onClick={() => deletePreset(p.id)}
                      className="ml-0.5 text-secondary-text hover:text-red-400"
                      title={t('priceHistory.autoTune.presets.deleteTooltip')}
                    >
                      ×
                    </button>
                  </span>
                ))}
              </div>
            )}
          </div>
          {/* Fine Tune sweep results */}
          {isCurrentAutoTune && autoTuneResult.fineTune && autoTuneResult.fineTune.sweep.length > 0 ? (
            <div className="mt-3 border-t border-border/40 pt-2">
              <div className="mb-1 text-xs font-medium text-secondary-text">
                {t('priceHistory.autoTune.fineTune.title')}
                {' · '}
                {autoTuneResult.fineTune.positionsTested} {t('priceHistory.autoTune.fineTune.position')}
                {' · '}
                {t('priceHistory.autoTune.fineTune.window')}: {autoTuneResult.fineTune.windowDays}D
              </div>
              <p className="mb-2 text-xs text-secondary-text">{t('priceHistory.autoTune.fineTune.selectionNote')}</p>
              <div className="text-xs text-secondary-text">{t('priceHistory.autoTune.fineTune.scoreTitle')}</div>
              <FineTuneSweepChart sweep={autoTuneResult.fineTune.sweep} bestIndex={autoTuneResult.fineTune.bestPositionIndex} />
              {autoTuneResult.fineTune.finalTest ? (
                <div className="mt-2 rounded-md border border-border/40 p-2 text-xs" data-testid="fine-tune-final-test">
                  <div className="font-medium text-foreground">
                    {t('priceHistory.autoTune.fineTune.finalTest')}
                    {' · #'}{autoTuneResult.fineTune.finalTest.positionIndex + 1}
                    {' · '}{autoTuneResult.fineTune.finalTest.strategyKey}
                  </div>
                  <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 tabular-nums text-secondary-text">
                    <span>CAGR: {formatAutoTuneValue(autoTuneResult.fineTune.finalTest.metrics.cagrPct)}%</span>
                    <span>Sharpe: {formatAutoTuneValue(autoTuneResult.fineTune.finalTest.metrics.sharpe)}</span>
                    <span>Max DD: {formatAutoTuneValue(autoTuneResult.fineTune.finalTest.metrics.maxDrawdownPct)}%</span>
                    <span>{t('priceHistory.autoTune.trades')}: {autoTuneResult.fineTune.finalTest.metrics.trades}</span>
                  </div>
                  <AutoTuneBudgetLedger decisions={autoTuneResult.fineTune.finalTest.decisions} language={language} />
                  <AutoTuneAllocationPanel report={autoTuneResult.fineTune.finalTest.allocation} language={language} onApplyThresholds={isCurrentAutoTune ? applyJointThresholds : undefined} />
                  {autoTuneResult.fineTune.finalTest.confidence ? (
                    <TestConfidence confidence={autoTuneResult.fineTune.finalTest.confidence} />
                  ) : null}
                </div>
              ) : null}
              {/* Sweep detail table (collapsed by default) */}
              <button
                type="button"
                onClick={() => setFineTuneTableExpanded((prev) => !prev)}
                className="mt-2 flex w-full items-center justify-between text-xs text-secondary-text hover:text-foreground"
              >
                <span>{t('priceHistory.autoTune.fineTune.detailToggle')}</span>
                <span className="text-[10px]">{fineTuneTableExpanded ? '▲' : '▼'}</span>
              </button>
              {fineTuneTableExpanded ? (
              <div className="mt-1 overflow-x-auto">
                <table className="w-full text-xs text-secondary-text">
                  <thead>
                    <tr className="border-b border-border/40">
                      <th className="px-2 py-1 text-left font-medium">#</th>
                      <th className="px-2 py-1 text-left font-medium">{t('priceHistory.autoTune.fineTune.trainRange')}</th>
                      <th className="px-2 py-1 text-left font-medium">{t('priceHistory.autoTune.fineTune.validationRange')}</th>
                      <th className="px-2 py-1 text-left font-medium">{t('priceHistory.autoTune.fineTune.strategy')}</th>
                      <th className="px-2 py-1 text-right font-medium">{t('priceHistory.autoTune.fineTune.validationScore')}</th>
                      <th className="px-2 py-1 text-right font-medium">{t('priceHistory.autoTune.fineTune.validationCagr')}</th>
                      <th className="px-2 py-1 text-right font-medium">{t('priceHistory.autoTune.fineTune.validationSharpe')}</th>
                      <th className="px-2 py-1 text-right font-medium">{t('priceHistory.autoTune.fineTune.validationMaxDd')}</th>
                      <th className="px-2 py-1 text-right font-medium">{t('priceHistory.autoTune.fineTune.validationTrades')}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {autoTuneResult.fineTune.sweep.map((pos) => {
                      const isBest = pos.positionIndex === autoTuneResult.fineTune!.bestPositionIndex;
                      const stratLabel = language === 'zh'
                        ? (pos.allStrategies.find((s) => s.key === pos.bestStrategyKey)?.nameZh ?? pos.bestStrategyKey)
                        : (pos.allStrategies.find((s) => s.key === pos.bestStrategyKey)?.nameEn ?? pos.bestStrategyKey);
                      return (
                        <tr
                          key={pos.positionIndex}
                          className={`border-b border-border/20 ${isBest ? 'bg-primary/10 font-semibold text-foreground' : ''}`}
                        >
                          <td className="px-2 py-1">
                            {pos.positionIndex + 1}
                            {isBest ? <span className="ml-1 text-primary">★</span> : null}
                          </td>
                          <td className="px-2 py-1">{pos.trainStart} ~ {pos.trainEnd} ({pos.trainBars}D)</td>
                          <td className="px-2 py-1">{pos.validationStart} ~ {pos.validationEnd}</td>
                          <td className="px-2 py-1">{stratLabel}</td>
                          <td className="px-2 py-1 text-right tabular-nums">{pos.validationScore.toFixed(2)}</td>
                          <td className={`px-2 py-1 text-right tabular-nums ${pos.validationCagr >= 0 ? 'text-emerald-400' : 'text-red-400'}`}>
                            {pos.validationCagr.toFixed(1)}%
                          </td>
                          <td className="px-2 py-1 text-right tabular-nums">{pos.validationSharpe.toFixed(2)}</td>
                          <td className="px-2 py-1 text-right tabular-nums text-red-400">{pos.validationMaxDd.toFixed(1)}%</td>
                          <td className="px-2 py-1 text-right tabular-nums">{pos.validationTrades}</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              ) : null}
            </div>
          ) : null}
        </div>
      ) : null}
      {autoTuneError ? (
        <div className="order-3 mb-4 rounded-xl border border-red-500/40 bg-red-500/10 p-3 text-xs text-red-400">
          {t('priceHistory.autoTune.error')}: {autoTuneError}
        </div>
      ) : null}

      <div className="order-1 mb-4 flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-secondary-text">{t('priceHistory.daysLabel')}</span>
        <div className="flex flex-wrap items-center gap-1.5">
          {DAY_OPTIONS.map((value) => (
            <button
              key={value}
              type="button"
              onClick={() => setDays(value)}
              className={`rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
                days === value
                  ? 'border-primary/50 bg-primary/10 text-primary'
                  : 'border-border/70 bg-background/50 text-secondary-text hover:bg-hover hover:text-foreground'
              }`}
            >
              {value % 365 === 0
                ? `${value / 365}${t('priceHistory.yearsSuffix')}`
                : `${value}${t('priceHistory.daysSuffix')}`}
            </button>
          ))}
        </div>
        <span className="mx-1 hidden h-4 w-px bg-border/60 sm:block" aria-hidden />
        <span className="text-xs font-medium text-secondary-text">{t('priceHistory.triggers')}</span>
        {TRIGGER_GROUPS.map(({ key, label, labelKey }) => (
          <button
            key={key}
            type="button"
            aria-pressed={visibleTriggers[key]}
            onClick={() => toggleTrigger(key)}
            className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
              visibleTriggers[key]
                ? 'border-primary/50 bg-primary/10 text-primary'
                : 'border-border/70 bg-background/50 text-muted-text hover:bg-hover hover:text-secondary-text'
            }`}
          >
            <span
              className={`inline-block h-2 w-2 rounded-full ${
                visibleTriggers[key] ? 'bg-primary' : 'bg-border'
              }`}
            />
            {labelKey ? t(labelKey) : label}
          </button>
        ))}
      </div>

      <div className="order-2">
      {isLoading && !result ? (
        <DashboardStateBlock loading title={t('priceHistory.loading')} />
      ) : error ? (
        <DashboardStateBlock
          title={t('priceHistory.loadFailed')}
          description={t('common.retry')}
          action={(
            <Button variant="secondary" size="sm" onClick={() => void load(days, thresholds)}>
              {t('priceHistory.retry')}
            </Button>
          )}
        />
      ) : !result || !geometry || result.dates.length === 0 ? (
        <DashboardStateBlock
          title={t('priceHistory.emptyTitle')}
          description={t('priceHistory.emptyDescription')}
        />
      ) : (
        <>
          <div ref={chartContainerRef} className="w-full overflow-x-auto">
            <svg
              width={geometry.width}
              viewBox={`0 0 ${geometry.width} ${PADDING.top + PLOT_HEIGHT + PADDING.bottom}`}
              role="img"
              aria-label={t('priceHistory.indicatorTitle')}
              className="block"
            >
              {geometry.ticks.map((tick, index) => (
                <g key={`tick-${index}`}>
                  <line
                    x1={PADDING.left}
                    x2={geometry.width - PADDING.right}
                    y1={tick.y}
                    y2={tick.y}
                    stroke="var(--border)"
                    strokeOpacity="0.3"
                  />
                  <text
                    x={geometry.width - PADDING.right + 6}
                    y={tick.y + 3.5}
                    fontSize="10"
                    fill="#ffffff"
                  >
                    {tick.value.toFixed(2)}
                  </text>
                </g>
              ))}

              {geometry.dateTicks.map((tick, index) => (
                <text
                  key={`date-${index}`}
                  x={tick.x}
                  y={PADDING.top + PLOT_HEIGHT + 18}
                  fontSize="10"
                  fill="#ffffff"
                  textAnchor={
                    index === 0 ? 'start' : index === geometry.dateTicks.length - 1 ? 'end' : 'middle'
                  }
                >
                  {tick.label}
                </text>
              ))}

              {bollBandPath ? (
                <path
                  d={bollBandPath}
                  fill={COLOR_BOLL_FILL}
                  fillOpacity="0.1"
                  stroke="none"
                />
              ) : null}

              {linePaths.map((line, index) => (
                <path
                  key={`line-${index}`}
                  d={line.d}
                  fill="none"
                  stroke={line.color}
                  strokeWidth={line.width}
                  strokeDasharray={line.dashed ? '2 3' : undefined}
                  strokeLinejoin="round"
                  strokeLinecap="round"
                />
              ))}

              {visibleTriggers.kdj ? markers?.kdjBuy.map((m) => renderMarker(m, 'square', BUY)) : null}
              {visibleTriggers.macd ? markers?.macdBuy.map((m) => renderMarker(m, 'circle', BUY, true)) : null}
              {visibleTriggers.obv ? markers?.obvBuy.map((m) => renderMarker(m, 'triangleUp', BUY)) : null}
              {visibleTriggers.rsi ? markers?.rsiBuy.map((m) => renderMarker(m, 'cross', BUY)) : null}
              {visibleTriggers.boll
                ? markers?.bollBuy.map((m) => renderMarker(m, EXTRA_GROUP_STYLES.boll.buyShape, BUY))
                : null}
              {visibleTriggers.cci
                ? markers?.cciBuy.map((m) => renderMarker(m, EXTRA_GROUP_STYLES.cci.buyShape, BUY))
                : null}
              {visibleTriggers.dmi
                ? markers?.dmiBuy.map((m) => renderMarker(m, EXTRA_GROUP_STYLES.dmi.buyShape, BUY))
                : null}
              {visibleTriggers.mfi
                ? markers?.mfiBuy.map((m) => renderMarker(m, EXTRA_GROUP_STYLES.mfi.buyShape, BUY))
                : null}
              {visibleTriggers.kdj ? markers?.kdjSell.map((m) => renderMarker(m, 'square', SELL)) : null}
              {visibleTriggers.macd ? markers?.macdSell.map((m) => renderMarker(m, 'circle', SELL, true)) : null}
              {visibleTriggers.obv ? markers?.obvSell.map((m) => renderMarker(m, 'triangleDown', SELL)) : null}
              {visibleTriggers.rsi ? markers?.rsiSell.map((m) => renderMarker(m, 'cross', SELL)) : null}
              {visibleTriggers.boll
                ? markers?.bollSell.map((m) => renderMarker(m, EXTRA_GROUP_STYLES.boll.sellShape, SELL))
                : null}
              {visibleTriggers.cci
                ? markers?.cciSell.map((m) => renderMarker(m, EXTRA_GROUP_STYLES.cci.sellShape, SELL))
                : null}
              {visibleTriggers.dmi
                ? markers?.dmiSell.map((m) => renderMarker(m, EXTRA_GROUP_STYLES.dmi.sellShape, SELL))
                : null}
              {visibleTriggers.mfi
                ? markers?.mfiSell.map((m) => renderMarker(m, EXTRA_GROUP_STYLES.mfi.sellShape, SELL))
                : null}

              {visibleTriggers.compositeBuy ? compositeMarkers?.buy.map(({ marker, score }) => renderCompositeMarker(marker, score, 'buy')) : null}
              {visibleTriggers.compositeSell ? compositeMarkers?.sell.map(({ marker, score }) => renderCompositeMarker(marker, score, 'sell')) : null}

              <rect
                x={PADDING.left}
                y={PADDING.top}
                width={geometry.width - PADDING.left - PADDING.right}
                height={PLOT_HEIGHT}
                fill="transparent"
                onMouseMove={(event) => {
                  const bounds = event.currentTarget.getBoundingClientRect();
                  const relativeX = ((event.clientX - bounds.left) / bounds.width)
                    * (geometry.width - PADDING.left - PADDING.right);
                  const index = Math.max(
                    0,
                    Math.min(geometry.n - 1, Math.round(relativeX / geometry.step)),
                  );
                  setHoveredIndex(index);
                }}
                onMouseLeave={() => setHoveredIndex(null)}
              />

              {hoveredPoint && typeof hoveredPoint.value === 'number' ? (() => {
                const tooltipWidth = 112;
                const tooltipX = Math.max(
                  PADDING.left,
                  Math.min(geometry.width - PADDING.right - tooltipWidth, hoveredPoint.x - tooltipWidth / 2),
                );
                const tooltipY = Math.max(PADDING.top + 4, hoveredPoint.y - 48);
                return (
                  <g pointerEvents="none">
                    <line
                      x1={hoveredPoint.x}
                      x2={hoveredPoint.x}
                      y1={PADDING.top}
                      y2={PADDING.top + PLOT_HEIGHT}
                      stroke="#ffffff"
                      strokeOpacity="0.45"
                      strokeDasharray="3 3"
                    />
                    <circle cx={hoveredPoint.x} cy={hoveredPoint.y} r="4" fill={COLOR_CLOSE} stroke="#ffffff" strokeWidth="1.5" />
                    <rect x={tooltipX} y={tooltipY} width={tooltipWidth} height="36" rx="5" fill="#111827" fillOpacity="0.95" stroke="#ffffff" strokeOpacity="0.25" />
                    <text x={tooltipX + 8} y={tooltipY + 14} fontSize="10" fill="#ffffff">
                      {hoveredPoint.date}
                    </text>
                    <text x={tooltipX + 8} y={tooltipY + 29} fontSize="11" fill="#ffffff" fontWeight="600">
                      {formatPrice(hoveredPoint.value)}
                    </text>
                  </g>
                );
              })() : null}
            </svg>
          </div>

          <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 text-xs text-secondary-text">
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-0.5 w-5" style={{ background: COLOR_CLOSE }} />
              {t('priceHistory.legend.close')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.macd ? '' : 'opacity-40'}`}>
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: BUY }} />
              {t('priceHistory.legend.macdBuy')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.macd ? '' : 'opacity-40'}`}>
              <span className="inline-block h-2.5 w-2.5 rounded-full" style={{ background: SELL }} />
              {t('priceHistory.legend.macdSell')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.obv ? '' : 'opacity-40'}`}>
              <span style={{ color: BUY }}>▲</span>
              {t('priceHistory.legend.obvBuy')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.obv ? '' : 'opacity-40'}`}>
              <span style={{ color: SELL }}>▼</span>
              {t('priceHistory.legend.obvSell')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.kdj ? '' : 'opacity-40'}`}>
              <span className="inline-block h-2.5 w-2.5" style={{ background: BUY }} />
              {t('priceHistory.legend.kdjBuy')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.kdj ? '' : 'opacity-40'}`}>
              <span className="inline-block h-2.5 w-2.5" style={{ background: SELL }} />
              {t('priceHistory.legend.kdjSell')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.rsi ? '' : 'opacity-40'}`}>
              <span style={{ color: BUY }}>✕</span>
              {t('priceHistory.legend.rsiBuy')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.rsi ? '' : 'opacity-40'}`}>
              <span style={{ color: SELL }}>✕</span>
              {t('priceHistory.legend.rsiSell')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.boll ? '' : 'opacity-40'}`}>
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: EXTRA_GROUP_STYLES.boll.buyColor }}
              />
              {t('priceHistory.legend.bollBuy')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.boll ? '' : 'opacity-40'}`}>
              <span
                className="inline-block h-2.5 w-2.5 rounded-full"
                style={{ background: EXTRA_GROUP_STYLES.boll.sellColor }}
              />
              {t('priceHistory.legend.bollSell')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.cci ? '' : 'opacity-40'}`}>
              <span className="inline-block h-2.5 w-2.5" style={{ background: EXTRA_GROUP_STYLES.cci.buyColor }} />
              {t('priceHistory.legend.cciBuy')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.cci ? '' : 'opacity-40'}`}>
              <span className="inline-block h-2.5 w-2.5" style={{ background: EXTRA_GROUP_STYLES.cci.sellColor }} />
              {t('priceHistory.legend.cciSell')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.dmi ? '' : 'opacity-40'}`}>
              <span style={{ color: EXTRA_GROUP_STYLES.dmi.buyColor }}>▲</span>
              {t('priceHistory.legend.dmiBuy')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.dmi ? '' : 'opacity-40'}`}>
              <span style={{ color: EXTRA_GROUP_STYLES.dmi.sellColor }}>▼</span>
              {t('priceHistory.legend.dmiSell')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.mfi ? '' : 'opacity-40'}`}>
              <span style={{ color: EXTRA_GROUP_STYLES.mfi.buyColor }}>✕</span>
              {t('priceHistory.legend.mfiBuy')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.mfi ? '' : 'opacity-40'}`}>
              <span style={{ color: EXTRA_GROUP_STYLES.mfi.sellColor }}>✕</span>
              {t('priceHistory.legend.mfiSell')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.compositeBuy ? '' : 'opacity-40'}`}>
              <span style={{ color: BUY }}>▲</span>
              {t('priceHistory.legend.compositeBuy')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.compositeSell ? '' : 'opacity-40'}`}>
              <span style={{ color: SELL }}>▼</span>
              {t('priceHistory.legend.compositeSell')}
            </span>
            {SMA_DOTTED.map(({ key, color }) => (
              <span key={`sma-legend-${key}`} className="flex items-center gap-1.5">
                <span className="inline-block h-0.5 w-5" style={{ background: color }} />
                SMA{key}
              </span>
            ))}
            <span className="flex items-center gap-1.5">
              <span className="inline-block h-0.5 w-5" style={{ background: COLOR_SMA200 }} />
              SMA200
            </span>
            <span className="ml-auto text-muted-text">
              {t('priceHistory.range')} {rangeLabel}
            </span>
          </div>

      {latestComposite ? (
        <div className="mt-3 rounded-xl border border-border/60 bg-background/40 p-3">
          <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs">
            <span className="font-semibold text-foreground">{t('priceHistory.compositeScore')}</span>
            <span className="font-semibold" style={{ color: BUY }}>
              {t('priceHistory.compositeBuy')}: {latestComposite.buyScore}/{latestComposite.maxBuyScore ?? 10}
            </span>
            <span className="font-semibold" style={{ color: SELL }}>
              {t('priceHistory.compositeSell')}: {latestComposite.sellScore}/{latestComposite.maxSellScore ?? 10}
            </span>
            <button
              type="button"
              onClick={() => setShowCompositeDebug((value) => !value)}
              className="rounded-lg border border-border/70 bg-background/50 px-2 py-1 text-xs font-medium text-secondary-text transition-colors hover:bg-hover hover:text-foreground"
            >
              {showCompositeDebug ? t('priceHistory.compositeHide') : t('priceHistory.compositeDetails')}
            </button>
          </div>
          {showCompositeDebug && latestComposite.buyBreakdown && latestComposite.sellBreakdown ? (
            <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
              {(['buy', 'sell'] as const).map((kind) => {
                const breakdown = kind === 'buy' ? latestComposite.buyBreakdown : latestComposite.sellBreakdown;
                const score = kind === 'buy' ? latestComposite.buyScore : latestComposite.sellScore;
                const color = kind === 'buy' ? BUY : SELL;
                return (
                  <div key={kind} className="rounded-lg border border-border/50 p-2 text-xs">
                    <div className="mb-1 font-semibold" style={{ color }}>
                      {kind === 'buy' ? t('priceHistory.compositeBuy') : t('priceHistory.compositeSell')}
                    </div>
                    {COMPOSITE_FACTOR_ROWS.map(({ key, labelKey }) => (
                      <div key={key} className="flex justify-between">
                        <span className="text-secondary-text">{t(labelKey as UiTextKey)}</span>
                        <span className="text-foreground">+{breakdown[key] ?? 0}</span>
                      </div>
                    ))}
                    <div className="mt-1 flex justify-between border-t border-border/50 pt-1 font-semibold text-foreground">
                      <span>{kind === 'buy' ? t('priceHistory.compositeBuy') : t('priceHistory.compositeSell')}</span>
                      <span>= {score}</span>
                    </div>
                  </div>
                );
              })}
            </div>
          ) : null}
        </div>
      ) : null}
        </>
      )}
      </div>
    </Card>
  );
};

export default StockIndicatorChart;
