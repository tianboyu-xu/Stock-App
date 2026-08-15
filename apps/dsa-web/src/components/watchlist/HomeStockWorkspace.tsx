import { Fragment, useMemo, useState } from 'react';
import type React from 'react';
import {
  ArrowDownWideNarrow,
  CalendarDays,
  CheckCircle2,
  CircleAlert,
  Clock3,
  GripVertical,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Star,
  Trash2,
} from 'lucide-react';
import { Badge, Button, InlineAlert, Input, ScrollArea, StatusDot } from '../common';
import { DashboardPanelHeader, DashboardStateBlock } from '../dashboard';
import { StockBar } from '../history';
import type { StockBarItem, TaskInfo } from '../../types/analysis';
import { getSentimentColor } from '../../types/analysis';
import { buildDecisionActionLabelMap, getDecisionActionLabel } from '../../utils/decisionAction';
import { areStockCodesEquivalent } from '../../utils/stockCode';
import { truncateStockName } from '../../utils/stockName';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import type { UiTextKey, UiTextParams } from '../../i18n/uiText';

export type HomeWorkspaceTab = 'watchlist' | 'today' | 'history';
export type WatchlistAnalyzeMode = 'all' | 'pending';

export interface HomeWatchlistRow {
  code: string;
  latestItem?: StockBarItem;
  analyzedToday: boolean;
  isTodayStatusLoading?: boolean;
  isTodayStatusUnknown?: boolean;
  activeTask?: TaskInfo;
}

interface BatchStatus {
  variant: 'success' | 'warning' | 'danger';
  message: string;
}

interface HomeStockWorkspaceProps {
  activeTab: HomeWorkspaceTab;
  onTabChange: (tab: HomeWorkspaceTab) => void;
  watchlistRows: HomeWatchlistRow[];
  watchlistLoading: boolean;
  watchlistActioning: boolean;
  watchlistMessage: string | null;
  onAddToWatchlist: (code: string) => Promise<void>;
  onRemoveFromWatchlist: (code: string) => Promise<void>;
  onReorderWatchlist: (orderedCodes: string[]) => Promise<void>;
  onRefreshWatchlist: () => Promise<void>;
  onAnalyzeWatchlist: (mode: WatchlistAnalyzeMode) => Promise<void>;
  isBatchAnalyzing: boolean;
  batchStatus: BatchStatus | null;
  todayItems: StockBarItem[];
  isLoadingTodayItems: boolean;
  todayLoadError: boolean;
  watchlistAnalyzedTodayCount: number;
  historyItems: StockBarItem[];
  isLoadingHistory: boolean;
  selectedStockCode?: string;
  selectedRecordId?: number;
  onHistoryItemClick: (recordId: number) => void;
  onDeleteStock?: (stockCode: string) => Promise<void> | void;
  isDeleting?: boolean;
  className?: string;
}

function getTaskStatusLabel(task: TaskInfo | undefined, t: (key: UiTextKey, params?: UiTextParams) => string) {
  if (!task) return '';
  if (task.status === 'processing') return t('taskPanel.processing');
  if (task.status === 'pending') return t('taskPanel.pending');
  if (task.status === 'cancel_requested') return t('taskPanel.cancelRequested');
  return task.status;
}

const ScoreBadge: React.FC<{ item?: StockBarItem }> = ({ item }) => {
  const { t } = useUiLanguage();
  const score = typeof item?.sentimentScore === 'number' ? item.sentimentScore : null;
  const color = score !== null ? getSentimentColor(score) : null;
  if (score === null || !color) {
    return <span className="text-[11px] text-muted-text">{t('common.noData')}</span>;
  }

  const actionLabels = buildDecisionActionLabelMap(t);
  const operationLabel = getDecisionActionLabel(
    item?.action,
    item?.actionLabel,
    item?.operationAdvice,
    t('history.sentiment'),
    actionLabels,
  );

  return (
    <Badge
      variant="default"
      size="sm"
      className="shrink-0 shadow-none text-[11px] font-semibold leading-none"
      style={{
        color,
        borderColor: `${color}30`,
        backgroundColor: `${color}10`,
      }}
    >
      {operationLabel} {score}
    </Badge>
  );
};

