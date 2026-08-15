import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { HomeStockWorkspace } from '../HomeStockWorkspace';
import type { HomeWatchlistRow } from '../HomeStockWorkspace';

function renderWorkspace({
  watchlistRows,
  selectedRecordId,
  selectedStockCode,
  onReorderWatchlist,
}: {
  watchlistRows: HomeWatchlistRow[];
  selectedRecordId?: number;
  selectedStockCode?: string;
  onReorderWatchlist?: (orderedCodes: string[]) => Promise<void>;
}) {
  const onHistoryItemClick = vi.fn();
  const onRemoveFromWatchlist = vi.fn().mockResolvedValue(undefined);
  const reorderMock = onReorderWatchlist ?? vi.fn().mockResolvedValue(undefined);
  window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');

  const renderView = (rows: HomeWatchlistRow[]) => (
    <UiLanguageProvider>
      <HomeStockWorkspace
        activeTab="watchlist"
        onTabChange={vi.fn()}
        watchlistRows={rows}
        watchlistLoading={false}
        watchlistActioning={false}
        watchlistMessage={null}
        onAddToWatchlist={vi.fn().mockResolvedValue(undefined)}
        onRemoveFromWatchlist={onRemoveFromWatchlist}
        onReorderWatchlist={reorderMock}
        onRefreshWatchlist={vi.fn().mockResolvedValue(undefined)}
        onAnalyzeWatchlist={vi.fn().mockResolvedValue(undefined)}
        isBatchAnalyzing={false}
        batchStatus={null}
        todayItems={[]}
        isLoadingTodayItems={false}
        todayLoadError={false}
        watchlistAnalyzedTodayCount={rows.filter((row) => row.analyzedToday).length}
        historyItems={[]}
        isLoadingHistory={false}
        selectedStockCode={selectedStockCode}
        selectedRecordId={selectedRecordId}
        onHistoryItemClick={onHistoryItemClick}
      />
    </UiLanguageProvider>
  );
  const view = render(renderView(watchlistRows));

  return {
    onHistoryItemClick,
    onRemoveFromWatchlist,
    onReorderWatchlist: reorderMock,
    rerenderWatchlistRows: (rows: HomeWatchlistRow[]) => view.rerender(renderView(rows)),
  };
}

