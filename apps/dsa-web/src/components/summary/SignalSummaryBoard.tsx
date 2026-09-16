import type React from 'react';
import { cn } from '../../utils/cn';
import { areStockCodesEquivalent } from '../../utils/stockCode';
import type { CompositeSummaryEntry } from '../../utils/compositeSummary';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Button } from '../common';
import { DashboardPanelHeader, DashboardStateBlock } from '../dashboard';
import { CurrentPositionTable } from './CurrentPositionTable';
import { getSummaryStockStyle } from './summaryStockStyle';

interface SignalSummaryBoardProps {
  className?: string;
  entries: CompositeSummaryEntry[];
  isLoading: boolean;
  signalsUnavailable: boolean;
  onRetry?: () => void;
  onStockSelect: (entry: CompositeSummaryEntry) => void;
  selectedRecordId?: number | null;
  selectedStockCode?: string | null;
}

function formatTriggerPrice(value: number | null | undefined): string | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    return null;
  }
  return value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export const SignalSummaryBoard: React.FC<SignalSummaryBoardProps> = ({
  className,
  entries,
  isLoading,
  signalsUnavailable,
  onRetry,
  onStockSelect,
  selectedRecordId,
  selectedStockCode,
}) => {
  const { t } = useUiLanguage();
  // Stale-while-revalidate: threshold edits above trigger a background
  // refresh. Keep existing entries visible (same height, no page shift) and
  // show a subtle refreshing indicator instead of replacing everything with
  // a loading block.
  const showInitialLoading = isLoading && entries.length === 0;
  const isRefreshing = isLoading && entries.length > 0;

  return (
    <section
      data-testid="signal-summary-board"
      aria-label={t('home.summaryTitle')}
      aria-busy={isRefreshing || undefined}
      className={cn('glass-card mb-4 flex flex-col overflow-hidden', className)}
    >
      <div className="space-y-1 border-b border-subtle px-3 py-2.5 sm:px-4">
        <DashboardPanelHeader
          className="mb-0"
          title={t('home.summaryTitle')}
          titleClassName="text-sm font-medium"
          actions={(
            <span className="flex items-center gap-1.5 text-[11px] text-muted-text">
              {isRefreshing ? (
                <span
                  role="status"
                  aria-label={t('common.loading')}
                  className="inline-block h-3 w-3 animate-spin rounded-full border border-current border-t-transparent"
                />
              ) : null}
              <span>
                {t('common.itemsCount', { count: entries.length })}
              </span>
            </span>
          )}
        />
        <p className="text-[11px] leading-relaxed text-muted-text">{t('home.summaryDescription')}</p>
      </div>
      {signalsUnavailable ? (
        <div className="flex items-center gap-2 border-b border-subtle px-3 py-1.5 text-[11px] text-muted-text sm:px-4">
          <span className="flex-1">{t('home.summarySignalsUnavailable')}</span>
          {onRetry ? (
            <Button type="button" variant="ghost" size="xsm" className="h-6" onClick={onRetry}>
              {t('common.retry')}
            </Button>
          ) : null}
        </div>
      ) : null}
      {showInitialLoading ? (
        <DashboardStateBlock
          compact
          loading
          className="px-4 py-6"
          title={t('common.loading')}
        />
      ) : entries.length === 0 ? (
        <DashboardStateBlock
          compact
          className="px-4 py-6"
          title={t('home.summaryEmptyTitle')}
          description={t('home.summaryEmptyDescription')}
        />
      ) : (
        <div
          className={cn(
            'flex flex-wrap gap-2 px-3 py-3 sm:px-4',
            isRefreshing && 'opacity-70 transition-opacity',
          )}
          data-testid="signal-summary-items"
        >
          {entries.map((entry) => {
            const isSelected =
              (typeof selectedRecordId === 'number' && entry.recordId === selectedRecordId) ||
              (typeof selectedStockCode === 'string' &&
                selectedStockCode.length > 0 &&
                areStockCodesEquivalent(entry.code, selectedStockCode));
            // Every summary item links to its real-time price chart (StockIndicatorChart),
            // even when no analysis report exists yet. The board's trigger data already
            // comes from the live indicators API, and the chart lets users verify the
            // latest 7-day / 3-day composite trigger visually.
            const ariaLabel = t('home.summaryOpenChartAria', { code: entry.code });
            const activeSide = entry.tone === 'buy' || entry.tone === 'sell' ? entry.tone : entry.triggerSide ?? null;
            const windowLabel = entry.intensity === 'strong'
              ? t('home.summaryTriggerStrong')
              : entry.intensity === 'light'
                ? t('home.summaryTriggerLight')
                : entry.triggerDate
                  ? t('home.summaryTriggerStale')
                  : null;
            const sideLabel = activeSide === 'buy'
              ? t('home.summaryTriggerSideBuy')
              : activeSide === 'sell'
                ? t('home.summaryTriggerSideSell')
                : null;
            const priceLabel = formatTriggerPrice(entry.triggerPrice);
            const triggerTitle = sideLabel && entry.triggerDate
              ? `${sideLabel} · ${entry.triggerDate}${priceLabel ? ` @ ${priceLabel}` : ''}${windowLabel ? ` · ${windowLabel}` : ''}`
              : t('home.summaryTriggerNone');
            return (
              <button
                key={entry.code}
                type="button"
                onClick={() => {
                  onStockSelect(entry);
                }}
                aria-label={ariaLabel}
                title={triggerTitle}
                style={getSummaryStockStyle(entry)}
                className={cn(
                  'home-history-item w-fit min-w-0 shrink-0 text-left',
                  isSelected ? 'home-history-item-selected' : '',
                )}
              >
                <span className="relative z-10 block px-2.5 py-2 font-mono text-sm text-foreground">
                  {entry.code}
                </span>
              </button>
            );
          })}
        </div>
      )}
      <CurrentPositionTable entries={entries} />
    </section>
  );
};
