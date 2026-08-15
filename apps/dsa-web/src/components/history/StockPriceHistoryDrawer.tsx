import type React from 'react';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { stocksApi, type KLineData } from '../../api/stocks';
import { Button, Card } from '../common';
import { Drawer } from '../common/Drawer';
import { DashboardStateBlock } from '../dashboard';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { formatUiText, type UiTextKey, type UiTextParams } from '../../i18n/uiText';

interface StockPriceHistoryDrawerProps {
  stockCode: string;
  stockName?: string;
  onClose: () => void;
}

const HISTORY_DAY_OPTIONS = [30, 60, 90, 180, 365];
const PLOT_HEIGHT = 300;
const VOLUME_HEIGHT = 60;
const PADDING = { top: 12, right: 66, bottom: 20, left: 10 };
const CANDLE_BODY_WIDTH = 6;
const CANDLE_STEP = 10;

const formatNumber = (value?: number | null, digits = 2): string =>
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '--';

const formatChangePct = (value?: number | null): string => {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return '--';
  }
  const sign = value > 0 ? '+' : '';
  return `${sign}${value.toFixed(2)}%`;
};

const formatCompactVolume = (value?: number | null): string => {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) {
    return '--';
  }
  if (value >= 100000000) return `${(value / 100000000).toFixed(2)}亿`;
  if (value >= 10000) return `${(value / 10000).toFixed(1)}万`;
  return Math.round(value).toString();
};

const isUp = (candle: KLineData): boolean => candle.close >= candle.open;

const chartColor = (up: boolean): string => `var(--home-price-${up ? 'up' : 'down'})`;

interface CandlestickChartProps {
  data: KLineData[];
  t: (key: UiTextKey, params?: UiTextParams) => string;
}

