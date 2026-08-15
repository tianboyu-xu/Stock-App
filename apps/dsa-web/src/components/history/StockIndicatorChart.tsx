import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { stocksApi, type IndicatorThresholds, type StockIndicatorsResponse } from '../../api/stocks';
import { Button, Card } from '../common';
import { DashboardStateBlock } from '../dashboard';
import { useUiLanguage } from '../../contexts/UiLanguageContext';

const DAY_OPTIONS = [7, 14, 30, 60, 90, 180, 365];
type TuningTrigger = 'macd' | 'kdj' | 'rsi' | 'obv';
const BENEFIT_COLORS: Record<string, string> = {
  macd: '#38bdf8',
  kdj: '#f59e0b',
  rsi: '#a78bfa',
  obv: '#22c55e',
};

const PLOT_HEIGHT = 340;
const PADDING = { top: 16, right: 60, bottom: 40, left: 12 };
const DATE_TICK_COUNT = 5;

type TriggerGroupKey = 'macd' | 'obv' | 'kdj' | 'rsi';

const TRIGGER_GROUPS: Array<{ key: TriggerGroupKey; label: string }> = [
  { key: 'macd', label: 'MACD' },
  { key: 'obv', label: 'OBV' },
  { key: 'kdj', label: 'KDJ' },
  { key: 'rsi', label: 'RSI' },
];

// Series colors matching the reference image.
const COLOR_CLOSE = '#2f7de1';
const COLOR_SMA200 = '#d62728';

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
const THRESHOLD_STORAGE_PREFIX = 'dsa.indicator.thresholds.';

function thresholdStorageKey(stockCode: string): string {
  return `${THRESHOLD_STORAGE_PREFIX}${stockCode.trim().toUpperCase()}`;
}

function readStoredThresholds(stockCode: string): IndicatorThresholds | null {
  if (typeof window === 'undefined') {
    return null;
  }
  try {
    const rawValue = window.localStorage.getItem(thresholdStorageKey(stockCode));
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
    return parsed as IndicatorThresholds;
  } catch {
    return null;
  }
}

