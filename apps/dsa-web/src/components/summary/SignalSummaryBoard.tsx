import type React from 'react';
import type { CSSProperties } from 'react';
import { cn } from '../../utils/cn';
import { areStockCodesEquivalent } from '../../utils/stockCode';
import type { CompositeSummaryEntry } from '../../utils/compositeSummary';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { Button } from '../common';
import { DashboardPanelHeader, DashboardStateBlock } from '../dashboard';

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

function stockBoxStyle(entry: CompositeSummaryEntry): CSSProperties | undefined {
  if (entry.tone === 'buy') {
    return entry.intensity === 'strong'
      ? { background: 'hsl(var(--success) / 0.35)' }
      : { background: 'hsl(var(--success) / 0.15)' };
  }
  if (entry.tone === 'sell') {
    return entry.intensity === 'strong'
      ? { background: 'hsl(var(--destructive) / 0.35)' }
      : { background: 'hsl(var(--destructive) / 0.15)' };
  }
  return undefined;
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

  return (
    <section
      data-testid="signal-summary-board"
      aria-label={t('home.summaryTitle')}
      className={cn('glass-card mb-4 flex flex-col overflow-hidden', className)}
    >
      <div className="space-y-1 border-b border-subtle px-3 py-2.5 sm:px-4">
        <DashboardPanelHeader
          className="mb-0"
          title={t('home.summaryTitle')}
          titleClassName="text-sm font-medium"
          actions={(
            <span className="text-[11px] text-muted-text">
              {t('common.itemsCount', { count: entries.length })}
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
      {isLoading ? (
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
        <div className="flex flex-wrap gap-2 px-3 py-3 sm:px-4" data-testid="signal-summary-items">
          {entries.map((entry) => {
            const isSelected =
              (typeof selectedRecordId === 'number' && entry.recordId === selectedRecordId) ||
              (typeof selectedStockCode === 'string' &&
                selectedStockCode.length > 0 &&
                areStockCodesEquivalent(entry.code, selectedStockCode));
            const canOpenDetail = typeof entry.recordId === 'number';
            const ariaLabel = canOpenDetail
              ? t('home.summaryOpenDetailAria', { code: entry.code })
              : t('home.summaryNoDetailAria', { code: entry.code });
            return (
              <button
                key={entry.code}
                type="button"
                onClick={() => {
                  if (canOpenDetail) {
                    onStockSelect(entry);
                  }
                }}
                disabled={!canOpenDetail}
                aria-label={ariaLabel}
                title={ariaLabel}
                style={stockBoxStyle(entry)}
                className={cn(
                  'home-history-item w-fit min-w-0 shrink-0 text-left',
                  isSelected ? 'home-history-item-selected' : '',
                  canOpenDetail ? '' : 'cursor-not-allowed',
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
    </section>
  );
};