const CandlestickChart: React.FC<CandlestickChartProps> = ({ data, t }) => {
  const [hoveredIndex, setHoveredIndex] = useState<number | null>(null);

  const chartWidth = Math.max(720, data.length * CANDLE_STEP + PADDING.left + PADDING.right);
  const plotTop = PADDING.top;
  const plotHeight = PLOT_HEIGHT;
  const plotBottom = plotTop + plotHeight;
  const volumeTop = plotBottom + 12;
  const volumeHeight = VOLUME_HEIGHT;

  const scales = useMemo(() => {
    const lows = data.map((c) => c.low);
    const highs = data.map((c) => c.high);
    const minPrice = lows.length ? Math.min(...lows) : 0;
    const maxPrice = highs.length ? Math.max(...highs) : 0;
    const padding = (maxPrice - minPrice) * 0.08 || maxPrice * 0.01 || 1;
    const maxVolume = data.reduce((acc, c) => Math.max(acc, c.volume ?? 0), 0) || 1;

    const x = (index: number): number => PADDING.left + index * CANDLE_STEP + CANDLE_STEP / 2;
    const y = (value: number): number => plotTop + plotHeight - ((value - (minPrice - padding)) / ((maxPrice + padding) - (minPrice - padding))) * plotHeight;
    const volumeY = (value: number): number => volumeTop + volumeHeight - (value / maxVolume) * volumeHeight;

    const priceTicks = [minPrice, (minPrice + maxPrice) / 2, maxPrice].map((value, index) => ({
      value,
      y: plotTop + (plotHeight * index) / 2,
    }));

    return { x, y, volumeY, minPrice, maxPrice, maxVolume, priceTicks };
  }, [data, plotTop, plotHeight, volumeTop, volumeHeight]);

  const hoveredCandle = hoveredIndex !== null ? data[hoveredIndex] : null;
  const rangeLabel = data.length > 1 ? `${data[0].date} ~ ${data[data.length - 1].date}` : data[0]?.date ?? '--';

  const handleMove = useCallback((event: React.MouseEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = chartWidth / rect.width;
    const offsetX = (event.clientX - rect.left) * ratio - PADDING.left;
    const index = Math.floor(offsetX / CANDLE_STEP);
    if (index >= 0 && index < data.length) {
      setHoveredIndex(index);
    } else {
      setHoveredIndex(null);
    }
  }, [chartWidth, data.length]);

  return (
    <div className="overflow-x-auto">
      <svg
        width="100%"
        viewBox={`0 0 ${chartWidth} ${volumeTop + volumeHeight + PADDING.bottom}`}
        role="img"
        aria-label={t('priceHistory.title')}
        onMouseMove={handleMove}
        onMouseLeave={() => setHoveredIndex(null)}
        className="min-w-[600px]"
      >
        {/* Price gridlines */}
        {scales.priceTicks.map((tick, index) => (
          <g key={`grid-${index}`}>
            <line
              x1={PADDING.left}
              x2={chartWidth - PADDING.right}
              y1={tick.y}
              y2={tick.y}
              stroke="var(--border)"
              strokeOpacity="0.35"
              strokeDasharray="3 3"
            />
            <text
              x={chartWidth - PADDING.right + 6}
              y={tick.y + 3.5}
              fontSize="10"
              fill="var(--muted-foreground, var(--secondary-text))"
            >
              {tick.value.toFixed(2)}
            </text>
          </g>
        ))}

        {/* Candles */}
        {data.map((candle, index) => {
          const up = isUp(candle);
          const color = chartColor(up);
          const x = scales.x(index);
          const bodyTop = scales.y(Math.max(candle.open, candle.close));
          const bodyBottom = scales.y(Math.min(candle.open, candle.close));
          const bodyHeight = Math.max(1, bodyBottom - bodyTop);
          const volumeBarHeight = Math.max(1, volumeTop + volumeHeight - scales.volumeY(candle.volume ?? 0));
          const isHovered = hoveredIndex === index;
          return (
            <g key={`${candle.date}-${index}`}>
              <line
                x1={x}
                x2={x}
                y1={scales.y(candle.high)}
                y2={scales.y(candle.low)}
                stroke={color}
                strokeWidth={1}
              />
              <rect
                x={x - CANDLE_BODY_WIDTH / 2}
                y={bodyTop}
                width={CANDLE_BODY_WIDTH}
                height={bodyHeight}
                fill={color}
                rx={1}
                opacity={isHovered ? 1 : 0.92}
              />
              <rect
                x={x - CANDLE_STEP / 2 + 1}
                y={scales.volumeY(candle.volume ?? 0)}
                width={CANDLE_STEP - 2}
                height={volumeBarHeight}
                fill={color}
                opacity={0.45}
              />
            </g>
          );
        })}

        {/* Hover crosshair + tooltip */}
        {hoveredCandle && hoveredIndex !== null ? (
          <g>
            <line
              x1={scales.x(hoveredIndex)}
              x2={scales.x(hoveredIndex)}
              y1={plotTop}
              y2={volumeTop + volumeHeight}
              stroke="var(--primary)"
              strokeWidth={1}
              strokeDasharray="4 3"
            />
            <rect
              x={PADDING.left}
              y={plotTop + 4}
              width={156}
              height={132}
              rx={8}
              fill="var(--card)"
              stroke="var(--border)"
              strokeOpacity="0.6"
            />
            <text x={PADDING.left + 10} y={plotTop + 22} fontSize="11" fontWeight="600" fill="var(--foreground)">
              {hoveredCandle.date}
            </text>
            <text x={PADDING.left + 10} y={plotTop + 40} fontSize="10" fill="var(--secondary-text)">
              {t('priceHistory.open')} {formatNumber(hoveredCandle.open)}
            </text>
            <text x={PADDING.left + 10} y={plotTop + 56} fontSize="10" fill="var(--secondary-text)">
              {t('priceHistory.high')} {formatNumber(hoveredCandle.high)}
            </text>
            <text x={PADDING.left + 10} y={plotTop + 72} fontSize="10" fill="var(--secondary-text)">
              {t('priceHistory.low')} {formatNumber(hoveredCandle.low)}
            </text>
            <text x={PADDING.left + 10} y={plotTop + 88} fontSize="10" fill="var(--secondary-text)">
              {t('priceHistory.close')} {formatNumber(hoveredCandle.close)}
            </text>
            <text
              x={PADDING.left + 10}
              y={plotTop + 104}
              fontSize="10"
              fill={chartColor(isUp(hoveredCandle))}
            >
              {t('priceHistory.change')} {formatChangePct(hoveredCandle.changePercent)}
            </text>
            <text x={PADDING.left + 10} y={plotTop + 120} fontSize="10" fill="var(--secondary-text)">
              {t('priceHistory.volume')} {formatCompactVolume(hoveredCandle.volume)}
            </text>
          </g>
        ) : null}
      </svg>
      <p className="mt-2 text-right text-xs text-muted-text">
        {t('priceHistory.range')} {rangeLabel}
      </p>
    </div>
  );
};