function writeStoredThresholds(stockCode: string, thresholds: IndicatorThresholds): void {
  if (typeof window === 'undefined') {
    return;
  }
  try {
    window.localStorage.setItem(thresholdStorageKey(stockCode), JSON.stringify(thresholds));
  } catch {
    // Local storage is best-effort; keep the in-memory values working.
  }
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
    | 'priceHistory.thresholdRsiSell';
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

// Smooth spline path closed down to a baseline, for area fills.
const buildSmoothAreaPath = (
  values: Array<number | null>,
  x: (i: number) => number,
  y: (v: number) => number,
  baselineY: number,
): string => {
  const points: Array<{ px: number; py: number }> = [];
  for (let i = 0; i < values.length; i += 1) {
    const v = values[i];
    if (typeof v === 'number' && Number.isFinite(v)) {
      points.push({ px: x(i), py: y(v) });
    }
  }
  if (points.length === 0) return '';
  if (points.length === 1) {
    return `M ${points[0].px} ${points[0].py} L ${points[0].px} ${baselineY} L ${points[0].px} ${points[0].py} Z`;
  }
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
  const first = points[0];
  const last = points[points.length - 1];
  d += ` L ${last.px} ${baselineY} L ${first.px} ${baselineY} Z`;
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

export interface StockIndicatorChartProps {
  stockCode: string;
  stockName?: string;
}

export const StockIndicatorChart: React.FC<StockIndicatorChartProps> = ({ stockCode, stockName }) => {
  const { t } = useUiLanguage();
  const [days, setDays] = useState(180);
  const [thresholds, setThresholds] = useState<IndicatorThresholds | null>(null);
  const [result, setResult] = useState<StockIndicatorsResponse | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);
  const [tuningTrigger, setTuningTrigger] = useState<TuningTrigger>('macd');
  const [transactionWindow, setTransactionWindow] = useState(90);
  const [isTuning, setIsTuning] = useState(false);
  const requestSeqRef = useRef(0);
  const chartContainerRef = useRef<HTMLDivElement | null>(null);
  const [containerWidth, setContainerWidth] = useState(0);
  const [visibleTriggers, setVisibleTriggers] = useState<Record<TriggerGroupKey, boolean>>({
    macd: true,
    obv: true,
    kdj: true,
    rsi: true,
  });

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
          setThresholds(response.thresholds);
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

  const applyThresholds = useCallback(() => {
    void load(days, thresholds);
  }, [load, days, thresholds]);

  const tuneThresholds = useCallback(async () => {
    setIsTuning(true);
    try {
      const response = await stocksApi.getIndicators(stockCode, {
        period: 'daily', days, optimize: true, trigger: tuningTrigger, transactionWindow,
      });
      setResult(response);
      setThresholds(response.thresholds);
      writeStoredThresholds(stockCode, response.thresholds);
    } finally {
      setIsTuning(false);
    }
  }, [days, stockCode, transactionWindow, tuningTrigger]);

  const toggleTrigger = useCallback((key: TriggerGroupKey) => {
    setTuningTrigger(key);
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

  const markers = useMemo(() => {
    if (!result) return null;
    return {
      macdBuy: collectMarkers(result.triggers.macdBuy),
      macdSell: collectMarkers(result.triggers.macdSell),
      obvBuy: collectMarkers(result.triggers.obvBuy),
      obvSell: collectMarkers(result.triggers.obvSell),
      kdjBuy: collectMarkers(result.triggers.kdjBuy),
      kdjSell: collectMarkers(result.triggers.kdjSell),
      rsiBuy: collectMarkers(result.triggers.rsiBuy),
      rsiSell: collectMarkers(result.triggers.rsiSell),
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

  return (
    <Card variant="bordered" padding="md" className="home-panel-card">
      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold text-foreground">{t('priceHistory.indicatorTitle')}</h2>
          <p className="mt-0.5 text-sm text-secondary-text">
            {stockName || result?.stockName || stockCode} · {stockCode}
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="text-xs text-secondary-text">{t('priceHistory.daysLabel')}</span>
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
                {value}
                {t('priceHistory.daysSuffix')}
              </button>
            ))}
          </div>
          <span className="ml-2 text-base font-semibold tabular-nums text-foreground">
            {formatPrice(latest)}
          </span>
        </div>
      </div>

      {thresholds ? (
        <div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-border/60 bg-background/40 p-3">
          <span className="text-xs font-medium text-secondary-text">{t('priceHistory.thresholds')}</span>
          {THRESHOLD_FIELDS.map(({ key, labelKey }) => (
            <label key={key} className="flex flex-col gap-1 text-xs text-secondary-text">
              <span>{t(labelKey)}</span>
              <input
                type="number"
                step="any"
                value={thresholds[key]}
                onChange={(event) => handleThresholdChange(key, event.target.value)}
                className="w-20 rounded-md border border-border/70 bg-card px-2 py-1 text-xs text-foreground focus:border-primary/50 focus:outline-none"
              />
            </label>
          ))}
          <Button variant="secondary" size="sm" onClick={applyThresholds}>
            {t('priceHistory.retry')}
          </Button>
          <label className="flex items-center gap-1 text-xs text-secondary-text">
            <span>Window</span>
            <input type="number" min="1" max="365" value={transactionWindow} onChange={(event) => setTransactionWindow(Math.max(1, Number(event.target.value) || 1))} className="w-16 rounded-md border border-border/70 bg-card px-2 py-1 text-xs text-foreground" />
            <span>D</span>
          </label>
          <Button variant="primary" size="sm" onClick={() => void tuneThresholds()} disabled={isTuning}>
            {isTuning ? 'Tuning…' : 'Auto tune'}
          </Button>
        </div>
      ) : null}

      <div className="mb-4 flex flex-wrap items-center gap-2">
        <span className="text-xs font-medium text-secondary-text">{t('priceHistory.triggers')}</span>
        {TRIGGER_GROUPS.map(({ key, label }) => (
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
            {label}
          </button>
        ))}
      </div>

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
              {visibleTriggers.kdj ? markers?.kdjSell.map((m) => renderMarker(m, 'square', SELL)) : null}
              {visibleTriggers.macd ? markers?.macdSell.map((m) => renderMarker(m, 'circle', SELL, true)) : null}
              {visibleTriggers.obv ? markers?.obvSell.map((m) => renderMarker(m, 'triangleDown', SELL)) : null}
              {visibleTriggers.rsi ? markers?.rsiSell.map((m) => renderMarker(m, 'cross', SELL)) : null}

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
              RSI {t('priceHistory.legend.macdBuy')}
            </span>
            <span className={`flex items-center gap-1.5 transition-opacity ${visibleTriggers.rsi ? '' : 'opacity-40'}`}>
              <span style={{ color: SELL }}>✕</span>
              RSI {t('priceHistory.legend.macdSell')}
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
          {result.benefitSeriesByTrigger && Object.keys(result.benefitSeriesByTrigger).length ? (
            <div className="mt-3">
              <div className="mb-1 flex items-center justify-between text-xs text-secondary-text">
                <span>Trigger benefit %</span>
                <span className="text-secondary-text">Window: {transactionWindow}D · Tune: {tuningTrigger.toUpperCase()}</span>
              </div>
              <div className="mb-2 flex flex-wrap gap-x-4 gap-y-1 text-xs">
                {Object.keys(result.benefitSeriesByTrigger).map((trigger) => (
                  <span key={trigger} className="flex items-center gap-1.5 text-secondary-text">
                    <span className="inline-block h-0.5 w-5" style={{ background: BENEFIT_COLORS[trigger] ?? '#ffffff' }} />
                    {trigger.toUpperCase()}
                    <span className="text-foreground">{(result.benefitByTrigger?.[trigger] ?? 0).toFixed(2)}%</span>
                  </span>
                ))}
              </div>
              <svg width={geometry.width} viewBox={`0 0 ${geometry.width} 104`} role="img" aria-label="Accumulated benefit percentage" className="block h-28 w-full">
                {[-30, 0, 30].map((value) => {
                  const py = 64 - Math.max(-30, Math.min(30, value)) * 0.8;
                  return (
                    <g key={`benefit-tick-${value}`}>
                      <line x1={PADDING.left} x2={geometry.width - PADDING.right} y1={py} y2={py} stroke="var(--border)" strokeOpacity="0.35" />
                      <text x={geometry.width - PADDING.right + 6} y={py + 3} fontSize="10" fill="#ffffff">
                        {value}%
                      </text>
                    </g>
                  );
                })}
                {geometry.dateTicks.map((tick, index) => (
                  <text
                    key={`benefit-date-${index}`}
                    x={tick.x}
                    y={92}
                    fontSize="10"
                    fill="#ffffff"
                    textAnchor={index === 0 ? 'start' : index === geometry.dateTicks.length - 1 ? 'end' : 'middle'}
                  >
                    {tick.label}
                  </text>
                ))}
                {Object.entries(result.benefitSeriesByTrigger).map(([trigger, series]) => {
                  const color = BENEFIT_COLORS[trigger] ?? '#ffffff';
                  const yMap = (value: number) => 64 - Math.max(-30, Math.min(30, value)) * 0.8;
                  return (
                    <g key={trigger}>
                      <path
                        d={buildSmoothAreaPath(series, geometry.x, yMap, 64)}
                        fill={color}
                        fillOpacity="0.18"
                        stroke="none"
                      />
                      <path
                        d={buildSmoothLinePath(series, geometry.x, yMap)}
                        fill="none"
                        stroke={color}
                        strokeWidth="2"
                        strokeLinejoin="round"
                        strokeLinecap="round"
                      />
                    </g>
                  );
                })}
              </svg>
            </div>
          ) : null}
        </>
      )}
    </Card>
  );
};

export default StockIndicatorChart;
