import type React from 'react';
import { useCallback, useEffect, useRef, useState } from 'react';
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { stocksApi } from '../../api/stocks';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { formatUiText } from '../../i18n/uiText';
import { normalizeStockCode } from '../../utils/stockCode';
import type { ClosedSale, CurrentPosition } from '../../utils/currentPosition';
import {
  buildProfitSeries,
  type PositionHistoryResult,
  type ProfitPoint,
} from '../../utils/positionProfitSeries';
import { Button } from '../common';
import { DashboardStateBlock } from '../dashboard';

const HISTORY_DAY_OPTIONS = [30, 60, 90, 180, 365];

function positionKey(code: string): string {
  return normalizeStockCode(code).toUpperCase();
}

function formatProfitDate(value: string, days: number): string {
  if (days > 92) {
    return value.slice(0, 7);
  }
  return value.slice(5);
}

function formatProfit(value: number, language: 'zh' | 'en'): string {
  const formatted = value.toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return value > 0 ? `+${formatted}` : formatted;
}

interface CurrentPositionProfitChartProps {
  positions: CurrentPosition[];
  closedSales?: ClosedSale[];
}

export const CurrentPositionProfitChart: React.FC<CurrentPositionProfitChartProps> = ({ positions, closedSales = [] }) => {
  const { language, t } = useUiLanguage();
  const [days, setDays] = useState(30);
  const [data, setData] = useState<ProfitPoint[]>([]);
  const [isLoading, setIsLoading] = useState(true);
  const [hasError, setHasError] = useState(false);
  const requestSeqRef = useRef(0);

  const load = useCallback(async () => {
    const sequence = ++requestSeqRef.current;
    setIsLoading(true);
    setHasError(false);

    const codes = Array.from(new Map(
      positions.map((position) => [positionKey(position.code), position.code]),
    ).entries());
    const results: PositionHistoryResult[] = await Promise.all(codes.map(async ([key, code]) => {
      try {
        const response = await stocksApi.getHistory(code, { period: 'daily', days });
        return { key, data: response.data ?? [], failed: false };
      } catch {
        return { key, data: [], failed: true };
      }
    }));

    if (sequence !== requestSeqRef.current) return;
    setData(buildProfitSeries(positions, results, closedSales));
    setHasError(
      closedSales.length === 0 && results.length > 0 && results.every((result) => result.failed),
    );
    setIsLoading(false);
  }, [closedSales, days, positions]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void load();
    }, 0);
    return () => window.clearTimeout(timer);
  }, [load]);

  const latestProfit = data[data.length - 1]?.profit ?? 0;
  const lineColor = latestProfit >= 0 ? 'hsl(var(--success))' : 'hsl(var(--danger))';
  const realizedColor = 'hsl(var(--warning))';
  const hasRealized = data.some((point) => point.realized !== null);

  return (
    <section className="border-t border-subtle px-3 py-3 sm:px-4" data-testid="current-position-profit-chart">
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <div>
          <h3 className="text-sm font-medium text-foreground">{t('home.currentPositionsProfitTitle')}</h3>
          <p className="mt-1 text-[11px] text-muted-text">{t('home.currentPositionsProfitDescription')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-1.5" aria-label={t('home.currentPositionsProfitWindow')}>
          {HISTORY_DAY_OPTIONS.map((value) => (
            <Button
              key={value}
              type="button"
              variant={days === value ? 'outline' : 'ghost'}
              size="xsm"
              className="h-7 px-2 text-[11px]"
              onClick={() => setDays(value)}
              aria-pressed={days === value}
            >
              {value}{t('priceHistory.daysSuffix')}
            </Button>
          ))}
        </div>
      </div>
      {isLoading ? (
        <DashboardStateBlock compact loading title={t('home.currentPositionsProfitLoading')} />
      ) : hasError || data.length === 0 ? (
        <DashboardStateBlock
          compact
          title={hasError ? t('home.currentPositionsProfitUnavailable') : t('home.currentPositionsProfitEmpty')}
          action={hasError ? (
            <Button type="button" variant="ghost" size="xsm" onClick={() => void load()}>
              {t('common.retry')}
            </Button>
          ) : undefined}
        />
      ) : (
        <div className="h-60 w-full min-w-0">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={data} margin={{ top: 8, right: 12, bottom: 4, left: 4 }}>
              <CartesianGrid stroke="hsl(var(--border) / 0.35)" strokeDasharray="3 3" />
              <XAxis
                dataKey="date"
                tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 10 }}
                tickFormatter={(value: string) => formatProfitDate(value, days)}
                minTickGap={days > 92 ? 48 : 24}
              />
              <YAxis
                yAxisId="unrealized"
                tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 10 }}
                tickFormatter={(value: number) => formatProfit(value, language)}
                width={64}
              />
              {hasRealized ? (
                <YAxis
                  yAxisId="realized"
                  orientation="right"
                  tick={{ fill: 'hsl(var(--muted-foreground))', fontSize: 10 }}
                  tickFormatter={(value: number) => formatProfit(value, language)}
                  width={64}
                />
              ) : null}
              <Tooltip
                labelFormatter={(value) => value}
                formatter={(value, name) => [
                  formatProfit(Number(value), language),
                  name === 'realized'
                    ? t('home.currentPositionsProfitRealized')
                    : t('home.currentPositionsProfitAmount'),
                ]}
              />
              <ReferenceLine y={0} yAxisId="unrealized" stroke="hsl(var(--muted-foreground) / 0.5)" />
              <Line yAxisId="unrealized" type="monotone" dataKey="profit" stroke={lineColor} strokeWidth={2} dot={false} isAnimationActive={false} />
              {hasRealized ? (
                <Line yAxisId="realized" type="monotone" dataKey="realized" stroke={realizedColor} strokeWidth={2} strokeDasharray="5 3" dot={false} connectNulls isAnimationActive={false} />
              ) : null}
            </LineChart>
          </ResponsiveContainer>
        </div>
      )}
      {!isLoading && data.length > 0 ? (
        <p className="mt-2 text-right text-[11px] text-muted-text">
          {formatUiText(t('home.currentPositionsProfitRange'), { from: data[0].date, to: data[data.length - 1].date })}
        </p>
      ) : null}
    </section>
  );
};

export default CurrentPositionProfitChart;
