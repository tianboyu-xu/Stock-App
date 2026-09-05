import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { stocksApi } from '../../../api/stocks';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { CURRENT_POSITIONS_STORAGE_KEY } from '../../../utils/currentPosition';
import { CurrentPositionTable } from '../CurrentPositionTable';

vi.mock('../../../api/stocks', () => ({
  stocksApi: {
    getQuote: vi.fn(),
    getHistory: vi.fn(),
    getIndicators: vi.fn(),
  },
}));

vi.mock('../../StockAutocomplete', () => ({
  StockAutocomplete: ({
    value,
    onChange,
    ariaLabel,
  }: {
    value: string;
    onChange: (value: string) => void;
    ariaLabel?: string;
  }) => (
    <input
      aria-label={ariaLabel}
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
}));

const TEXT: Record<string, string> = {
  'common.cancel': 'Cancel',
  'common.delete': 'Delete',
  'common.itemsCount': '{count} items',
  'home.currentPositionsTitle': 'Current positions',
  'home.currentPositionsDescription': 'Track positions',
  'home.currentPositionsTableAria': 'Current positions table',
  'home.currentPositionsAddAria': 'Add current position',
  'home.currentPositionsRefreshAria': 'Refresh position quotes',
  'home.currentPositionsEmptyTitle': 'No current positions',
  'home.currentPositionsEmptyDescription': 'Add a position',
  'home.currentPositionsStock': 'Stock',
  'home.currentPositionsStockPlaceholder': 'Enter code or name',
  'home.currentPositionsPurchaseDate': 'Purchase date',
  'home.currentPositionsPurchasePrice': 'Purchase price',
  'home.currentPositionsQuantity': 'Quantity',
  'home.currentPositionsAccount': 'Account',
  'home.currentPositionsAccountFor': '{code} position account',
  'home.currentPositionsCurrentPrice': 'Current price',
  'home.currentPositionsTotalPrice': 'Total price',
  'home.currentPositionsGainLoss': 'Gain / loss',
  'home.currentPositionsGainLossPct': 'Return',
  'home.currentPositionsAfterTaxCagr': 'After-tax CAGR',
  'home.currentPositionsAccountPct': 'Account %',
  'home.currentPositionsLastTriggerDate': 'Last trigger date',
  'home.currentPositionsLastTriggerPrice': 'Last trigger price',
  'home.currentPositionsDragAria': 'Drag {code} to reorder',
  'home.currentPositionsTriggerSideBuy': 'Buy',
  'home.currentPositionsTriggerSideSell': 'Sell',
  'home.currentPositionsProfitTitle': 'Position profit trend',
  'home.currentPositionsProfitDescription': 'Profit description',
  'home.currentPositionsProfitWindow': 'Profit window',
  'home.currentPositionsProfitLoading': 'Loading profit',
  'home.currentPositionsProfitUnavailable': 'Profit unavailable',
  'home.currentPositionsProfitEmpty': 'No profit data',
  'home.currentPositionsProfitAmount': 'Profit / loss',
  'home.currentPositionsProfitRange': 'Range: {from} ~ {to}',
  'home.currentPositionsTaxNote': 'Tax note',
  'home.currentPositionsQuoteLoading': 'Loading quote',
  'home.currentPositionsQuoteUnavailable': 'Quote unavailable',
  'home.currentPositionsStockRequired': 'Stock required',
  'home.currentPositionsDateInvalid': 'Date invalid',
  'home.currentPositionsPurchasePriceRequired': 'Purchase price required',
  'home.currentPositionsQuantityRequired': 'Quantity required',
  'home.currentPositionsSave': 'Add position',
  'home.currentPositionsEditAria': 'Edit {code} position',
  'home.currentPositionsSaveEditAria': 'Save {code} position',
  'home.currentPositionsCancelEditAria': 'Cancel editing {code} position',
  'home.currentPositionsDeleteAria': 'Delete {code} position',
};

vi.mock('../../../contexts/UiLanguageContext', () => ({
  UiLanguageProvider: ({ children }: { children: React.ReactNode }) => children,
  useUiLanguage: () => ({
    language: 'en',
    setLanguage: vi.fn(),
    t: (key: string, params?: Record<string, string | number>) => (
      (TEXT[key] ?? key).replace(/\{(\w+)\}/g, (_, name: string) => String(params?.[name] ?? `{${name}}`))
    ),
  }),
}));

describe('CurrentPositionTable', () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.clearAllMocks();
    vi.mocked(stocksApi.getQuote).mockResolvedValue({
      stockCode: 'AAPL',
      currentPrice: 120,
    });
    vi.mocked(stocksApi.getHistory).mockResolvedValue({
      stockCode: 'AAPL',
      stockName: 'Apple',
      period: 'daily',
      data: [
        { date: '2025-09-04', open: 100, high: 101, low: 99, close: 100 },
        { date: '2026-09-04', open: 119, high: 121, low: 118, close: 120 },
      ],
    });
    vi.mocked(stocksApi.getIndicators).mockRejectedValue(new Error('no indicators'));
  });

  it('adds a position from the plus action, persists it, and renders calculated returns', async () => {
    render(
      <UiLanguageProvider>
        <CurrentPositionTable entries={[]} />
      </UiLanguageProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Add current position' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Stock' }), { target: { value: 'AAPL' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Purchase price' }), { target: { value: '100' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Quantity' }), { target: { value: '2' } });
    fireEvent.change(screen.getByLabelText('Purchase date'), { target: { value: '2025-09-04' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Account' }), { target: { value: 'HSA' } });
    fireEvent.submit(screen.getByTestId('current-position-form'));

    expect(await screen.findAllByText('AAPL')).not.toHaveLength(0);
    await waitFor(() => expect(stocksApi.getQuote).toHaveBeenCalledWith('AAPL'));
    expect(screen.getByText('120.00')).toBeInTheDocument();
    expect(screen.getByText('+40.00')).toBeInTheDocument();
    expect(screen.getByText('+20.00%')).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Quantity' })).toBeInTheDocument();
    expect(screen.getByRole('columnheader', { name: 'Account' })).toBeInTheDocument();
    await waitFor(() => expect(stocksApi.getHistory).toHaveBeenCalledWith('AAPL', { period: 'daily', days: 30 }));
    expect(screen.getByTestId('current-position-profit-chart')).toBeInTheDocument();
    expect(JSON.parse(window.localStorage.getItem(CURRENT_POSITIONS_STORAGE_KEY) ?? '[]')[0].account).toBe('HSA');
  });

  it('edits the stock code from the row action and refreshes its quote', async () => {
    render(
      <UiLanguageProvider>
        <CurrentPositionTable entries={[]} />
      </UiLanguageProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Add current position' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Stock' }), { target: { value: 'AAPL' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Purchase price' }), { target: { value: '100' } });
    fireEvent.change(screen.getByLabelText('Purchase date'), { target: { value: '2025-09-04' } });
    fireEvent.submit(screen.getByTestId('current-position-form'));

    await screen.findAllByText('AAPL');
    await waitFor(() => expect(stocksApi.getQuote).toHaveBeenCalledWith('AAPL'));
    fireEvent.click(screen.getByRole('button', { name: 'Edit AAPL position' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Stock' }), { target: { value: 'MSFT' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save AAPL position' }));

    expect(await screen.findByText('MSFT')).toBeInTheDocument();
    await waitFor(() => expect(stocksApi.getQuote).toHaveBeenCalledWith('MSFT'));
    expect(JSON.parse(window.localStorage.getItem(CURRENT_POSITIONS_STORAGE_KEY) ?? '[]')[0].code).toBe('MSFT');
  });

  it('computes account % within the same account type', async () => {
    vi.mocked(stocksApi.getQuote).mockImplementation(async (code: string) => ({
      stockCode: code,
      currentPrice: code === 'AAPL' ? 100 : 200,
    }));
    render(
      <UiLanguageProvider>
        <CurrentPositionTable entries={[]} />
      </UiLanguageProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Add current position' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Stock' }), { target: { value: 'AAPL' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Purchase price' }), { target: { value: '50' } });
    fireEvent.change(screen.getByLabelText('Purchase date'), { target: { value: '2025-09-04' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Account' }), { target: { value: '401K' } });
    fireEvent.submit(screen.getByTestId('current-position-form'));
    await screen.findAllByText('AAPL');

    fireEvent.click(screen.getByRole('button', { name: 'Add current position' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Stock' }), { target: { value: 'MSFT' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Purchase price' }), { target: { value: '100' } });
    fireEvent.change(screen.getByLabelText('Purchase date'), { target: { value: '2025-09-04' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Account' }), { target: { value: '401K' } });
    fireEvent.submit(screen.getByTestId('current-position-form'));
    await screen.findAllByText('MSFT');

    await waitFor(() => expect(stocksApi.getQuote).toHaveBeenCalledWith('MSFT'));
    // 401K total = 100*1 + 200*1 = 300, so AAPL 33.33% and MSFT 66.67% within the same account type.
    expect(screen.getByText('33.33%')).toBeInTheDocument();
    expect(screen.getByText('66.67%')).toBeInTheDocument();
    expect(screen.queryByText('33.33%(401K)')).not.toBeInTheDocument();
  });

  it('edits share quantity from the row action', async () => {
    render(
      <UiLanguageProvider>
        <CurrentPositionTable entries={[]} />
      </UiLanguageProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Add current position' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Stock' }), { target: { value: 'AAPL' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Purchase price' }), { target: { value: '100' } });
    fireEvent.change(screen.getByLabelText('Purchase date'), { target: { value: '2025-09-04' } });
    fireEvent.submit(screen.getByTestId('current-position-form'));
    await screen.findAllByText('AAPL');

    fireEvent.click(screen.getByRole('button', { name: 'Edit AAPL position' }));
    fireEvent.change(screen.getByLabelText('Quantity'), { target: { value: '5' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save AAPL position' }));

    await waitFor(() => {
      expect(JSON.parse(window.localStorage.getItem(CURRENT_POSITIONS_STORAGE_KEY) ?? '[]')[0].quantity).toBe(5);
    });
    expect(screen.getByText('600.00')).toBeInTheDocument();
  });

  it('fetches trigger color for position codes missing from summary entries', async () => {
    vi.mocked(stocksApi.getIndicators).mockResolvedValue({
      stockCode: 'VOO',
      stockName: 'VOO',
      period: 'daily',
      dates: ['2026-09-03', '2026-09-04'],
      close: [500, 510],
      sma: {},
      ema: {},
      macd: [0, 0],
      macdSignal: [0, 0],
      k: [50, 50],
      d: [50, 50],
      j: [50, 50],
      rsi: [50, 50],
      rsi6: [50, 50],
      rsi14: [50, 50],
      bolu: [520, 520],
      bold: [490, 490],
      cci: [0, 0],
      obv: [1000, 1000],
      obvMa: {},
      triggers: {
        macdBuy: [null, null],
        macdSell: [null, null],
        kdjBuy: [null, null],
        kdjSell: [null, null],
        rsiBuy: [null, null],
        rsiSell: [null, null],
        obvBuy: [null, null],
        obvSell: [null, null],
      },
      composite: {
        buyScore: [0, 7],
        sellScore: [0, 0],
        buySignal: [null, 510],
        sellSignal: [null, null],
        buyBreakdown: [],
        sellBreakdown: [],
      },
      thresholds: {
        bolConstant: 0.1,
        macdBuy: 0.7,
        macdSell: 0.99,
        kdjBuy: 40,
        kdjSell: 70,
        rsiBuy: 10,
        rsiSell: 70,
        compositeBuyThreshold: 6,
        compositeSellThreshold: 6,
        macdLookback: 120,
        macdLowPercentile: 15,
        macdHighPercentile: 85,
        rsiLow: 15,
        rsiHigh: 85,
        kdjLow: 40,
        kdjHigh: 70,
        trendPeriod: 200,
      },
    });
    render(
      <UiLanguageProvider>
        <CurrentPositionTable entries={[]} />
      </UiLanguageProvider>,
    );

    fireEvent.click(screen.getByRole('button', { name: 'Add current position' }));
    fireEvent.change(screen.getByRole('textbox', { name: 'Stock' }), { target: { value: 'VOO' } });
    fireEvent.change(screen.getByRole('spinbutton', { name: 'Purchase price' }), { target: { value: '400' } });
    fireEvent.change(screen.getByLabelText('Purchase date'), { target: { value: '2025-09-04' } });
    fireEvent.submit(screen.getByTestId('current-position-form'));

    await screen.findAllByText('VOO');
    await waitFor(() => expect(stocksApi.getIndicators).toHaveBeenCalledWith(
      'VOO',
      expect.objectContaining({ period: 'daily', days: 30 }),
    ));
    const triggerDate = await screen.findByText('2026-09-04');
    expect(triggerDate.getAttribute('style')).toContain('--success');
    expect(screen.getByText('510.00')).toBeInTheDocument();
    expect(screen.getByText('(Buy)')).toBeInTheDocument();
  });

  it('shows buy/sell side for stale triggers without tone color', async () => {
    window.localStorage.setItem(CURRENT_POSITIONS_STORAGE_KEY, JSON.stringify([{
      id: 'bai-1',
      code: 'BAI',
      name: 'BAI',
      purchaseDate: '2025-09-04',
      purchasePrice: 40,
      quantity: 1,
      account: 'RSU',
    }]));
    render(
      <UiLanguageProvider>
        <CurrentPositionTable
          entries={[{
            code: 'BAI',
            recordId: null,
            tone: 'none',
            intensity: 'none',
            triggerDate: '2026-01-05',
            triggerPrice: 42.5,
            triggerSide: 'sell',
          }]}
        />
      </UiLanguageProvider>,
    );

    expect(await screen.findAllByText('BAI')).not.toHaveLength(0);
    expect(screen.getByText('42.50')).toBeInTheDocument();
    expect(screen.getByText('(Sell)')).toBeInTheDocument();
  });

  it('places account % immediately after the stock column and supports drag reorder', async () => {
    window.localStorage.setItem(CURRENT_POSITIONS_STORAGE_KEY, JSON.stringify([
      {
        id: 'p-aapl', code: 'AAPL', name: 'AAPL', purchaseDate: '2025-09-04',
        purchasePrice: 100, quantity: 1, account: 'HSA',
      },
      {
        id: 'p-msft', code: 'MSFT', name: 'MSFT', purchaseDate: '2025-09-04',
        purchasePrice: 100, quantity: 1, account: 'HSA',
      },
    ]));
    vi.mocked(stocksApi.getQuote).mockImplementation(async (code: string) => ({
      stockCode: code,
      currentPrice: 120,
    }));
    render(
      <UiLanguageProvider>
        <CurrentPositionTable entries={[]} />
      </UiLanguageProvider>,
    );

    await screen.findAllByText('AAPL');
    const headers = screen.getAllByRole('columnheader').map((header) => header.textContent);
    expect(headers[0]).toBe('Stock');
    expect(headers[1]).toBe('Account %');

    const firstRow = screen.getByTestId('position-row-p-aapl');
    const secondRow = screen.getByTestId('position-row-p-msft');
    fireEvent.dragStart(firstRow);
    fireEvent.dragOver(secondRow);
    fireEvent.drop(secondRow);

    await waitFor(() => {
      const stored = JSON.parse(window.localStorage.getItem(CURRENT_POSITIONS_STORAGE_KEY) ?? '[]');
      expect(stored.map((item: { code: string }) => item.code)).toEqual(['MSFT', 'AAPL']);
    });
  });
});