interface PriceHistoryContentProps {
  stockCode: string;
  stockName?: string;
  onClose: () => void;
}

const PriceHistoryContent: React.FC<PriceHistoryContentProps> = ({ stockCode, stockName, onClose }) => {
  const { t } = useUiLanguage();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<KLineData[]>([]);
  const [stockNameResolved, setStockNameResolved] = useState<string | undefined>(stockName);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);
  const requestSeqRef = useRef(0);

  const load = useCallback(async (windowDays: number) => {
    const seq = ++requestSeqRef.current;
    setIsLoading(true);
    setError(null);
    try {
      const response = await stocksApi.getHistory(stockCode, { period: 'daily', days: windowDays });
      if (seq !== requestSeqRef.current) {
        return;
      }
      setData(response.data ?? []);
      setStockNameResolved(response.stockName || stockName);
    } catch (err) {
      if (seq !== requestSeqRef.current) {
        return;
      }
      setError(err);
    } finally {
      if (seq === requestSeqRef.current) {
        setIsLoading(false);
      }
    }
  }, [stockCode, stockName]);

  useEffect(() => {
    void load(days);
  }, [load, days]);

  const handleSelectDays = useCallback((value: number) => {
    setDays(value);
  }, []);

  const latest = data.length ? data[data.length - 1] : null;
  const latestUp = latest ? isUp(latest) : true;

  return (
    <div className="space-y-4 animate-fade-in">
      <Card variant="gradient" padding="md" className="home-panel-card">
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="flex items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-primary/12 text-primary">
              <svg className="h-5 w-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.8} d="M3 13.5V19a1 1 0 001 1h16a1 1 0 001-1v-5.5M3 13.5V5a1 1 0 011-1h16a1 1 0 011 1v8.5M3 13.5L8 8l4 4 3-3 6 6" />
              </svg>
            </div>
            <div>
              <h2 className="text-2xl font-bold text-foreground">{t('priceHistory.title')}</h2>
              <p className="mt-1 text-sm text-secondary-text">
                {stockNameResolved || stockCode} · {stockCode}
              </p>
            </div>
          </div>
          <Button variant="secondary" size="sm" onClick={onClose}>
            {t('priceHistory.backToCurrentReport')}
          </Button>
        </div>
      </Card>

      <Card variant="bordered" padding="md" className="home-panel-card">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-secondary-text">{t('priceHistory.daysLabel')}</span>
            <div className="flex flex-wrap items-center gap-1.5">
              {HISTORY_DAY_OPTIONS.map((value) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => handleSelectDays(value)}
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
          </div>
          <div className="text-right">
            <p className="text-xs text-secondary-text">{formatUiText(t('priceHistory.lastDays'), { days })}</p>
            {latest ? (
              <p className="mt-0.5 text-lg font-semibold tabular-nums" style={{ color: chartColor(latestUp) }}>
                {formatNumber(latest.close)}
                <span className="ml-2 text-sm font-normal">{formatChangePct(latest.changePercent)}</span>
              </p>
            ) : null}
          </div>
        </div>

        {isLoading ? (
          <DashboardStateBlock loading title={t('priceHistory.loading')} />
        ) : error ? (
          <DashboardStateBlock
            title={t('priceHistory.loadFailed')}
            description={t('common.retry')}
            action={(
              <Button variant="secondary" size="sm" onClick={() => void load(days)}>
                {t('priceHistory.retry')}
              </Button>
            )}
          />
        ) : data.length === 0 ? (
          <DashboardStateBlock
            title={t('priceHistory.emptyTitle')}
            description={t('priceHistory.emptyDescription')}
          />
        ) : (
          <CandlestickChart data={data} t={t} />
        )}
      </Card>
    </div>
  );
};

export const StockPriceHistoryDrawer: React.FC<StockPriceHistoryDrawerProps> = ({ stockCode, stockName, onClose }) => {
  const [isOpen, setIsOpen] = useState(true);

  const handleClose = useCallback(() => {
    setIsOpen(false);
    setTimeout(onClose, 300);
  }, [onClose]);

  return (
    <Drawer
      isOpen={isOpen}
      onClose={handleClose}
      title={`${stockName || ''} · ${stockCode}`}
      width="max-w-5xl"
      zIndex={110}
      backdropClassName="bg-background/56 backdrop-blur-[2px]"
    >
      <PriceHistoryContent stockCode={stockCode} stockName={stockName} onClose={handleClose} />
    </Drawer>
  );
};