const WatchlistRowItem: React.FC<{
  row: HomeWatchlistRow;
  onRemove: (code: string) => Promise<void>;
  onOpenDetail: (row: HomeWatchlistRow) => void;
  disabled: boolean;
  selected: boolean;
  isDragging: boolean;
  onDragStart: (code: string) => void;
  onDragOver: (code: string, position: 'before' | 'after') => void;
  onDrop: (targetCode: string, position: 'before' | 'after') => void;
  onDragEnd: () => void;
}> = ({
  row,
  onRemove,
  onOpenDetail,
  disabled,
  selected,
  isDragging,
  onDragStart,
  onDragOver,
  onDrop,
  onDragEnd,
}) => {
  const { t } = useUiLanguage();
  const taskLabel = getTaskStatusLabel(row.activeTask, t);
  const isLatestDetailLoading = Boolean(row.isTodayStatusLoading);
  const isLatestDetailUnavailable = !isLatestDetailLoading && Boolean(row.isTodayStatusUnknown);
  const item = isLatestDetailLoading || isLatestDetailUnavailable ? undefined : row.latestItem;
  const stockName = row.latestItem?.stockName || row.code;
  const canOpenDetail = typeof item?.id === 'number';

  const getDropPosition = (event: React.DragEvent<HTMLDivElement>): 'before' | 'after' => {
    const bounds = event.currentTarget.getBoundingClientRect();
    return event.clientY < bounds.top + bounds.height / 2 ? 'before' : 'after';
  };

  const handleOpenDetail = () => {
    onOpenDetail(row);
  };

  return (
    <div
      className={`home-subpanel group relative flex min-w-0 items-start gap-2 px-3 py-2.5 text-left transition-colors ${
        selected
          ? 'home-history-item-selected'
          : 'hover:border-subtle-hover hover:bg-base/65'
      } ${isDragging ? 'opacity-40' : ''}`}
      data-testid={`watchlist-row-${row.code}`}
      draggable={!disabled}
      onDragStart={(event) => {
        event.dataTransfer.effectAllowed = 'move';
        event.dataTransfer.setData('text/plain', row.code);
        onDragStart(row.code);
      }}
      onDragOver={(event) => {
        event.preventDefault();
        event.dataTransfer.dropEffect = 'move';
        onDragOver(row.code, getDropPosition(event));
      }}
      onDrop={(event) => {
        event.preventDefault();
        onDrop(row.code, getDropPosition(event));
      }}
      onDragEnd={onDragEnd}
    >
      <div
        className="flex shrink-0 cursor-grab items-center text-muted-text opacity-0 transition-opacity group-hover:opacity-100 active:cursor-grabbing"
        title={t('watchlist.dragHint')}
        aria-hidden="true"
      >
        <GripVertical className="h-4 w-4" />
      </div>
      <button
        type="button"
        aria-pressed={selected}
        aria-label={canOpenDetail
          ? t('watchlist.openLatestDetailAria', { code: row.code })
          : isLatestDetailLoading
            ? t('watchlist.latestDetailLoadingAria', { code: row.code })
            : isLatestDetailUnavailable
              ? t('watchlist.latestDetailUnavailableAria', { code: row.code })
            : t('watchlist.noLatestDetailAria', { code: row.code })}
        className="min-w-0 flex-1 cursor-pointer whitespace-normal rounded-lg text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-cyan/30"
        onClick={handleOpenDetail}
      >
        <div className="w-full min-w-0">
          <div className="flex min-w-0 items-center gap-2">
            <span className="truncate font-mono text-sm font-semibold text-foreground">
              {row.code}
            </span>
            {row.isTodayStatusLoading ? (
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-muted-text" aria-label={t('watchlist.todayStatusLoading')} />
            ) : row.isTodayStatusUnknown ? (
              <CircleAlert className="h-3.5 w-3.5 shrink-0 text-warning" aria-label={t('watchlist.todayStatusUnavailable')} />
            ) : row.analyzedToday ? (
              <CheckCircle2 className="h-3.5 w-3.5 shrink-0 text-success" aria-label={t('watchlist.analyzedToday')} />
            ) : (
              <Clock3 className="h-3.5 w-3.5 shrink-0 text-muted-text" aria-label={t('watchlist.notAnalyzedToday')} />
            )}
          </div>
          <div
            className="mt-1 block w-full min-w-0 max-w-full whitespace-normal break-words text-xs leading-snug text-secondary-text [overflow-wrap:anywhere] [word-break:break-word]"
            style={{ whiteSpace: 'normal', overflowWrap: 'anywhere', wordBreak: 'break-word' }}
          >
            {stockName}
          </div>
          {!canOpenDetail ? (
            <div className="flex min-w-0 items-center gap-2 text-[11px]">
              <span className={`truncate ${isLatestDetailLoading ? 'text-muted-text' : 'text-warning'}`}>
                {isLatestDetailLoading
                  ? t('watchlist.latestDetailLoadingCta')
                  : isLatestDetailUnavailable
                    ? t('watchlist.latestDetailUnavailableCta')
                    : t('watchlist.noLatestDetailCta')}
              </span>
            </div>
          ) : null}
          {row.activeTask ? (
            <div className="flex min-w-0 items-center gap-2 text-[11px] text-muted-text">
              <StatusDot
                tone={row.activeTask.status === 'processing' ? 'info' : 'neutral'}
                pulse={row.activeTask.status === 'processing'}
                className="h-1.5 w-1.5"
              />
              <span className="truncate">{t('watchlist.taskRunning', { status: taskLabel })}</span>
            </div>
          ) : null}
        </div>
      </button>
      <div className="absolute right-3 top-2.5 z-10 flex items-start gap-1.5">
        <ScoreBadge item={item} />
        <Button
          type="button"
          variant="ghost"
          size="xsm"
          className="h-7 w-7 px-0"
          disabled={disabled}
          aria-label={t('watchlist.removeAria', { code: row.code })}
          onClick={() => void onRemove(row.code)}
        >
          <Trash2 className="h-3.5 w-3.5 text-danger" aria-hidden="true" />
        </Button>
      </div>
    </div>
  );
};