describe('HomeStockWorkspace', () => {
  it('opens the latest watchlist detail from a native button and keeps the row selected', () => {
    const { onHistoryItemClick } = renderWorkspace({
      watchlistRows: [{
        code: '600519',
        analyzedToday: true,
        latestItem: {
          id: 21,
          stockCode: '600519',
          stockName: '贵州茅台',
          sentimentScore: 88,
          operationAdvice: '买入',
          analysisCount: 1,
          lastAnalysisTime: '2026-03-19T09:00:00+08:00',
        },
      }],
      selectedRecordId: 21,
    });

    const row = screen.getByRole('button', { name: '打开 600519 最新分析详情' });
    fireEvent.click(row);

    expect(onHistoryItemClick).toHaveBeenCalledWith(21);
    expect(row.tagName).toBe('BUTTON');
    expect(row).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows an explicit notice when a watchlist row has no detail yet', async () => {
    const { onHistoryItemClick } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
      }],
    });

    const row = screen.getByRole('button', { name: '暂无 AAPL 的分析详情，可先分析' });
    fireEvent.click(row);

    expect(await screen.findByRole('alert')).toHaveTextContent('暂无分析详情，可先分析。');
    expect(onHistoryItemClick).not.toHaveBeenCalled();
  });

  it('shows loading feedback instead of no-detail copy while latest detail lookup is still pending', async () => {
    const { onHistoryItemClick } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
        isTodayStatusLoading: true,
      }],
    });

    const row = screen.getByRole('button', { name: '正在查找 AAPL 的最新分析详情' });
    fireEvent.click(row);

    expect(await screen.findByRole('alert')).toHaveTextContent('正在查找最新分析详情，请稍候。');
    expect(onHistoryItemClick).not.toHaveBeenCalled();
    expect(screen.getByText('正在查找详情...')).toBeInTheDocument();
  });

  it('shows retry feedback instead of no-detail copy when the latest detail lookup failed', async () => {
    const { onHistoryItemClick } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
        isTodayStatusUnknown: true,
      }],
    });

    const row = screen.getByRole('button', { name: 'AAPL 的最新分析详情暂时无法确认，请稍后重试' });
    fireEvent.click(row);

    expect(await screen.findByRole('alert')).toHaveTextContent('最新分析详情暂时无法确认，请稍后重试。');
    expect(screen.queryByText('暂无分析详情，可先分析。')).not.toBeInTheDocument();
    expect(screen.getByText('详情暂不可用')).toBeInTheDocument();
    expect(onHistoryItemClick).not.toHaveBeenCalled();
  });

  it('does not expose a cached detail while the current row status is unsettled', async () => {
    const cachedItem = {
      id: 24,
      stockCode: 'AAPL',
      stockName: 'Apple',
      sentimentScore: 68,
      operationAdvice: 'neutral',
      analysisCount: 1,
      lastAnalysisTime: '2026-03-18T09:20:00+08:00',
    };
    const { onHistoryItemClick, rerenderWatchlistRows } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
        latestItem: cachedItem,
        isTodayStatusLoading: true,
      }],
    });

    fireEvent.click(screen.getByRole('button', { name: '\u6b63\u5728\u67e5\u627e AAPL \u7684\u6700\u65b0\u5206\u6790\u8be6\u60c5' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('\u6b63\u5728\u67e5\u627e\u6700\u65b0\u5206\u6790\u8be6\u60c5\uff0c\u8bf7\u7a0d\u5019\u3002');
    expect(onHistoryItemClick).not.toHaveBeenCalled();

    rerenderWatchlistRows([{
      code: 'AAPL',
      analyzedToday: false,
      latestItem: cachedItem,
      isTodayStatusUnknown: true,
    }]);
    fireEvent.click(screen.getByRole('button', { name: 'AAPL \u7684\u6700\u65b0\u5206\u6790\u8be6\u60c5\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5' }));
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('\u6700\u65b0\u5206\u6790\u8be6\u60c5\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002');
    });
    expect(onHistoryItemClick).not.toHaveBeenCalled();
  });

  it('clears a loading notice when the same row detail lookup settles', async () => {
    const { rerenderWatchlistRows } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
        isTodayStatusLoading: true,
      }],
    });

    const row = screen.getByTestId('watchlist-row-AAPL');
    fireEvent.click(row.querySelector('button[aria-pressed]') as HTMLButtonElement);
    expect(await screen.findByRole('alert')).toBeInTheDocument();

    rerenderWatchlistRows([{
      code: 'AAPL',
      analyzedToday: false,
      latestItem: {
        id: 22,
        stockCode: 'AAPL',
        stockName: 'Apple',
        sentimentScore: 72,
        operationAdvice: 'neutral',
        analysisCount: 1,
        lastAnalysisTime: '2026-03-19T09:00:00+08:00',
      },
    }]);

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(row.querySelector('button[aria-pressed]')).toBeInTheDocument();
  });

  it('clears a no-detail notice when the matching row receives a detail', async () => {
    const { rerenderWatchlistRows } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
      }],
    });

    fireEvent.click(screen.getByRole('button', { name: '暂无 AAPL 的分析详情，可先分析' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('暂无分析详情，可先分析。');

    rerenderWatchlistRows([{
      code: 'AAPL',
      analyzedToday: true,
      latestItem: {
        id: 23,
        stockCode: 'AAPL',
        stockName: 'Apple',
        sentimentScore: 80,
        operationAdvice: 'buy',
        analysisCount: 1,
        lastAnalysisTime: '2026-03-19T10:00:00+08:00',
      },
    }]);

    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: '打开 AAPL 最新分析详情' })).toBeInTheDocument();
  });

  it('derives an opened notice from the latest row state instead of retaining stale copy', async () => {
    const { rerenderWatchlistRows } = renderWorkspace({
      watchlistRows: [{
        code: 'AAPL',
        analyzedToday: false,
      }],
    });

    const row = screen.getByTestId('watchlist-row-AAPL');
    fireEvent.click(row.querySelector('button[aria-pressed]') as HTMLButtonElement);
    expect(await screen.findByRole('alert')).toHaveTextContent('\u6682\u65e0\u5206\u6790\u8be6\u60c5\uff0c\u53ef\u5148\u5206\u6790\u3002');

    rerenderWatchlistRows([{
      code: 'AAPL',
      analyzedToday: false,
      isTodayStatusLoading: true,
    }]);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('\u6b63\u5728\u67e5\u627e\u6700\u65b0\u5206\u6790\u8be6\u60c5\uff0c\u8bf7\u7a0d\u5019\u3002');
    });

    rerenderWatchlistRows([{
      code: 'AAPL',
      analyzedToday: false,
      isTodayStatusUnknown: true,
    }]);
    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('\u6700\u65b0\u5206\u6790\u8be6\u60c5\u6682\u65f6\u65e0\u6cd5\u786e\u8ba4\uff0c\u8bf7\u7a0d\u540e\u91cd\u8bd5\u3002');
    });
  });

  it('does not bubble delete clicks into detail opening', async () => {
    const { onHistoryItemClick, onRemoveFromWatchlist } = renderWorkspace({
      watchlistRows: [{
        code: '600519',
        analyzedToday: true,
        latestItem: {
          id: 21,
          stockCode: '600519',
          stockName: '贵州茅台',
          sentimentScore: 88,
          operationAdvice: '买入',
          analysisCount: 1,
          lastAnalysisTime: '2026-03-19T09:00:00+08:00',
        },
      }],
    });

    fireEvent.click(screen.getByRole('button', { name: '从自选股移除 600519' }));

    expect(onRemoveFromWatchlist).toHaveBeenCalledWith('600519');
    expect(onHistoryItemClick).not.toHaveBeenCalled();
  });

  it('keeps the watchlist row selected for equivalent stock-code formats', () => {
    renderWorkspace({
      watchlistRows: [{
        code: 'HK700',
        analyzedToday: true,
        latestItem: {
          id: 88,
          stockCode: '00700',
          stockName: '腾讯控股',
          sentimentScore: 91,
          operationAdvice: '买入',
          analysisCount: 1,
          lastAnalysisTime: '2026-03-19T09:00:00+08:00',
        },
      }],
      selectedStockCode: '00700.HK',
    });

    expect(screen.getByRole('button', { name: '打开 HK700 最新分析详情' })).toHaveAttribute('aria-pressed', 'true');
  });

  const createDataTransfer = () => ({
    effectAllowed: 'all',
    dropEffect: 'none',
    setData: vi.fn(),
    getData: vi.fn(),
    clearData: vi.fn(),
    setDragImage: vi.fn(),
    files: [],
    items: [],
    types: [],
  });

  it('reorders the list when a dragged row is dropped onto a gap position', async () => {
    const { onReorderWatchlist } = renderWorkspace({
      watchlistRows: [
        { code: '600519', analyzedToday: false },
        { code: 'AAPL', analyzedToday: false },
        { code: '000001', analyzedToday: false },
      ],
    });

    const dataTransfer = createDataTransfer();
    fireEvent.dragStart(screen.getByTestId('watchlist-row-600519'), { dataTransfer });
    const gapAfterAapl = screen.getByTestId('watchlist-drop-gap-2');
    fireEvent.dragOver(gapAfterAapl, { dataTransfer });
    fireEvent.drop(gapAfterAapl, { dataTransfer });

    await waitFor(() => {
      expect(onReorderWatchlist).toHaveBeenCalledWith(['AAPL', '600519', '000001']);
    });
  });

  it('reorders the list when a dragged row is dropped on the lower half of another row', async () => {
    const { onReorderWatchlist } = renderWorkspace({
      watchlistRows: [
        { code: '600519', analyzedToday: false },
        { code: 'AAPL', analyzedToday: false },
        { code: '000001', analyzedToday: false },
      ],
    });

    const dataTransfer = createDataTransfer();
    fireEvent.dragStart(screen.getByTestId('watchlist-row-600519'), { dataTransfer });
    const aaplRow = screen.getByTestId('watchlist-row-AAPL');
    fireEvent.dragOver(aaplRow, { dataTransfer, clientY: 100 });
    fireEvent.drop(aaplRow, { dataTransfer, clientY: 100 });

    await waitFor(() => {
      expect(onReorderWatchlist).toHaveBeenCalledWith(['AAPL', '600519', '000001']);
    });
  });

  it('renders the full company name without truncation', () => {
    renderWorkspace({
      watchlistRows: [{
        code: '600519',
        analyzedToday: true,
        latestItem: {
          id: 21,
          stockCode: '600519',
          stockName: '贵州茅台酒股份有限公司',
          sentimentScore: 88,
          operationAdvice: '买入',
          analysisCount: 1,
          lastAnalysisTime: '2026-03-19T09:00:00+08:00',
        },
      }],
    });

    expect(screen.getByText('贵州茅台酒股份有限公司')).toBeInTheDocument();
  });
});
