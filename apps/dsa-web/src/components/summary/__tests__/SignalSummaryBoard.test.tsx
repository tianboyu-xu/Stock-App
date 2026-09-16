import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SignalSummaryBoard } from '../SignalSummaryBoard';
import type { CompositeSummaryEntry } from '../../../utils/compositeSummary';

vi.mock('../../../contexts/UiLanguageContext', () => ({
  useUiLanguage: () => ({
    language: 'zh',
    setLanguage: vi.fn(),
    t: (key: string, params?: Record<string, string | number>) => {
      if (key === 'common.itemsCount') return `共 ${params?.count ?? 0} 项`;
      if (key === 'home.summaryOpenChartAria') return `chart ${params?.code}`;
      if (key === 'home.summaryTriggerStrong') return '3天内';
      if (key === 'home.summaryTriggerLight') return '7天内';
      if (key === 'home.summaryTriggerStale') return '7天外';
      if (key === 'home.summaryTriggerNone') return '近7天无触发';
      if (key === 'home.summaryTriggerSideBuy') return '买入';
      if (key === 'home.summaryTriggerSideSell') return '卖出';
      return key;
    },
  }),
}));

const entries: CompositeSummaryEntry[] = [
  { code: '600519', recordId: 11, tone: 'buy', intensity: 'strong', triggerDate: '2026-09-02', triggerPrice: 1688.1, triggerSide: 'buy' },
  { code: '00700', recordId: 12, tone: 'sell', intensity: 'light', triggerDate: '2026-08-28', triggerPrice: 520, triggerSide: 'sell' },
  { code: 'AAPL', recordId: null, tone: 'none', intensity: 'none', triggerDate: null },
];

describe('SignalSummaryBoard', () => {
  it('renders one stock item per entry with code only', () => {
    render(
      <SignalSummaryBoard
        entries={entries}
        isLoading={false}
        signalsUnavailable={false}
        onStockSelect={() => {}}
      />,
    );

    const container = screen.getByTestId('signal-summary-items');
    expect(container.children).toHaveLength(3);
    expect(screen.getByRole('button', { name: 'chart 600519' })).toHaveTextContent('600519');
    expect(screen.getByRole('button', { name: 'chart 00700' })).toHaveTextContent('00700');
    const chartOnlyButton = screen.getByRole('button', { name: 'chart AAPL' });
    expect(chartOnlyButton).toHaveTextContent('AAPL');
    expect(chartOnlyButton).toBeEnabled();
    // Old code-only style: no inline trigger sublabel, trigger info stays in the hover title.
    expect(screen.queryByTestId('signal-summary-trigger-600519')).toBeNull();
    expect(screen.getByRole('button', { name: 'chart 600519' })).toHaveAttribute(
      'title',
      expect.stringContaining('2026-09-02'),
    );
  });

  it('tints only the item box background for buy and sell triggers', () => {
    render(
      <SignalSummaryBoard
        entries={entries}
        isLoading={false}
        signalsUnavailable={false}
        onStockSelect={() => {}}
      />,
    );

    const buyButton = screen.getByRole('button', { name: 'chart 600519' });
    const sellButton = screen.getByRole('button', { name: 'chart 00700' });
    const plainButton = screen.getByRole('button', { name: 'chart AAPL' });
    expect(buyButton.getAttribute('style')).toContain('--success');
    expect(sellButton.getAttribute('style')).toContain('--destructive');
    expect(plainButton.getAttribute('style')).toBeNull();
    expect(buyButton.querySelector('.text-success')).toBeNull();
    expect(sellButton.querySelector('.text-danger-dim')).toBeNull();
  });

  it('forwards every stock selection to the live price chart, even without a report', () => {
    const onStockSelect = vi.fn();
    render(
      <SignalSummaryBoard
        entries={entries}
        isLoading={false}
        signalsUnavailable={false}
        onStockSelect={onStockSelect}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'chart 600519' }));
    expect(onStockSelect).toHaveBeenCalledWith(entries[0]);
    fireEvent.click(screen.getByRole('button', { name: 'chart AAPL' }));
    expect(onStockSelect).toHaveBeenCalledTimes(2);
    expect(onStockSelect).toHaveBeenNthCalledWith(2, entries[2]);
  });

  it('shows loading and empty states', () => {
    const { rerender } = render(
      <SignalSummaryBoard
        entries={[]}
        isLoading
        signalsUnavailable={false}
        onStockSelect={() => {}}
      />,
    );
    expect(screen.queryByTestId('signal-summary-items')).toBeNull();

    rerender(
      <SignalSummaryBoard
        entries={[]}
        isLoading={false}
        signalsUnavailable={false}
        onStockSelect={() => {}}
      />,
    );
    expect(screen.getByText('home.summaryEmptyTitle')).toBeTruthy();
  });

  it('shows the retry action when triggers are unavailable', () => {
    const onRetry = vi.fn();
    render(
      <SignalSummaryBoard
        entries={entries}
        isLoading={false}
        signalsUnavailable
        onRetry={onRetry}
        onStockSelect={() => {}}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'common.retry' }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('keeps entries visible while refreshing instead of collapsing to loading', () => {
    render(
      <SignalSummaryBoard
        entries={entries}
        isLoading
        signalsUnavailable={false}
        onStockSelect={() => {}}
      />,
    );

    // Stale-while-revalidate: same items stay mounted (no height collapse /
    // page shift) with a subtle refreshing indicator.
    const container = screen.getByTestId('signal-summary-items');
    expect(container.children).toHaveLength(3);
    expect(screen.getByRole('status')).toBeInTheDocument();
    expect(screen.getByTestId('signal-summary-board')).toHaveAttribute('aria-busy', 'true');
  });
});