const TodayItem: React.FC<{ item: StockBarItem; onClick: (recordId: number) => void }> = ({ item, onClick }) => {
  const stockName = item.stockName || item.stockCode;

  return (
    <button
      type="button"
      className="home-subpanel grid w-full min-w-0 grid-cols-[minmax(0,1fr)_auto] items-center gap-2 px-3 py-2.5 text-left"
      onClick={() => onClick(item.id)}
    >
      <div className="min-w-0">
        <span className="block truncate text-sm font-semibold text-foreground">
          {truncateStockName(stockName)}
        </span>
        <span className="mt-1 block truncate font-mono text-[11px] text-secondary-text">
          {item.stockCode}
        </span>
      </div>
      <ScoreBadge item={item} />
    </button>
  );
};

export const HomeStockWorkspace: React.FC<HomeStockWorkspaceProps> = ({
  activeTab,
  onTabChange,
  watchlistRows,
  watchlistLoading,
  watchlistActioning,
  watchlistMessage,
  onAddToWatchlist,
  onRemoveFromWatchlist,
  onReorderWatchlist,
  onRefreshWatchlist,
  onAnalyzeWatchlist,
  isBatchAnalyzing,
  batchStatus,
  todayItems,
  isLoadingTodayItems,
  todayLoadError,
  watchlistAnalyzedTodayCount,
  historyItems,
  isLoadingHistory,
  selectedStockCode,
  selectedRecordId,
  onHistoryItemClick,
  onDeleteStock,
  isDeleting = false,
  className = '',
}) => {
  const { t } = useUiLanguage();
  const [draftCode, setDraftCode] = useState('');
  const [workspaceNoticeCode, setWorkspaceNoticeCode] = useState<string | null>(null);
  const [dragCode, setDragCode] = useState<string | null>(null);
  const [dragInsertIndex, setDragInsertIndex] = useState<number | null>(null);
  const pendingWatchlistCount = watchlistRows
    .filter((row) => !row.analyzedToday && !row.isTodayStatusLoading && !row.isTodayStatusUnknown)
    .length;
  const isTodayStatusUnavailable = watchlistRows.some((row) => row.isTodayStatusLoading || row.isTodayStatusUnknown);
  const topTodayItem = todayItems[0];
  const tabs: Array<{ key: HomeWorkspaceTab; label: string }> = [
    { key: 'watchlist', label: t('watchlist.tabWatchlist') },
    { key: 'history', label: t('watchlist.tabHistory') },
    { key: 'today', label: t('watchlist.tabToday') },
  ];

  const statusClassName = useMemo(() => {
    if (!batchStatus) return '';
    if (batchStatus.variant === 'danger') return 'border-danger/30 bg-danger/10 text-danger';
    if (batchStatus.variant === 'warning') return 'border-warning/30 bg-warning/10 text-warning';
    return 'border-success/30 bg-success/10 text-success';
  }, [batchStatus]);

  const visibleWorkspaceNotice = useMemo(() => {
    if (!workspaceNoticeCode) return null;
    const row = watchlistRows.find((item) => areStockCodesEquivalent(item.code, workspaceNoticeCode));
    if (!row) return null;
    if (row.isTodayStatusLoading) {
      return { message: t('watchlist.latestDetailLoading') };
    }
    if (row.isTodayStatusUnknown) {
      return { message: t('watchlist.latestDetailUnavailable') };
    }
    if (row.latestItem) return null;
    return { message: t('watchlist.noLatestDetail') };
  }, [t, watchlistRows, workspaceNoticeCode]);

  const handleAddSubmit = (event: React.FormEvent) => {
    event.preventDefault();
    const code = draftCode.trim();
    if (!code) return;
    setWorkspaceNoticeCode(null);
    void onAddToWatchlist(code).then(() => setDraftCode(''));
  };

  const handleWatchlistRowOpen = (row: HomeWatchlistRow) => {
    if (row.isTodayStatusLoading || row.isTodayStatusUnknown) {
      setWorkspaceNoticeCode(row.code);
      return;
    }
    const recordId = row.latestItem?.id;
    if (typeof recordId === 'number') {
      setWorkspaceNoticeCode(null);
      onHistoryItemClick(recordId);
      return;
    }
    setWorkspaceNoticeCode(row.code);
  };

  const handleWatchlistDragStart = (code: string) => {
    setDragCode(code);
    setDragInsertIndex(null);
  };

  const handleWatchlistDragOver = (code: string, position: 'before' | 'after') => {
    const targetIndex = watchlistRows.findIndex((row) => areStockCodesEquivalent(row.code, code));
    if (targetIndex < 0) return;
    setDragInsertIndex(targetIndex + (position === 'after' ? 1 : 0));
  };

  const handleWatchlistDropAt = (insertIndex: number) => {
    const sourceCode = dragCode;
    setDragCode(null);
    setDragInsertIndex(null);
    if (!sourceCode) return;
    const codes = watchlistRows.map((row) => row.code);
    const sourceIndex = codes.findIndex((code) => areStockCodesEquivalent(code, sourceCode));
    if (sourceIndex < 0 || insertIndex < 0 || insertIndex > codes.length) return;
    const next = codes.filter((_, index) => index !== sourceIndex);
    const adjustedIndex = sourceIndex < insertIndex ? insertIndex - 1 : insertIndex;
    next.splice(adjustedIndex, 0, sourceCode);
    if (next.every((code, index) => code === codes[index])) return;
    void onReorderWatchlist(next);
  };

  const handleWatchlistDrop = (targetCode: string, position: 'before' | 'after') => {
    const targetIndex = watchlistRows.findIndex((row) => areStockCodesEquivalent(row.code, targetCode));
    if (targetIndex < 0) return;
    handleWatchlistDropAt(targetIndex + (position === 'after' ? 1 : 0));
  };

  const handleWatchlistDragEnd = () => {
    setDragCode(null);
    setDragInsertIndex(null);
  };

  const renderTabs = (
    <div className="grid grid-cols-3 gap-1 rounded-xl border border-subtle bg-base/40 p-1">
      {tabs.map((tab) => {
        const selected = activeTab === tab.key;
        return (
          <button
            key={tab.key}
            type="button"
            aria-pressed={selected}
            className={`h-8 rounded-lg px-2 text-xs font-medium transition-colors ${
              selected ? 'bg-primary/15 text-primary shadow-inner' : 'text-secondary-text hover:bg-hover hover:text-foreground'
            }`}
            onClick={() => {
              setWorkspaceNoticeCode(null);
              onTabChange(tab.key);
            }}
          >
            {tab.label}
          </button>
        );
      })}
    </div>
  );

  if (activeTab === 'history') {
    return (
      <div className={`flex min-h-0 flex-1 flex-col gap-2 ${className}`}>
        {renderTabs}
        <StockBar
          items={historyItems}
          isLoading={isLoadingHistory}
          selectedStockCode={selectedStockCode}
          selectedRecordId={selectedRecordId}
          onItemClick={onHistoryItemClick}
          onDeleteStock={onDeleteStock}
          isDeleting={isDeleting}
          className="flex-1 overflow-hidden"
        />
      </div>
    );
  }

  return (
    <aside className={`glass-card flex min-h-0 flex-1 flex-col overflow-hidden ${className}`}>
      <div className="space-y-2.5 border-b border-subtle px-3 py-3 sm:px-4">
        {renderTabs}

        {activeTab === 'watchlist' ? (
          <>
            <DashboardPanelHeader
              className="mb-0"
              title={t('watchlist.title')}
              titleClassName="text-sm font-medium"
              leading={<Star className="h-4 w-4 text-primary" aria-hidden="true" />}
              actions={(
                <div className="flex items-center gap-1.5">
                  <span className="text-[11px] text-muted-text">{t('common.itemsCount', { count: watchlistRows.length })}</span>
                  <Button
                    type="button"
                    variant="ghost"
                    size="xsm"
                    className="h-7 w-7 px-0"
                    disabled={watchlistLoading}
                    onClick={() => {
                      setWorkspaceNoticeCode(null);
                      void onRefreshWatchlist();
                    }}
                    aria-label={t('watchlist.refreshAria')}
                  >
                    <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" />
                  </Button>
                </div>
              )}
            />
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="default" className="gap-1 shadow-none text-[11px]">
                {t('watchlist.todayCoverage')} {watchlistAnalyzedTodayCount}/{watchlistRows.length}
              </Badge>
              <Badge variant="default" className="gap-1 shadow-none text-[11px]">
                {t('watchlist.pendingToday')} {pendingWatchlistCount}
              </Badge>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant="home-action-ai"
                className="h-8 flex-1 whitespace-nowrap px-2 text-xs sm:flex-none"
                disabled={watchlistRows.length === 0 || isBatchAnalyzing}
                isLoading={isBatchAnalyzing}
                loadingText={t('watchlist.submitting')}
                onClick={() => void onAnalyzeWatchlist('all')}
              >
                <Play className="h-4 w-4" aria-hidden="true" />
                {t('watchlist.analyzeAll')}
              </Button>
              <Button
                type="button"
                size="sm"
                variant="home-action-report"
                className="h-8 flex-1 whitespace-nowrap px-2 text-xs sm:flex-none"
                disabled={pendingWatchlistCount === 0 || isTodayStatusUnavailable || isBatchAnalyzing}
                onClick={() => void onAnalyzeWatchlist('pending')}
              >
                <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                {t('watchlist.analyzePending')}
              </Button>
            </div>
            <form className="grid grid-cols-[minmax(0,1fr)_auto] gap-2" onSubmit={handleAddSubmit}>
              <Input
                value={draftCode}
                onChange={(event) => setDraftCode(event.target.value)}
                placeholder={t('watchlist.addPlaceholder')}
                className="h-8 rounded-lg px-3 text-xs"
                disabled={watchlistActioning}
                aria-label={t('watchlist.addPlaceholder')}
              />
              <Button
                type="submit"
                size="sm"
                variant="secondary"
                className="h-8 w-8 px-0"
                disabled={!draftCode.trim() || watchlistActioning}
                isLoading={watchlistActioning}
                aria-label={t('watchlist.add')}
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
              </Button>
            </form>
            {batchStatus ? (
              <div className={`rounded-xl border px-3 py-2 text-xs ${statusClassName}`}>
                {batchStatus.message}
              </div>
            ) : null}
            {watchlistMessage ? (
              <div className="rounded-xl border border-subtle bg-base/35 px-3 py-2 text-xs text-secondary-text">
                {watchlistMessage}
              </div>
            ) : null}
            {visibleWorkspaceNotice ? (
              <InlineAlert
                variant="warning"
                message={visibleWorkspaceNotice.message}
                className="rounded-xl px-3 py-2 text-xs shadow-none"
              />
            ) : null}
          </>
        ) : (
          <>
            <DashboardPanelHeader
              className="mb-0"
              title={t('watchlist.todayTitle')}
              titleClassName="text-sm font-medium"
              leading={<CalendarDays className="h-4 w-4 text-cyan" aria-hidden="true" />}
              actions={<span className="text-[11px] text-muted-text">{t('common.itemsCount', { count: todayItems.length })}</span>}
            />
            <div className="flex flex-wrap gap-1.5">
              <Badge variant="default" className="gap-1 shadow-none text-[11px]">
                {t('watchlist.watchlistCoverage')} {watchlistAnalyzedTodayCount}/{watchlistRows.length}
              </Badge>
              <Badge variant="default" className="gap-1 shadow-none text-[11px]">
                {t('watchlist.topScore')} {topTodayItem?.sentimentScore ?? '-'}
              </Badge>
            </div>
          </>
        )}
      </div>

      <ScrollArea viewportClassName="px-3 py-3 sm:px-4" className="min-h-0 flex-1">
        {activeTab === 'watchlist' ? (
          watchlistLoading ? (
            <DashboardStateBlock loading compact title={t('watchlist.loading')} />
          ) : watchlistRows.length === 0 ? (
            <DashboardStateBlock
              compact
              title={t('watchlist.emptyTitle')}
              description={t('watchlist.emptyDescription')}
            />
          ) : (
            <div className="space-y-1.5">
              <div className="flex items-center gap-2 text-[11px] text-muted-text">
                <ArrowDownWideNarrow className="h-3.5 w-3.5" aria-hidden="true" />
                {t('watchlist.listHint')}
              </div>
              {watchlistRows.map((row, index) => {
                const isDragging = dragCode !== null && areStockCodesEquivalent(dragCode, row.code);
                const isInsertGap = dragCode !== null && dragInsertIndex === index;
                return (
                  <Fragment key={row.code}>
                    <div
                      data-testid={`watchlist-drop-gap-${index}`}
                      data-active={isInsertGap}
                      className={`flex items-center transition-all ${isInsertGap ? 'h-3' : 'pointer-events-none h-0 opacity-0'}`}
                      onDragOver={(event) => {
                        event.preventDefault();
                        event.dataTransfer.dropEffect = 'move';
                        setDragInsertIndex(index);
                      }}
                      onDrop={(event) => {
                        event.preventDefault();
                        handleWatchlistDropAt(index);
                      }}
                    >
                      <span className={`h-0.5 w-full rounded-full transition-colors ${isInsertGap ? 'bg-cyan shadow-[0_0_10px_rgba(34,211,238,0.7)]' : 'bg-transparent'}`} />
                    </div>
                    <WatchlistRowItem
                      row={row}
                      onRemove={async (code) => {
                        setWorkspaceNoticeCode(null);
                        await onRemoveFromWatchlist(code);
                      }}
                      onOpenDetail={handleWatchlistRowOpen}
                      disabled={watchlistActioning}
                      selected={
                        (typeof selectedRecordId === 'number' && selectedRecordId === row.latestItem?.id)
                        || (
                          Boolean(selectedStockCode)
                          && (
                            areStockCodesEquivalent(selectedStockCode ?? '', row.code)
                            || areStockCodesEquivalent(selectedStockCode ?? '', row.latestItem?.stockCode ?? '')
                          )
                        )
                      }
                      isDragging={isDragging}
                      onDragStart={handleWatchlistDragStart}
                      onDragOver={handleWatchlistDragOver}
                      onDrop={handleWatchlistDrop}
                      onDragEnd={handleWatchlistDragEnd}
                    />
                  </Fragment>
                );
              })}
              <div
                data-testid={`watchlist-drop-gap-${watchlistRows.length}`}
                data-active={dragCode !== null && dragInsertIndex === watchlistRows.length}
                className={`flex items-center transition-all ${dragCode !== null && dragInsertIndex === watchlistRows.length ? 'h-3' : 'pointer-events-none h-0 opacity-0'}`}
                onDragOver={(event) => {
                  event.preventDefault();
                  event.dataTransfer.dropEffect = 'move';
                  setDragInsertIndex(watchlistRows.length);
                }}
                onDrop={(event) => {
                  event.preventDefault();
                  handleWatchlistDropAt(watchlistRows.length);
                }}
              >
                <span className={`h-0.5 w-full rounded-full transition-colors ${dragCode !== null && dragInsertIndex === watchlistRows.length ? 'bg-cyan shadow-[0_0_10px_rgba(34,211,238,0.7)]' : 'bg-transparent'}`} />
              </div>
            </div>
          )
        ) : isLoadingTodayItems ? (
          <DashboardStateBlock loading compact title={t('watchlist.loading')} />
        ) : todayLoadError ? (
          <DashboardStateBlock
            compact
            title={t('watchlist.todayLoadErrorTitle')}
            description={t('watchlist.todayLoadErrorDescription')}
          />
        ) : todayItems.length === 0 ? (
          <DashboardStateBlock
            compact
            title={t('watchlist.todayEmptyTitle')}
            description={t('watchlist.todayEmptyDescription')}
          />
        ) : (
          <div className="space-y-2">
            <div className="flex items-center gap-2 text-[11px] text-muted-text">
              <ArrowDownWideNarrow className="h-3.5 w-3.5" aria-hidden="true" />
              {t('watchlist.todaySortHint')}
            </div>
            {todayItems.map((item) => (
              <TodayItem key={`${item.stockCode}-${item.id}`} item={item} onClick={onHistoryItemClick} />
            ))}
          </div>
        )}
      </ScrollArea>
    </aside>
  );
};

export default HomeStockWorkspace;
