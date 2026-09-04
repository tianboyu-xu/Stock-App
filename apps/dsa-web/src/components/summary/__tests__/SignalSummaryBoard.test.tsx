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
      if (key === 'home.summaryOpenDetailAria') return `open ${params?.code}`;
      if (key === 'home.summaryNoDetailAria') return `no detail ${params?.code}`;
      return key;
    },
  }),
}));

const entries: CompositeSummaryEntry[] = [
  { code: '600519', recordId: 11, tone: 'buy', intensity: 'strong', triggerDate: '2026-09-02' },
  { code: '00700', recordId: 12, tone: 'sell', intensity: 'light', triggerDate: '2026-08-28' },
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
    expect(screen.getByRole('button', { name: 'open 600519' })).toHaveTextContent('600519');
    expect(screen.getByRole('button', { name: 'open 00700' })).toHaveTextContent('00700');
    expect(screen.getByRole('button', { name: 'no detail AAPL' })).toHaveTextContent('AAPL');
    expect(screen.getByRole('button', { name: 'no detail AAPL' })).toBeDisabled();
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

    const buyButton = screen.getByRole('button', { name: 'open 600519' });
    const sellButton = screen.getByRole('button', { name: 'open 00700' });
    const plainButton = screen.getByRole('button', { name: 'no detail AAPL' });
    expect(buyButton.getAttribute('style')).toContain('--success');
    expect(sellButton.getAttribute('style')).toContain('--destructive');
    expect(plainButton.getAttribute('style')).toBeNull();
    expect(buyButton.querySelector('.text-success')).toBeNull();
    expect(sellButton.querySelector('.text-danger-dim')).toBeNull();
  });

  it('forwards stock selection like a watchlist item', () => {
    const onStockSelect = vi.fn();
    render(
      <SignalSummaryBoard
        entries={entries}
        isLoading={false}
        signalsUnavailable={false}
        onStockSelect={onStockSelect}
      />,
    );

    fireEvent.click(screen.getByRole('button', { name: 'open 600519' }));
    expect(onStockSelect).toHaveBeenCalledWith(entries[0]);
    fireEvent.click(screen.getByRole('button', { name: 'no detail AAPL' }));
    expect(onStockSelect).toHaveBeenCalledTimes(1);
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
});
