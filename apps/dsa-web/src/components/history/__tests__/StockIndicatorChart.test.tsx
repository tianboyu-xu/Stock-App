import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AUTO_TUNE_METHODOLOGY_VERSION, stocksApi, type AutoTuneResponse, type AutoTuneStrategyResult, type AllocationMetrics, type AllocationTransition } from '../../../api/stocks';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { StockIndicatorChart } from '../StockIndicatorChart';
import { isVisibleTradeMark, strategyPresentation, combinedStrategyCurves, findHoldingAnchor, navTradeDots, rebaseRowsFromPurchaseDate, selectDateTickCount, withTradePnL } from '../autoTunePresentation';
import { CURRENT_POSITIONS_STORAGE_KEY } from '../../../utils/currentPosition';
import { visibleTriggersStorageKey } from '../../../utils/visibleTriggers';
import { clearAutoTuneSessionCache, peekAutoTuneState } from '../../../utils/autoTuneStorage';

vi.mock('../../../api/stocks', async () => {
  const actual = await vi.importActual<typeof import('../../../api/stocks')>('../../../api/stocks');
  return {
    ...actual,
    stocksApi: {
      ...actual.stocksApi,
      getIndicators: vi.fn(),
      autoTune: vi.fn(),
    },
  };
});

const BAR_COUNT = 6;

const indicatorDates = Array.from({ length: BAR_COUNT }, (_v, i) => `2026-03-0${i + 1}`);
const closePrices = [104, 107, 103, 110, 112, 115];

function buildIndicatorResponse() {
  return {
    stockCode: '600519',
    stockName: '贵州茅台',
    period: 'daily' as const,
    dates: indicatorDates,
    close: closePrices,
    sma: {
      '5': closePrices.map((c) => c - 1),
      '200': Array.from({ length: BAR_COUNT }, () => 100),
    },
    ema: {},
    macd: [0.1, 0.2, -0.1, 0.3, 0.25, 0.4],
    macdSignal: [0.1, 0.15, 0.12, 0.2, 0.22, 0.3],
    k: [50, 55, 48, 60, 62, 65],
    d: [48, 52, 50, 55, 57, 60],
    j: [54, 61, 44, 70, 72, 75],
    rsi: [60, 65, 45, 70, 72, 75],
    rsi6: [58, 60, 40, 68, 70, 73],
    rsi14: [55, 57, 48, 66, 68, 71],
    bolu: closePrices.map((c) => c + 8),
    bold: closePrices.map((c) => c - 8),
    cci: [10, 12, -5, 20, 25, 30],
    obv: [1000, 2200, 1800, 3000, 3400, 4000],
    obvMa: {},
    triggers: {
      macdBuy: [null, null, null, 110, null, null],
      macdSell: [null, null, null, null, null, null],
      kdjBuy: [null, null, null, null, null, null],
      kdjSell: [null, null, null, null, null, null],
      rsiBuy: [null, null, null, null, null, null],
      rsiSell: [null, null, null, null, null, null],
      obvBuy: [null, null, 103, null, null, null],
      obvSell: [null, null, null, null, null, null],
      bollBuy: [null, null, null, 110, null, null],
      bollSell: [null, null, null, null, 112, null],
      cciBuy: [null, null, null, null, null, null],
      cciSell: [null, null, null, null, null, null],
      dmiBuy: [null, null, null, null, null, null],
      dmiSell: [null, null, null, null, null, null],
      mfiBuy: [null, null, null, null, null, null],
      mfiSell: [null, null, null, null, null, null],
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
      bollBuyLevel: 0.1,
      bollSellLevel: 0.9,
      bollWeight: 2,
      cciBuyLevel: -100,
      cciSellLevel: 100,
      cciWeight: 0,
      adxMinLevel: 20,
      dmiWeight: 0,
      mfiBuyLevel: 20,
      mfiSellLevel: 80,
      mfiWeight: 0,
      volumeConfirmLevel: 1.5,
      volumeWeight: 0,
      range52HighLevel: 0.95,
      range52LowLevel: 1.05,
      range52Weight: 0,
    },
    composite: {
      buyScore: [3, 4, 5, 8, 7, 9],
      sellScore: [2, 2, 3, 4, 3, 5],
      buySignal: [null, null, null, 1, null, null],
      sellSignal: [null, null, null, null, null, null],
      buyBreakdown: [
        { macd: 1, kdj: 1, rsi: 0, regime: 1, momentum: 1, boll: 0, cci: 0, dmi: 0, mfi: 0, volume: 0, range52: 0 },
        { macd: 1, kdj: 1, rsi: 0, regime: 1, momentum: 1, boll: 0, cci: 0, dmi: 0, mfi: 0, volume: 0, range52: 0 },
        { macd: 1, kdj: 1, rsi: 0, regime: 1, momentum: 1, boll: 0, cci: 0, dmi: 0, mfi: 0, volume: 0, range52: 0 },
        { macd: 2, kdj: 1, rsi: 1, regime: 1, momentum: 1, boll: 2, cci: 0, dmi: 0, mfi: 0, volume: 0, range52: 0 },
        { macd: 1, kdj: 1, rsi: 1, regime: 1, momentum: 1, boll: 2, cci: 0, dmi: 0, mfi: 0, volume: 0, range52: 0 },
        { macd: 2, kdj: 1, rsi: 1, regime: 2, momentum: 1, boll: 2, cci: 0, dmi: 0, mfi: 0, volume: 0, range52: 0 },
      ],
      sellBreakdown: [
        { macd: 0, kdj: 0, rsi: 0, regime: 1, momentum: 1, boll: 0, cci: 0, dmi: 0, mfi: 0, volume: 0, range52: 0 },
        { macd: 0, kdj: 0, rsi: 0, regime: 1, momentum: 1, boll: 0, cci: 0, dmi: 0, mfi: 0, volume: 0, range52: 0 },
        { macd: 1, kdj: 0, rsi: 0, regime: 1, momentum: 1, boll: 0, cci: 0, dmi: 0, mfi: 0, volume: 0, range52: 0 },
        { macd: 1, kdj: 1, rsi: 0, regime: 1, momentum: 1, boll: 0, cci: 0, dmi: 0, mfi: 0, volume: 0, range52: 0 },
        { macd: 1, kdj: 1, rsi: 0, regime: 0, momentum: 1, boll: 0, cci: 0, dmi: 0, mfi: 0, volume: 0, range52: 0 },
        { macd: 2, kdj: 1, rsi: 0, regime: 1, momentum: 1, boll: 0, cci: 0, dmi: 0, mfi: 0, volume: 0, range52: 0 },
      ],
      maxBuyScore: 12,
      maxSellScore: 12,
    },
  };
}

const segmentMetrics = {
  totalReturnPct: 20,
  cagrPct: 10,
  afterTaxTotalReturnPct: 18,
  afterTaxCagrPct: 9,
  maxDrawdownPct: -8,
  sharpe: 1.2,
  sortino: 1.5,
  profitFactor: 2,
  trades: 10,
  winRatePct: 60,
  avgTradePct: 2,
  avgHoldingDays: 30,
  exposurePct: 50,
  tradesPerYear: 5,
};

const equityDates = ['2024-01-02', '2024-03-01', '2024-06-03', '2024-09-02', '2024-12-02'];

function buildAutoTuneResponse() {
  return {
    methodologyVersion: AUTO_TUNE_METHODOLOGY_VERSION,
    windowDays: 90,
    history: {
      bars: 2400,
      startDate: '2016-01-04',
      endDate: '2025-12-31',
      yearsRequested: 10,
      yearsUsed: 10,
      testYearsRequested: 5,
      testYearsUsed: 5,
    },
    split: {
      train: { startDate: '2016-01-04', endDate: '2022-01-01', bars: 1440 },
      validation: { startDate: '2022-01-04', endDate: '2024-01-01', bars: 480 },
      test: { startDate: '2024-01-02', endDate: '2025-12-31', bars: 480 },
      trainValidation: { startDate: '2016-01-04', endDate: '2024-01-01', bars: 1920 },
    },
    assumptions: {
      cost_pct_per_side: 0.05,
      capitalGainsTaxShortTermPct: 35,
      capitalGainsTaxLongTermPct: 15,
    },
    fixedParameters: { keys: ['rsi_period'], reasonCode: 'fixed_defaults' },
    strategies: [
      {
        key: 'A',
        nameZh: '基线 A',
        nameEn: 'Baseline A',
        descriptionZh: '基线策略',
        descriptionEn: 'Baseline strategy',
        tuned: true,
        params: {
          thresholds: {
            compositeBuyThreshold: 5,
            compositeSellThreshold: 7,
            rsiLow: 14,
            rsiHigh: 84,
            kdjLow: 35,
            kdjHigh: 75,
            macdLookback: 90,
            macdLowPercentile: 15,
            macdHighPercentile: 85,
            trendPeriod: 200,
          },
          stopMultipleAtr: null,
          trailMultipleAtr: null,
        },
        metrics: { trainValidation: segmentMetrics, test: { ...segmentMetrics, cagrPct: 12 } },
        objectives: { score: 1.2 },
        paramRobustness: 0.8,
        testEquity: {
          dates: equityDates,
          values: [0, 2.5, -1, 4.2, 8.8],
        },
      },
      {
        key: 'C',
        nameZh: '趋势 B',
        nameEn: 'Trend B',
        descriptionZh: '趋势过滤 + ATR 风控',
        descriptionEn: 'Trend filter + ATR risk',
        tuned: true,
        params: {
          thresholds: {
            compositeBuyThreshold: 7,
            compositeSellThreshold: 8,
            rsiLow: 20,
            rsiHigh: 80,
            kdjLow: 30,
            kdjHigh: 70,
            macdLookback: 100,
            macdLowPercentile: 20,
            macdHighPercentile: 80,
            trendPeriod: 200,
          },
          stopMultipleAtr: 2.5,
          trailMultipleAtr: 3.5,
        },
        metrics: { trainValidation: segmentMetrics, test: { ...segmentMetrics, cagrPct: 11 } },
        objectives: { score: 1.1 },
        paramRobustness: 0.7,
        testEquity: {
          dates: equityDates,
          values: [0, 1, -2, 3, 12.4],
        },
      },
    ],
    benchmarks: [
      {
        key: 'sp500_buy_hold',
        nameZh: '标普500 买入持有',
        nameEn: 'S&P 500 buy & hold',
        descriptionZh: '',
        descriptionEn: '',
        available: false,
        metrics: { trainValidation: null, test: null },
        testEquity: null,
      },
      {
        key: 'stock_buy_hold',
        nameZh: '个股买入持有',
        nameEn: 'Stock buy & hold',
        descriptionZh: '',
        descriptionEn: '',
        available: true,
        metrics: { trainValidation: segmentMetrics, test: segmentMetrics },
        testEquity: {
          dates: equityDates,
          values: [0, 1, 3, 2, 5],
        },
      },
      {
        key: 'strategy_on_sp500',
        nameZh: '推荐时点 × 标普500',
        nameEn: 'Recommended signals on S&P 500',
        descriptionZh: '',
        descriptionEn: '',
        available: false,
        metrics: { trainValidation: null, test: null },
        testEquity: null,
      },
    ],
    recommended: {
      strategyKey: 'A',
      reasonCode: 'best_validation',
      eps: 0.01,
      thresholds: {},
      risk: {},
      paramsDisplay: [],
    },
  };
}

function renderChart() {
  return render(
    <UiLanguageProvider>
      <StockIndicatorChart stockCode="600519" stockName="贵州茅台" />
    </UiLanguageProvider>,
  );
}

async function runAutoTuneAndGetPlot() {
  const tuneButton = await screen.findByRole('button', { name: 'Auto Tune' });
  fireEvent.click(tuneButton);
  await screen.findAllByText('基线 A');
  const plot = screen.getByTestId('strategy-nav-chart');
  return plot;
}

describe('StockIndicatorChart auto tune panel', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    clearAutoTuneSessionCache();
    window.localStorage.clear();
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'zh');
    vi.mocked(stocksApi.getIndicators).mockResolvedValue(buildIndicatorResponse());
    vi.mocked(stocksApi.autoTune).mockResolvedValue(buildAutoTuneResponse());
  });

  it('shows the six strategy options and shares selection and range with the NAV chart', async () => {
    renderChart();
    await runAutoTuneAndGetPlot();
    expect(vi.mocked(stocksApi.autoTune).mock.calls.at(-1)?.[1]).toMatchObject({ includeMacroRouter: true });

    const strategySelect = screen.getByTestId('trigger-strategy-select') as HTMLSelectElement;
    expect(strategySelect.options).toHaveLength(6);
    expect(strategySelect).toHaveValue('baseline');
    expect(screen.getAllByTestId('strategy-nav-chart')).toHaveLength(1);
    expect(screen.getByTestId('strategy-combined-chart')).toBeInTheDocument();
    expect(screen.getByText('研究详情与参数').closest('details')).not.toHaveAttribute('open');
    expect(screen.getAllByText('个股买入持有').length).toBeGreaterThan(0);

    fireEvent.change(strategySelect, { target: { value: 'budget' } });
    expect(strategySelect).toHaveValue('budget');
    expect(screen.getByTestId('strategy-combined-chart')).toHaveTextContent('自适应预算');
    await waitFor(() => expect(JSON.parse(window.localStorage.getItem('dsa.autotune.600519')!).selectedTriggerStrategy).toBe('budget'));
    fireEvent.click(screen.getByRole('button', { name: '7天' }));
    await waitFor(() => expect(screen.getByTestId('strategy-combined-chart')).toHaveTextContent('7 根'));
    expect(JSON.parse(window.localStorage.getItem('dsa.autotune.600519')!).days).toBe(7);

    const lastCall = vi.mocked(stocksApi.autoTune).mock.calls.at(-1);
    expect(lastCall?.[0]).toBe('600519');
    expect(lastCall?.[1]?.acesConfig).toMatchObject({ version: 1, enabled: true, buy_thresholds: [6, 7, 8], sell_thresholds: [-6, -7, -8],
      allocation: { economic: { allowed_max_drawdown: .25 } } });
  });

  it('keeps the new report after switching stocks when localStorage rejects the save', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    const response: AutoTuneResponse = buildAutoTuneResponse();
    const metrics: AllocationMetrics = { ...segmentMetrics, targetCagr: .3, initialNav: 1, finalNav: 1.4,
      tradeCount: 1, turnover: 1, averageExposurePct: 100, transactionCost: 0, allocationDecisions: 1,
      budgetConstrainedDecisions: 0, lowSampleFallbacks: 0, fallbackPct: 0 };
    response.allocation = { selectedPolicy: 'FIXED', selectionBasis: 'validation', uniqueStatesVisited: 1,
      qTable: [], config: { policyMode: 'FIXED', simplicityTolerance: 0, q: {}, state: {} },
      policies: [{ name: 'FIXED', transitions: [], executions: [],
        metrics: { train: metrics, validation: metrics, test: metrics },
        testEquity: response.strategies[0].testEquity!,
        economicCurve: equityDates.map((date, i) => ({ date, strategyNav: 1 + i / 10,
          benchmarkNav: 1 + i / 20, requiredNav: 1 + i / 15, cagrDeficit: 0 })),
      }] };
    vi.mocked(stocksApi.autoTune).mockResolvedValue(response);
    const old = { result: { ...buildAutoTuneResponse(), methodologyVersion: 1 },
      selectedStrategyKey: null, settings: { transactionWindow: 90, autoTuneYears: 10,
        autoTuneTestYears: 3, trainRangePct: null, fineTuneEnabled: false, fineTuneDays: 360 } };
    window.localStorage.setItem('dsa.autotune.600519', JSON.stringify(old));
    const chart = (code: string) => <UiLanguageProvider><StockIndicatorChart stockCode={code} /></UiLanguageProvider>;
    const rendered = render(chart('600519'));
    await screen.findByRole('alert');
    const setItem = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('Quota exceeded', 'QuotaExceededError');
    });
    try {
      fireEvent.click(screen.getByRole('button', { name: 'Auto Tune' }));
      await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
      const saved = peekAutoTuneState<{ result: AutoTuneResponse }>('dsa.autotune.600519');
      expect(saved?.result).toEqual(response);
      fireEvent.change(screen.getByTestId('trigger-strategy-select'), { target: { value: 'budget' } });
      rendered.rerender(chart('AAPL'));
      await waitFor(() => expect(screen.queryByTestId('strategy-nav-chart')).not.toBeInTheDocument());
      rendered.rerender(chart('600519'));
      await screen.findByTestId('strategy-nav-chart');
      expect(screen.queryByRole('alert')).not.toBeInTheDocument();
      expect(screen.getByTestId('trigger-strategy-select')).toHaveValue('budget');
      expect(strategyPresentation(peekAutoTuneState<{ result: AutoTuneResponse }>('dsa.autotune.600519')!.result, 'budget')
        .curve.map(point => point.benchmarkNav)).toEqual([1, 1.05, 1.1, 1.15, 1.2]);
      expect(peekAutoTuneState<{ result: AutoTuneResponse }>('dsa.autotune.600519')?.result).toEqual(saved?.result);
    } finally {
      setItem.mockRestore();
    }
  });

  it('requests MATR from the trigger selector and keeps missing macro data distinct from A–F signals', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    const response: AutoTuneResponse = buildAutoTuneResponse();
    response.macroRouter = { strategyKey: 'MATR', version: 1, status: 'UNAVAILABLE',
      reason: 'FRED_API_KEY_MISSING', correlations: [], history: [] };
    response.strategies[0].testDecisions = [{ date: '2026-03-02', signalDate: '2026-03-01',
      side: 'buy', status: 'executed', reason: 'signal', executionPrice: 107, tradeNavPct: 100,
      holdingPct: 100, score: 7, suggestedBudgetPct: 100, executedBudgetPct: 100, cashAfterPct: 0 }];
    vi.mocked(stocksApi.autoTune).mockResolvedValue(response);
    renderChart();
    await screen.findByRole('button', { name: 'Auto Tune' });
    const select = screen.getByTestId('trigger-strategy-select');
    fireEvent.change(select, { target: { value: 'macro_router' } });
    expect(screen.getByTestId('macro-router-panel')).toHaveTextContent('Run Auto Tune to include MATR in the strategy comparison');
    fireEvent.click(screen.getByRole('button', { name: 'Auto Tune' }));
    await waitFor(() => expect(screen.getByTestId('macro-router-panel')).toHaveTextContent('FRED_API_KEY_MISSING'));
    expect(vi.mocked(stocksApi.autoTune).mock.calls.at(-1)?.[1]).toMatchObject({ includeMacroRouter: true });
    expect(select).toHaveValue('macro_router');
    expect(screen.queryByRole('img', { name: /2026-03-02.*BUY.*100\.0%/ })).not.toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply selected to chart' })).toBeDisabled();
    expect(strategyPresentation(response, 'macro_router').marks).toEqual([]);
  });

  it('keeps MATR and other strategy NAV lines together when changing the trigger selection', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    const response: AutoTuneResponse = buildAutoTuneResponse();
    response.macroRouter = { strategyKey: 'MATR', version: 2, status: 'READY', correlations: [], history: [],
      testEquity: { dates: equityDates.slice(1, 4), values: [10, 8, 14] },
      benchmarkEquity: { dates: equityDates.slice(1, 4), values: [20, 25, 30] },
    };
    vi.mocked(stocksApi.autoTune).mockResolvedValue(response);
    renderChart();
    fireEvent.click(await screen.findByRole('button', { name: 'Auto Tune' }));
    const combined = await screen.findByTestId('strategy-combined-chart');
    expect(combined).toHaveTextContent('3 available strategies are shown together');
    expect(combined).toHaveTextContent('Common history: 2024-03-01 to 2024-09-02');
    expect(screen.queryByTestId('shared-date-axis')).not.toBeInTheDocument();
    const priceChart = screen.getByRole('img', { name: 'Technical indicators' });
    expect(within(priceChart).getByText('2026-03-01')).toBeInTheDocument();
    fireEvent.change(screen.getByTestId('trigger-strategy-select'), { target: { value: 'macro_router' } });
    expect(combined).toHaveTextContent('3 available strategies are shown together');
    expect(combined).toHaveTextContent('Selected strategy: MATR');
    expect(screen.getByTestId('macro-router-panel')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Apply selected to chart' })).toBeDisabled();
    const rows = combinedStrategyCurves(response, ['baseline', 'trend', 'macro_router']).rows;
    expect(rows.every(row => ['baseline', 'trend', 'macro_router'].every(family => row[`nav:${family}`] != null))).toBe(true);
  });

  it('restores the saved auto tune result and plot state for the current stock', async () => {
    window.localStorage.setItem('dsa.autotune.600519', JSON.stringify({
      result: buildAutoTuneResponse(),
      selectedStrategyKey: null,
      selectedTriggerStrategy: 'budget',
      days: 7,
      settings: {
        transactionWindow: 90,
        autoTuneYears: 10,
        autoTuneTestYears: 3,
        trainRangePct: null,
        fineTuneEnabled: false,
        fineTuneDays: 360,
      },
    }));
    renderChart();

    const strategySelect = await screen.findByTestId('trigger-strategy-select') as HTMLSelectElement;
    await waitFor(() => expect(strategySelect).toHaveValue('budget'));
    expect(screen.getByTestId('strategy-combined-chart')).toHaveTextContent('7 根');
    expect(screen.getAllByTestId('strategy-nav-chart')).toHaveLength(1);
  });

  it('normalizes a legacy snake-case cache so methodology and SPY NAV survive a stock switch', async () => {
    const response = buildAutoTuneResponse();
    const policy = {
      name: 'FIXED',
      metrics: { train: null, validation: null, test: { ...segmentMetrics, targetCagr: .3 } },
      transitions: [],
      test_equity: response.strategies[0].testEquity,
      executions: [],
      economic_curve: equityDates.map((date, index) => ({
        date,
        strategy_nav: 1 + index / 10,
        required_nav: 1 + index / 20,
        benchmark_nav: 1 + index / 25,
        cagr_deficit: 0,
      })),
    };
    const withoutMethodologyVersion: Record<string, unknown> = { ...response };
    delete withoutMethodologyVersion.methodologyVersion;
    window.localStorage.setItem('dsa.autotune.600519', JSON.stringify({
      result: {
        ...withoutMethodologyVersion,
        methodology_version: AUTO_TUNE_METHODOLOGY_VERSION,
        allocation: {
          technical_strategy_key: 'A',
          selected_policy: 'FIXED',
          selection_basis: 'validation',
          policies: [policy],
        },
      },
      selected_strategy_key: null,
      selected_trigger_strategy: 'budget',
      days: 7,
      settings: {
        transaction_window: 90,
        auto_tune_years: 10,
        auto_tune_test_years: 3,
        train_range_pct: null,
        fine_tune_enabled: false,
        fine_tune_days: 360,
      },
    }));

    renderChart();

    const navChart = await screen.findByTestId('strategy-nav-chart');
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(within(navChart).queryByRole('status')).not.toBeInTheDocument();
  });

  it('shows validation scores and metrics for sweep positions, with the final test separate', async () => {
    const response: AutoTuneResponse = buildAutoTuneResponse();
    response.fineTune = {
      selectionBasis: 'validation',
      windowDays: 360,
      step: 72,
      positionsTested: 2,
      bestPositionIndex: 1,
      sweep: [0, 1].map((positionIndex) => ({
        positionIndex,
        trainStart: '2018-01-02',
        trainEnd: '2019-01-02',
        trainBars: 252,
        validationStart: '2019-01-03',
        validationEnd: '2019-04-03',
        bestStrategyKey: 'A',
        validationCagr: 21 + positionIndex,
        validationSharpe: 1.1,
        validationMaxDd: -6,
        validationTrades: 4,
        validationScore: positionIndex === 0 ? -0.45 : 1.23,
        testCagr: null,
        testSharpe: null,
        testMaxDd: null,
        testTrades: null,
        thresholds: {},
        stopMultipleAtr: null,
        trailMultipleAtr: null,
        allStrategies: response.strategies.map((strategy) => ({
          key: strategy.key,
          nameZh: strategy.nameZh,
          nameEn: strategy.nameEn,
          tuned: strategy.tuned,
          validationCagr: 21 + positionIndex,
          validationSharpe: 1.1,
          validationMaxDd: -6,
          validationTrades: 4,
          validationScore: positionIndex === 0 ? -0.45 : 1.23,
          thresholds: strategy.params.thresholds,
          stopMultipleAtr: strategy.params.stopMultipleAtr,
          trailMultipleAtr: strategy.params.trailMultipleAtr,
        })),
      })),
      finalTest: {
        strategyKey: 'A',
        positionIndex: 1,
        metrics: { ...segmentMetrics, cagrPct: 42 },
        equity: response.strategies[0].testEquity!,
      },
    };
    vi.mocked(stocksApi.autoTune).mockResolvedValue(response);
    renderChart();
    await runAutoTuneAndGetPlot();

    const sweepChart = screen.getByRole('img', { name: '各窗口位置验证评分对比' });
    expect(within(sweepChart).getByText('-0.45')).toBeInTheDocument();
    expect(within(sweepChart).getByText('1.23')).toBeInTheDocument();
    expect(sweepChart.textContent).not.toContain('%');
    expect(screen.getByTestId('fine-tune-final-test')).toHaveTextContent('CAGR: 42%');
    expect(screen.getByTestId('fine-tune-final-test')).toHaveTextContent('#2');

    fireEvent.click(screen.getByRole('button', { name: /各窗口明细/ }));
    const table = screen.getByRole('columnheader', { name: '验证 CAGR' }).closest('table')!;
    expect(within(table).getByText('21.0%')).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: '验证评分' })).toBeInTheDocument();
    expect(within(table).getByRole('columnheader', { name: '验证范围' })).toBeInTheDocument();
    expect(table.textContent).not.toContain('42%');
  });

  it('preserves legacy cached settings but blocks applying or saving the outdated result until rerun', async () => {
    const legacyResult = {
      ...buildAutoTuneResponse(),
      methodologyVersion: undefined,
      fineTune: { sweep: [{ positionIndex: 0, testCagr: 100 }] },
    };
    const settings = {
      transactionWindow: 120,
      autoTuneYears: 15,
      autoTuneTestYears: 3,
      trainRangePct: null,
      fineTuneEnabled: false,
      fineTuneDays: 360,
    };
    window.localStorage.setItem('dsa.autotune.600519', JSON.stringify({
      result: legacyResult,
      selectedStrategyKey: 'C',
      settings,
    }));
    renderChart();
    await screen.findByRole('button', { name: 'Auto Tune' });
    expect(screen.getByRole('alert')).toHaveTextContent('请重新运行 Auto Tune');
    expect(screen.getByTestId('strategy-combined-chart')).toBeInTheDocument();
    expect(screen.getByTestId('strategy-nav-chart')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: '应用选中到图表' })).toBeDisabled();
    expect(screen.getByRole('button', { name: '保存为方案' })).toBeDisabled();
    expect(screen.queryByRole('img', { name: '各窗口位置验证评分对比' })).not.toBeInTheDocument();
    expect(screen.getByLabelText('交易窗口', { exact: false })).toHaveValue(120);
    expect(screen.getByLabelText('历史', { exact: false })).toHaveValue(15);
    const beforeApply = vi.mocked(stocksApi.getIndicators).mock.calls.length;
    fireEvent.click(screen.getByRole('button', { name: '应用选中到图表' }));
    expect(vi.mocked(stocksApi.getIndicators).mock.calls).toHaveLength(beforeApply);
    expect(JSON.parse(window.localStorage.getItem('dsa.autotune.600519')!).settings).toEqual(settings);

    fireEvent.click(screen.getByRole('button', { name: 'Auto Tune' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(screen.getByRole('button', { name: '应用选中到图表' })).toBeEnabled();
    expect(JSON.parse(window.localStorage.getItem('dsa.autotune.600519')!).result.methodologyVersion)
      .toBe(AUTO_TUNE_METHODOLOGY_VERSION);
  });

  it('keeps an incompatible saved preset loadable with an English warning and preserves it after rerun', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    const preset = {
      id: 'legacy',
      name: 'Old strategy',
      timestamp: 1,
      result: { ...buildAutoTuneResponse(), methodologyVersion: 1 },
      selectedStrategyKey: 'C',
      settings: {
        transactionWindow: 180,
        autoTuneYears: 12,
        autoTuneTestYears: 3,
        trainRangePct: null,
        fineTuneEnabled: false,
        fineTuneDays: 360,
      },
    };
    window.localStorage.setItem('dsa.autotune.presets', JSON.stringify([preset]));
    renderChart();
    const option = await screen.findByRole('option', { name: 'Old strategy · rerun required' });
    fireEvent.change(option.closest('select')!, { target: { value: 'legacy' } });
    expect(screen.getByRole('alert')).toHaveTextContent('rerun Auto Tune');
    expect(screen.getByRole('button', { name: 'Apply selected to chart' })).toBeDisabled();
    expect(screen.getByLabelText('Trade window', { exact: false })).toHaveValue(180);
    fireEvent.click(screen.getByRole('button', { name: 'Auto Tune' }));
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
    expect(JSON.parse(window.localStorage.getItem('dsa.autotune.presets')!)).toEqual([preset]);
  });

  it('explains cross-fold validation and conditional test uncertainty, including insufficient evidence', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    const response: AutoTuneResponse = buildAutoTuneResponse();
    const fold = {
      train: response.split.train,
      validation: response.split.validation,
      metrics: segmentMetrics,
      score: 0.5,
    };
    response.walkForward = {
      folds: [fold, fold],
      aggregation: 'median_objective_minus_population_stddev',
      parameterSource: 'latest_fold',
      minimumExtraValidationBars: 270,
    };
    const confidence = {
      available: true,
      reason: null,
      method: 'circular_block_bootstrap',
      confidenceLevel: 0.95,
      bars: 480,
      blockLength: 8,
      resamples: 400,
      validResamples: 400,
      sharpeCiLower: -0.4,
      sharpeCiUpper: 1.7,
      positiveSharpeFraction: 0.75,
    };
    response.strategies[0] = {
      ...response.strategies[0],
      validationScore: 0.5,
      validationScoreDispersion: 0.1,
      validationPositiveFolds: 1,
      validationEligibleFolds: 2,
      validationWorstCagrPct: -4,
      validationFolds: [fold, fold],
      testConfidence: confidence,
    };
    response.strategies[1].testConfidence = {
      ...confidence,
      available: false,
      reason: 'insufficient_trades',
      sharpeCiLower: null,
      sharpeCiUpper: null,
      positiveSharpeFraction: null,
    };
    response.recommended.reasonCode = 'insufficient_validation_trades';
    vi.mocked(stocksApi.autoTune).mockResolvedValue(response);
    renderChart();
    fireEvent.click(await screen.findByRole('button', { name: 'Auto Tune' }));
    await screen.findAllByText('Baseline A');
    expect(screen.getByText(/Selection uses 2 chronological/)).toBeInTheDocument();
    expect(screen.getByText(/Positive validation folds 1\/2/)).toHaveTextContent('Worst validation CAGR -4%');
    expect(screen.getByText(/No validation fold meets the trade minimum/)).toBeInTheDocument();
    expect(screen.getByTestId('test-confidence')).toHaveTextContent('95% block bootstrap interval: -0.4 to 1.7');
    expect(screen.getByTestId('test-confidence')).toHaveTextContent('It is not a probability of future profit');
    const secondRow = screen.getAllByText('Trend B').find((el) => el.closest('tr'))!.closest('tr')!;
    fireEvent.click(secondRow);
    expect(screen.getByTestId('test-confidence')).toHaveTextContent('Insufficient final-test evidence');
    expect(screen.getByTestId('test-confidence')).not.toHaveTextContent('95%');
  });

  it('shows selected strategy execution markers on the technical chart', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    const response: AutoTuneResponse = buildAutoTuneResponse();
    const dates = indicatorDates;
    response.testPrices = { dates, values: dates.map((_, i) => 100 + i) };
    response.strategies.forEach((strategy, i) => {
      strategy.testEquity = { dates, values: dates.map((_, index) => index + i) };
      strategy.validationScore = i;
      strategy.testDecisions = [
        { signalDate: dates[0], date: dates[1], side: i ? 'sell' : 'buy',
          status: 'executed', reason: i ? 'stop' : 'signal', suggestedBudgetPct: 50, executedBudgetPct: 50,
          cashAfterPct: 50, holdingPct: i ? 0 : 50, tradeNavPct: 50, executionPrice: 101, score: i ? null : 7 },
        { signalDate: dates[1], date: dates[2], side: 'buy', status: 'executed', reason: 'signal',
          suggestedBudgetPct: 5, executedBudgetPct: 5, cashAfterPct: 45, holdingPct: 55, tradeNavPct: 5,
          executionPrice: 102, score: 6 },
      ];
    });
    vi.mocked(stocksApi.autoTune).mockResolvedValue(response);
    renderChart();
    fireEvent.click(await screen.findByRole('button', { name: 'Auto Tune' }));
    const chart = await screen.findByRole('img', { name: 'Technical indicators' });
    expect(within(chart).getByRole('img', { name: /2026-03-02.*BUY.*50\.0%, 7 \(50\.0%\)/ })).toBeInTheDocument();
    expect(within(chart).getByText('50.0%, 7 (50.0%)')).toBeInTheDocument();
    expect(within(chart).queryByRole('img', { name: /2026-03-03.*5\.0%, 6/ })).not.toBeInTheDocument();
    expect(within(chart).queryByText('S 7')).not.toBeInTheDocument();

    const strategySelect = screen.getByTestId('trigger-strategy-select');
    fireEvent.change(strategySelect, { target: { value: 'trend' } });
    expect(within(chart).getByRole('img', { name: /2026-03-02.*SELL.*50\.0%, — \(0\.0%\)/ })).toBeInTheDocument();
    expect(within(chart).queryByText('50.0%, 7 (50.0%)')).not.toBeInTheDocument();
    const before = strategyPresentation(response, 'trend');
    response.strategies[0].testEquity!.values.fill(10000);
    expect(strategyPresentation(response, 'trend').legacy?.key).toBe(before.legacy?.key);
    expect(before.curve.at(-1)?.strategyNav).toBeCloseTo(1 + response.strategies[1].testEquity!.values.at(-1)! / 100);
    expect(screen.getAllByTestId('strategy-nav-chart')).toHaveLength(1);
  });

  it('draws the ACES line even when selection fields miss every policy name', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    const response: AutoTuneResponse = buildAutoTuneResponse();
    const metrics: AllocationMetrics = { ...segmentMetrics, targetCagr: .3, initialNav: 1, finalNav: 1.1,
      tradeCount: 2, turnover: 1, averageExposurePct: 80, transactionCost: 0, allocationDecisions: 2,
      budgetConstrainedDecisions: 0, lowSampleFallbacks: 0, fallbackPct: 0 };
    response.aces = { strategyKey: 'G', version: 1, selectedPolicy: null, selectionBasis: 'validation',
      simulationMode: 'TUNED', simulationStatus: 'COMPLETED', inspectedOnly: true, config: {}, liveEnabled: false,
      readiness: { status: 'WARN', checks: {} }, qTable: [], uniqueStatesVisited: 0,
      policies: [{ name: 'Q_LEARNING', transitions: [], executions: [],
        metrics: { train: metrics, validation: metrics, test: metrics },
        testEquity: { dates: equityDates, values: [0, 1, 2, 3, 4] },
        economicCurve: equityDates.map((date, i) => ({ date, strategyNav: 1 + i / 10,
          benchmarkNav: 1 + i / 20, requiredNav: 1 + i / 15, cagrDeficit: 0 })),
      }] };
    expect(strategyPresentation(response, 'aces').policy?.name).toBe('Q_LEARNING');
    expect(combinedStrategyCurves(response, ['baseline', 'trend', 'multifactor', 'budget', 'aces']).rows
      .some(row => row['nav:aces'] != null)).toBe(true);
    vi.mocked(stocksApi.autoTune).mockResolvedValue(response);
    renderChart();
    fireEvent.click(await screen.findByRole('button', { name: 'Auto Tune' }));
    await screen.findByTestId('strategy-combined-chart');
    // Recharts legends don't render text in jsdom, so the observable signal
    // for a drawn ACES line is its absence from the missing-curve note.
    const combined = screen.getByTestId('strategy-combined-chart');
    expect(combined).toHaveTextContent('No saved curve for');
    expect(combined).toHaveTextContent('Adaptive Budget (NO_RESULT)');
    expect(combined).not.toHaveTextContent('ACES');
  });

  it('lists families without a saved curve instead of hiding them', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    renderChart();
    fireEvent.click(await screen.findByRole('button', { name: 'Auto Tune' }));
    await screen.findByTestId('strategy-combined-chart');
    expect(screen.getByTestId('strategy-combined-chart')).toHaveTextContent('No saved curve for');
    expect(screen.getByTestId('strategy-combined-chart')).toHaveTextContent('ACES (ACES_NOT_RUN)');
  });

  it('hides the holding toggle when the stock is not in current positions', async () => {
    renderChart();
    await runAutoTuneAndGetPlot();
    expect(screen.queryByTestId('holding-anchor-toggle')).not.toBeInTheDocument();
  });

  it('anchors all NAV lines at the holding buy date when the toggle is on', async () => {
    window.localStorage.setItem(CURRENT_POSITIONS_STORAGE_KEY, JSON.stringify([
      { id: 'other', code: 'AAPL', name: 'Apple', purchaseDate: '2024-01-02', purchasePrice: 200, quantity: 5, account: 'Robinhood' },
      { id: 'mine', code: 'sh600519', name: '贵州茅台', purchaseDate: '2024-06-03', purchasePrice: 100, quantity: 10, account: 'Robinhood' },
    ]));
    renderChart();
    await runAutoTuneAndGetPlot();

    const toggle = screen.getByTestId('holding-anchor-toggle');
    expect(toggle).toHaveTextContent('自持仓 2024-06-03 起');
    expect(toggle).toHaveAttribute('aria-pressed', 'false');
    fireEvent.click(toggle);
    // Toggling moves the card to the standalone slot, so re-query it.
    const anchoredToggle = screen.getByTestId('holding-anchor-toggle');
    expect(anchoredToggle).toHaveAttribute('aria-pressed', 'true');
    expect(anchoredToggle).toHaveTextContent('已锚定 2024-06-03');
    const combined = screen.getByTestId('strategy-combined-chart');
    expect(combined).toHaveTextContent('自 2024-06-03 起 · 3 根');
    expect(combined).toHaveTextContent('按 1.0 起算');
    fireEvent.click(anchoredToggle);
    expect(screen.getByTestId('holding-anchor-toggle')).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByTestId('strategy-combined-chart')).toHaveTextContent('最近 180 根');
  });

  it('marks each current-position bought point on the price chart line', async () => {
    window.localStorage.setItem(CURRENT_POSITIONS_STORAGE_KEY, JSON.stringify([
      { id: 'early', code: '600519', name: '贵州茅台', purchaseDate: '2026-03-02', purchasePrice: 107, quantity: 10, account: 'Robinhood' },
      { id: 'late', code: '600519', name: '贵州茅台', purchaseDate: '2026-03-05', purchasePrice: 112, quantity: 5, account: 'HSA' },
    ]));
    renderChart();
    await screen.findByRole('img', { name: '技术指标' });

    const markers = screen.getAllByTestId('holding-buy-marker');
    expect(markers).toHaveLength(2);
    expect(markers[0]).toHaveAttribute('aria-label', '2026-03-02 · 持仓买入 @107');
    expect(markers[1]).toHaveAttribute('aria-label', '2026-03-05 · 持仓买入 @112');
    expect(screen.getByTestId('trigger-legend')).toHaveTextContent('持仓买入');
  });

  it('shows no bought-point marker when the holding starts after the chart range', async () => {
    window.localStorage.setItem(CURRENT_POSITIONS_STORAGE_KEY, JSON.stringify([
      { id: 'future', code: '600519', name: '贵州茅台', purchaseDate: '2026-04-01', purchasePrice: 120, quantity: 10, account: 'Robinhood' },
    ]));
    renderChart();
    await screen.findByRole('img', { name: '技术指标' });

    expect(screen.queryByTestId('holding-buy-marker')).not.toBeInTheDocument();
    expect(screen.getByTestId('trigger-legend')).not.toHaveTextContent('持仓买入');
  });

  it('remembers trigger toggles separately for each stock', async () => {
    window.localStorage.setItem(
      visibleTriggersStorageKey('600519'),
      JSON.stringify({ macd: true, obv: false, kdj: false, rsi: false, boll: false, cci: false,
        dmi: false, mfi: false, compositeBuy: true, compositeSell: false }),
    );
    const rendered = render(
      <UiLanguageProvider>
        <StockIndicatorChart stockCode="600519" stockName="贵州茅台" />
      </UiLanguageProvider>,
    );
    await screen.findByRole('button', { name: 'Auto Tune' });
    expect(screen.getByRole('button', { name: 'MACD' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'SELL' })).toHaveAttribute('aria-pressed', 'false');

    fireEvent.click(screen.getByRole('button', { name: 'BOLL' }));
    expect(JSON.parse(window.localStorage.getItem(visibleTriggersStorageKey('600519'))!).boll).toBe(true);

    rendered.rerender(
      <UiLanguageProvider>
        <StockIndicatorChart stockCode="AAPL" />
      </UiLanguageProvider>,
    );
    expect(screen.getByRole('button', { name: 'MACD' })).toHaveAttribute('aria-pressed', 'false');

    rendered.rerender(
      <UiLanguageProvider>
        <StockIndicatorChart stockCode="600519" stockName="贵州茅台" />
      </UiLanguageProvider>,
    );
    expect(screen.getByRole('button', { name: 'MACD' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('button', { name: 'BOLL' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('keeps the NAV card stacked under the price chart in holding view', async () => {
    window.localStorage.setItem(CURRENT_POSITIONS_STORAGE_KEY, JSON.stringify([
      { id: 'mine', code: '600519', name: '贵州茅台', purchaseDate: '2024-06-03', purchasePrice: 100, quantity: 10, account: 'Robinhood' },
    ]));
    renderChart();
    await runAutoTuneAndGetPlot();

    const stacked = () => document.querySelector('.order-1 [data-testid="strategy-combined-chart"]');
    expect(stacked()).not.toBeNull();
    expect(document.querySelector('.order-4 [data-testid="strategy-combined-chart"]')).toBeNull();

    // The card stays stacked when the holding view turns on: no position shift.
    fireEvent.click(screen.getByTestId('holding-anchor-toggle'));
    expect(screen.getByTestId('holding-anchor-toggle')).toHaveAttribute('aria-pressed', 'true');
    expect(stacked()).not.toBeNull();
    expect(document.querySelector('.order-4 [data-testid="strategy-combined-chart"]')).toBeNull();

    fireEvent.click(screen.getByTestId('holding-anchor-toggle'));
    expect(stacked()).not.toBeNull();
    expect(document.querySelector('.order-4 [data-testid="strategy-combined-chart"]')).toBeNull();
  });

  it('steps BOL constant and MACD triggers by 0.1', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    renderChart();
    await screen.findByRole('img', { name: 'Technical indicators' });
    expect(screen.getByLabelText('BOL constant')).toHaveAttribute('step', '0.1');
    expect(screen.getByLabelText('MACD Buy')).toHaveAttribute('step', '0.1');
    expect(screen.getByLabelText('MACD Sell')).toHaveAttribute('step', '0.1');
    expect(screen.getByLabelText('KDJ Buy')).toHaveAttribute('step', 'any');
  });

  it('reads as one chart: header row on top, NAV info below the NAV plot', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    renderChart();
    const priceChart = await screen.findByRole('img', { name: 'Technical indicators' });
    // No legend toggle: the legend always shows, and the toggles stay in one
    // scrollable row.
    expect(screen.queryByRole('button', { name: /Legend/ })).not.toBeInTheDocument();
    const legend = screen.getByTestId('trigger-legend');
    expect(legend.compareDocumentPosition(priceChart) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(legend.closest('.order-1')).toBeNull();
    // The price section is always expanded: its label is plain text.
    expect(screen.getByText('Technical indicator price chart').tagName).toBe('P');
    // The composite score panel sits above the price plot as well.
    const compositeTitle = screen.getByText('Composite score');
    expect(compositeTitle.compareDocumentPosition(priceChart) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

    fireEvent.click(await screen.findByRole('button', { name: 'Auto Tune' }));
    const combined = await screen.findByTestId('strategy-combined-chart');
    // The NAV card stacks chart-first via flex order: plot on top, info below.
    expect(combined.className).toContain('flex-col');
    const navChart = within(combined).getByTestId('strategy-nav-chart');
    expect(navChart.className).toContain('order-1');
    const navHeader = within(combined).getByRole('heading', { name: 'Adaptive budget / NAV' }).closest('div')!;
    expect(navHeader.className).toContain('order-3');
    // The strategy description sits right below the NAV plot.
    expect(navChart.nextElementSibling).toHaveTextContent('2 available strategies are shown together');
  });

  it('fits the expanded legend to the section width and thins date ticks on narrow plots', async () => {
    renderChart();
    await screen.findByRole('img', { name: '技术指标' });
    // The legend panel spans the full section width below the single header
    // row instead of squeezing beside the title, so the expanded legend never
    // overflows sideways.
    const legend = screen.getByTestId('trigger-legend');
    expect(legend.closest('.home-panel-card')).not.toBeNull();
    expect(legend.closest('.order-1')).toBeNull();
    expect(legend.closest('details')).toBeNull();
    expect(selectDateTickCount(390)).toBe(3);
    expect(selectDateTickCount(1280)).toBe(7);
  });

  it('shares one middle date axis between the stacked charts', async () => {
    const response = buildAutoTuneResponse();
    response.strategies.forEach(strategy => {
      strategy.testEquity = { dates: indicatorDates, values: indicatorDates.map((_, index) => index) };
    });
    vi.mocked(stocksApi.autoTune).mockResolvedValue(response);
    renderChart();
    const priceChart = await screen.findByRole('img', { name: '技术指标' });
    // No Auto Tune result yet: the price chart keeps its own date row.
    expect(within(priceChart).getByText('2026-03-01')).toBeInTheDocument();
    expect(screen.queryByTestId('shared-date-axis')).not.toBeInTheDocument();

    fireEvent.click(await screen.findByRole('button', { name: 'Auto Tune' }));
    await screen.findByTestId('strategy-combined-chart');
    const axis = screen.getByTestId('shared-date-axis');
    expect(axis).toHaveTextContent('2026-03-01');
    expect(axis).toHaveTextContent('2026-03-06');
    // The price SVG hides its own date row while sharing.
    expect(within(priceChart).queryByText('2026-03-01')).not.toBeInTheDocument();
  });

  it('keeps separate axes in the anchored holding view', async () => {
    window.localStorage.setItem(CURRENT_POSITIONS_STORAGE_KEY, JSON.stringify([
      { id: 'mine', code: '600519', name: '贵州茅台', purchaseDate: '2024-06-03', purchasePrice: 100, quantity: 10, account: 'Robinhood' },
    ]));
    renderChart();
    await runAutoTuneAndGetPlot();
    expect(screen.queryByTestId('shared-date-axis')).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId('holding-anchor-toggle'));
    expect(screen.queryByTestId('shared-date-axis')).not.toBeInTheDocument();
    const priceChart = screen.getByRole('img', { name: '技术指标' });
    expect(within(priceChart).getByText('2026-03-01')).toBeInTheDocument();
  });

  it('filters price-chart strategy markers to the holding period when anchored', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    window.localStorage.setItem(CURRENT_POSITIONS_STORAGE_KEY, JSON.stringify([
      { id: 'mine', code: '600519', name: 'Kweichow Moutai', purchaseDate: '2026-03-03', purchasePrice: 100, quantity: 10, account: 'Robinhood' },
    ]));
    const response: AutoTuneResponse = buildAutoTuneResponse();
    const dates = indicatorDates;
    response.strategies[0].testDecisions = [
      { signalDate: dates[0], date: dates[1], side: 'buy', status: 'executed', reason: 'signal',
        suggestedBudgetPct: 50, executedBudgetPct: 50, cashAfterPct: 50, holdingPct: 50, tradeNavPct: 50,
        executionPrice: 101, score: 7 },
      { signalDate: dates[2], date: dates[3], side: 'sell', status: 'executed', reason: 'stop',
        suggestedBudgetPct: 50, executedBudgetPct: 50, cashAfterPct: 100, holdingPct: 0, tradeNavPct: 40,
        executionPrice: 110, score: null },
    ];
    vi.mocked(stocksApi.autoTune).mockResolvedValue(response);
    renderChart();
    fireEvent.click(await screen.findByRole('button', { name: 'Auto Tune' }));
    const priceChart = await screen.findByRole('img', { name: 'Technical indicators' });
    const strategyMarkers = () => within(priceChart).getAllByRole('img')
      .filter((node) => node.getAttribute('data-testid') !== 'holding-buy-marker');
    expect(strategyMarkers()).toHaveLength(2);
    // The current-position bought point stays on the line either way.
    expect(screen.getByTestId('holding-buy-marker')).toHaveAccessibleName(/2026-03-03/);

    fireEvent.click(screen.getByTestId('holding-anchor-toggle'));
    const anchoredMarkers = strategyMarkers();
    expect(anchoredMarkers).toHaveLength(1);
    expect(anchoredMarkers[0]).toHaveAccessibleName(/SELL/);
    expect(screen.getByTestId('holding-buy-marker')).toHaveAccessibleName(/2026-03-03/);
  });

  it('detects the earliest lot and rebases every series from the buy date', () => {
    window.localStorage.setItem(CURRENT_POSITIONS_STORAGE_KEY, JSON.stringify([
      { id: 'late', code: '600519', name: '贵州茅台', purchaseDate: '2024-09-02', purchasePrice: 110, quantity: 5, account: 'Robinhood' },
      { id: 'early', code: '600519', name: '贵州茅台', purchaseDate: '2024-03-01', purchasePrice: 90, quantity: 5, account: '401K' },
    ]));
    const holding = findHoldingAnchor('600519');
    expect(holding).toMatchObject({ purchaseDate: '2024-03-01', purchasePrice: 90 });
    expect(findHoldingAnchor('AAPL')).toBeNull();

    const rows = [
      { date: '2024-01-02', 'nav:baseline': 1, 'nav:trend': 1, benchmarkNav: 1, requiredNav: 1 },
      { date: '2024-03-01', 'nav:baseline': 1.1, 'nav:trend': 1.2, benchmarkNav: 1.05, requiredNav: 1.1 },
      { date: '2024-06-03', 'nav:baseline': 1.21, 'nav:trend': null, benchmarkNav: null, requiredNav: 1.2 },
    ];
    const anchored = rebaseRowsFromPurchaseDate(rows, '2024-03-01');
    expect(anchored.anchorDate).toBe('2024-03-01');
    expect(anchored.rows).toHaveLength(2);
    expect(anchored.rows[0]['nav:baseline']).toBeCloseTo(1);
    expect(anchored.rows[1]['nav:baseline']).toBeCloseTo(1.1);
    expect(anchored.rows[0]['nav:trend']).toBeCloseTo(1);
    expect(anchored.rows[1]['nav:trend']).toBeNull();
    expect(anchored.rows[0].benchmarkNav).toBeCloseTo(1);

    expect(rebaseRowsFromPurchaseDate(rows, '2026-01-01')).toEqual({ rows: [], anchorDate: null });
    const fromStart = rebaseRowsFromPurchaseDate(rows, '2020-01-01');
    expect(fromStart.anchorDate).toBe('2024-01-02');
    expect(fromStart.rows).toHaveLength(3);
  });

  it('draws composite signals hollow and OBV as diamonds so they differ from strategy triangles', async () => {
    renderChart();
    const chart = await screen.findByRole('img', { name: '技术指标' });
    // The default-on composite BUY signal must be hollow, unlike filled
    // strategy execution triangles.
    const hollowTriangles = chart.querySelectorAll('polygon[fill="none"]');
    expect(hollowTriangles.length).toBeGreaterThan(0);
    expect(hollowTriangles[0].getAttribute('stroke')).toBe('#1faa3a');

    fireEvent.click(screen.getByRole('button', { name: 'OBV' }));
    const diamonds = Array.from(chart.querySelectorAll('polygon')).filter(
      (node) => (node.getAttribute('points') ?? '').trim().split(/\s+/).length === 4,
    );
    expect(diamonds.length).toBeGreaterThan(0);
    expect(diamonds[0].getAttribute('fill')).toBe('#1faa3a');

    fireEvent.click(screen.getByRole('button', { name: 'BOLL' }));
    expect(chart.querySelector('circle[fill="none"]')?.getAttribute('stroke')).toBe('#7c3aed');
  });

  it('matches legend swatches to the disambiguated marker glyphs', async () => {
    renderChart();
    await screen.findByRole('button', { name: 'Auto Tune' });
    const obvBuy = screen.getByText('OBV 买入触发').closest('span')!;
    expect(obvBuy.querySelector('span')).toHaveStyle({ transform: 'rotate(45deg)' });
    const compositeBuy = screen.getByText('复合 BUY 信号').closest('span')!;
    expect(compositeBuy.querySelector('span')?.getAttribute('style')).toContain('webkit-text-stroke');
  });

  it('colors trade sides correctly, groups by side, and filters to the holding period', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    window.localStorage.setItem(CURRENT_POSITIONS_STORAGE_KEY, JSON.stringify([
      { id: 'mine', code: '600519', name: 'Kweichow Moutai', purchaseDate: '2024-06-03', purchasePrice: 100, quantity: 10, account: 'Robinhood' },
    ]));
    const response: AutoTuneResponse = buildAutoTuneResponse();
    response.strategies[0].testDecisions = [
      { signalDate: '2024-02-01', date: '2024-03-01', side: 'buy', status: 'executed', reason: 'signal',
        suggestedBudgetPct: 50, executedBudgetPct: 50, cashAfterPct: 50, holdingPct: 50, tradeNavPct: 50,
        executionPrice: 90, score: 7 },
      { signalDate: '2024-08-01', date: '2024-09-02', side: 'sell', status: 'executed', reason: 'stop',
        suggestedBudgetPct: 50, executedBudgetPct: 50, cashAfterPct: 100, holdingPct: 0, tradeNavPct: 40,
        executionPrice: 110, score: null },
    ];
    vi.mocked(stocksApi.autoTune).mockResolvedValue(response);
    renderChart();
    fireEvent.click(await screen.findByRole('button', { name: 'Auto Tune' }));
    const combined = await screen.findByTestId('strategy-combined-chart');

    expect(combined).toHaveTextContent('Executed trade details (2)');
    expect(combined).toHaveTextContent('BUY (1)');
    expect(combined).toHaveTextContent('SELL (1)');
    const buySide = within(combined).getByText('BUY', { selector: 'span' });
    expect(buySide).toHaveStyle({ color: '#1faa3a' });
    const sellSide = within(combined).getByText('SELL', { selector: 'span' });
    expect(sellSide).toHaveStyle({ color: '#d62728' });

    fireEvent.click(screen.getByTestId('holding-anchor-toggle'));
    const anchored = screen.getByTestId('strategy-combined-chart');
    expect(anchored).toHaveTextContent('Executed trade details (1)');
    expect(anchored).toHaveTextContent('holding since 2024-06-03');
    expect(anchored).toHaveTextContent('SELL (1)');
    expect(anchored).not.toHaveTextContent('BUY (1)');
  });

  it('pairs each sell with the latest buy and sorts chronologically', () => {
    const marks = withTradePnL([
      { date: '2024-09-02', side: 'SELL', price: 99, reason: 'stop', status: 'executed', budget: 40 },
      { date: '2024-06-03', side: 'BUY', price: 95, reason: 'signal', status: 'executed', budget: 30 },
      { date: '2024-03-01', side: 'BUY', price: 90, reason: 'signal', status: 'executed', budget: 50 },
      { date: '2024-01-02', side: 'SELL', price: 100, reason: 'stop', status: 'executed', budget: 40 },
    ]);
    expect(marks.map(mark => mark.date)).toEqual(['2024-01-02', '2024-03-01', '2024-06-03', '2024-09-02']);
    expect(marks[0].pnlPct).toBeNull();
    expect(marks[1].pnlPct).toBeNull();
    expect(marks[2].pnlPct).toBeNull();
    expect(marks[3].pnlPct).toBeCloseTo((99 / 95 - 1) * 100);
  });

  it('does not present the mandatory segment-end liquidation as a sell trigger', () => {
    const response = buildAutoTuneResponse();
    const strategy = response.strategies[0] as AutoTuneStrategyResult;
    strategy.testDecisions = [
      { signalDate: '2026-03-05', date: '2026-03-06', side: 'buy', status: 'executed', reason: 'signal',
        suggestedBudgetPct: 50, executedBudgetPct: 50, cashAfterPct: 50, holdingPct: 50, tradeNavPct: 50,
        executionPrice: 100, score: 7 },
      { signalDate: '2026-03-10', date: '2026-03-10', side: 'sell', status: 'executed', reason: 'segment_end',
        suggestedBudgetPct: 50, executedBudgetPct: 50, cashAfterPct: 100, holdingPct: 0, tradeNavPct: 50,
        executionPrice: 101, score: null },
    ];

    expect(strategyPresentation(response, 'baseline').marks.filter(isVisibleTradeMark)).toHaveLength(1);
    expect(strategyPresentation(response, 'baseline').marks.filter(isVisibleTradeMark)[0].side).toBe('BUY');
  });

  it('orders trade details by date with price and colored P/L, and dots trades on the NAV line', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    const response: AutoTuneResponse = buildAutoTuneResponse();
    response.strategies[0].testDecisions = [
      { signalDate: '2024-08-01', date: '2024-09-02', side: 'sell', status: 'executed', reason: 'stop',
        suggestedBudgetPct: 50, executedBudgetPct: 50, cashAfterPct: 100, holdingPct: 0, tradeNavPct: 40,
        executionPrice: 99, score: null },
      { signalDate: '2024-05-01', date: '2024-06-03', side: 'buy', status: 'executed', reason: 'signal',
        suggestedBudgetPct: 30, executedBudgetPct: 30, cashAfterPct: 70, holdingPct: 30, tradeNavPct: 30,
        executionPrice: 95, score: 6 },
      { signalDate: '2024-02-01', date: '2024-03-01', side: 'buy', status: 'executed', reason: 'signal',
        suggestedBudgetPct: 50, executedBudgetPct: 50, cashAfterPct: 50, holdingPct: 50, tradeNavPct: 50,
        executionPrice: 90, score: 7 },
    ];
    vi.mocked(stocksApi.autoTune).mockResolvedValue(response);
    renderChart();
    fireEvent.click(await screen.findByRole('button', { name: 'Auto Tune' }));
    const combined = await screen.findByTestId('strategy-combined-chart');

    expect(combined).toHaveTextContent('Executed trade details (3)');
    const text = combined.textContent ?? '';
    expect(text.indexOf('2024-03-01')).toBeLessThan(text.indexOf('2024-06-03'));
    expect(combined).toHaveTextContent('@90.00');
    expect(combined).toHaveTextContent('@99.00');
    // Sell P/L is measured against the latest buy: 99/95-1 = +4.2%.
    expect(combined).toHaveTextContent('+4.2%');
    expect(combined).toHaveTextContent('excluding fees');

    // NAV trade dots pin each executed mark to the baseline NAV value and
    // skip dates outside the displayed rows.
    const rows = combinedStrategyCurves(response, ['baseline']).rows;
    const ordered = withTradePnL(strategyPresentation(response, 'baseline').marks);
    const dots = navTradeDots(rows, ordered, 'baseline');
    expect(dots).toHaveLength(3);
    expect(dots[0]).toMatchObject({ date: '2024-03-01', side: 'BUY' });
    expect(dots[0].nav).toBeCloseTo(1 + 2.5 / 100);
    expect(dots[2]).toMatchObject({ date: '2024-09-02', side: 'SELL' });
    expect(navTradeDots(rows.slice(0, 1), strategyPresentation(response, 'baseline').marks, 'baseline')).toEqual([]);
  });

  it('shows trigger thresholds expanded with restore next to the title', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    renderChart();
    await screen.findByRole('button', { name: 'Auto Tune' });
    const title = screen.getByText('Trigger thresholds');
    expect(title.tagName).toBe('SPAN');
    expect(title.closest('details')).toBeNull();
    const titleRow = screen.getByRole('button', { name: 'Restore defaults' }).closest('div')!;
    expect(titleRow.textContent).toContain('Trigger thresholds');
    expect(screen.getByText('Advanced tuning settings').closest('details')).not.toHaveAttribute('open');
  });

  it.each(['TUNED', 'PRESET'] as const)('shows losing ACES results despite research rejection (%s)', async (mode) => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    const response: AutoTuneResponse = buildAutoTuneResponse();
    const dates = indicatorDates;
    response.testPrices = { dates, values: dates.map(() => 100) };
    const metrics: AllocationMetrics = { ...segmentMetrics, totalReturnPct: -2, targetCagr: .3, initialNav: 1, finalNav: .98,
      tradeCount: 1, turnover: 1, averageExposurePct: 100, transactionCost: 0, allocationDecisions: 2,
      budgetConstrainedDecisions: 1, lowSampleFallbacks: 1, fallbackPct: 50 };
    const blocked = { triggerDate: dates[2], executionDate: dates[3], triggerDirection: 'BUY', triggerScore: 8,
      execution: null, portfolioBefore: { lastPrice: 100, currentExposure: 1 }, executionReason: 'NO_CASH',
      policyReason: 'LOW_SAMPLE_FALLBACK' } as AllocationTransition;
    response.aces = { strategyKey: 'G', version: 1, selectedPolicy: null, inspectedPolicy: mode === 'PRESET' ? 'FIXED' : 'Q_LEARNING',
      simulationMode: mode, simulationStatus: 'COMPLETED',
      inspectedOnly: true, selectionBasis: 'validation', config: {}, liveEnabled: false,
      readiness: { status: 'FAIL', checks: { stress: false } }, qTable: [], uniqueStatesVisited: 1,
      policies: (mode === 'PRESET' ? ['FIXED'] : ['FIXED', 'Q_LEARNING']).map(name => ({ name,
        metrics: { train: mode === 'PRESET' ? null : metrics, validation: mode === 'PRESET' ? null : metrics, test: metrics },
        testEquity: { dates, values: dates.map(() => name === 'FIXED' ? 90 : -2) }, transitions: [blocked],
        economicCurve: dates.map(date => ({ date, strategyNav: .98, benchmarkNav: 1.1, requiredNav: 1.2, cagrDeficit: .1 })),
        executions: [{ date: dates[1], reason: 'signal', side: 'BUY', tradeValue: 1, transactionCost: 0, nav: 1,
          executionPrice: 100, holdingPct: 100, tradeNavPct: 100, score: 7 }],
      })) };
    vi.mocked(stocksApi.autoTune).mockResolvedValue(response);
    renderChart();
    fireEvent.click(await screen.findByRole('button', { name: 'Auto Tune' }));
    await screen.findByTestId('strategy-combined-chart');
    const strategySelect = screen.getByTestId('trigger-strategy-select') as HTMLSelectElement;
    fireEvent.change(strategySelect, { target: { value: 'aces' } });
    await waitFor(() => expect(screen.getByTestId('strategy-combined-chart')).toHaveTextContent('ACES'));
    expect(await screen.findAllByText(/Backtest completed/)).not.toHaveLength(0);
    expect(screen.queryByText(/ACES FAIL/)).not.toBeInTheDocument();
    expect(screen.getByText('Return: -2.0%')).toBeInTheDocument();
    expect(strategyPresentation(response, 'aces').policy?.name).toBe(mode === 'PRESET' ? 'FIXED' : 'Q_LEARNING');
    expect(screen.getByRole('img', { name: /2026-03-02.*BUY.*100\.0%, 7 \(100\.0%\)/ })).toBeInTheDocument();
    expect(screen.getAllByTestId('strategy-nav-chart')).toHaveLength(1);
  });

  it('keeps indicator trigger toggles alongside the strategy select', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    renderChart();
    await screen.findByRole('button', { name: 'Auto Tune' });

    const strategySelect = screen.getByTestId('trigger-strategy-select') as HTMLSelectElement;
    expect(strategySelect).toBeEnabled();
    expect(Array.from(strategySelect.options).map(option => option.textContent)).toEqual([
      'Baseline', 'Trend', 'Multi-factor', 'Adaptive Budget', 'ACES', 'MATR · Macro Router',
    ]);
    expect(screen.getByTestId('trigger-toggles').className).toContain('flex-nowrap');
    expect(screen.getByTestId('trigger-legend')).toBeInTheDocument();
    expect(screen.getByText('BOLL Buy Trigger')).toBeInTheDocument();
    expect(screen.getByText('Composite BUY Signal')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'BOLL' })).toHaveAttribute('aria-pressed', 'false');
    expect(screen.getByRole('button', { name: 'BUY' })).toHaveAttribute('aria-pressed', 'true');
  });

  it('shows extension factors in the composite breakdown with a dynamic max score', async () => {
    renderChart();
    await screen.findByRole('button', { name: 'Auto Tune' });

    const scoreNodes = screen.getAllByText((_content, el) => el?.textContent === 'BUY: 9/12');
    expect(scoreNodes.length).toBe(1);

    fireEvent.click(screen.getByRole('button', { name: '明细' }));
    for (const label of ['MACD', 'KDJ', 'RSI', '趋势', '动量', 'BOLL', 'CCI', 'DMI', 'MFI', '量能', '52 周位置']) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
    // BOLL weight=2 contributes +2 to the latest buy score.
    const bollRows = screen.getAllByText('BOLL').filter((el) => el.closest('.flex.justify-between'));
    expect(bollRows.length).toBeGreaterThan(0);
    expect(bollRows[0].parentElement?.textContent).toContain('+2');
  });

  it('selects strategies by keyboard and applies the selected thresholds to the chart', async () => {
    renderChart();
    await runAutoTuneAndGetPlot();

    // Recommended (default selected) is 基线 A; ArrowDown from its row selects 趋势 B.
    const rowCell = screen.getAllByText('基线 A').find((el) => el.closest('tr'));
    expect(rowCell).toBeDefined();
    fireEvent.keyDown(rowCell!.closest('tr')!, { key: 'ArrowDown' });

    const selectedBlock = screen.getByText(/当前选中/).closest('div');
    expect(selectedBlock?.textContent).toContain('趋势 B');

    // Strategy C exposes ATR risk params; they must appear in the live display.
    const stopLabel = screen.getByText('ATR 止损倍数').closest('label');
    expect(stopLabel?.textContent).toContain('2.5');

    fireEvent.click(screen.getByRole('button', { name: '应用选中到图表' }));

    await waitFor(() => {
      const calls = vi.mocked(stocksApi.getIndicators).mock.calls;
      const lastArgs = calls.at(-1)?.[1] as Record<string, unknown> | undefined;
      expect(lastArgs?.compositeBuyThreshold).toBe(7);
      expect(lastArgs?.compositeSellThreshold).toBe(8);
    });
  });

  it('restores default thresholds on the chart', async () => {
    renderChart();
    await runAutoTuneAndGetPlot();

    fireEvent.click(screen.getByRole('button', { name: '恢复默认阈值' }));

    await waitFor(() => {
      const calls = vi.mocked(stocksApi.getIndicators).mock.calls;
      const lastArgs = calls.at(-1)?.[1] as Record<string, unknown> | undefined;
      expect(lastArgs?.compositeBuyThreshold).toBe(6);
      expect(lastArgs?.rsiLow).toBe(15);
      expect(lastArgs?.kdjLow).toBe(40);
    });
  });

  it('marks the recommended strategy row and keeps unavailable benchmarks out of the legend', async () => {
    renderChart();
    await runAutoTuneAndGetPlot();

    const rowCell = screen.getAllByText('基线 A').find((el) => el.closest('tr'));
    const row = rowCell?.closest('tr');
    expect(row).not.toBeNull();
    expect(within(row!).getByText('推荐')).toBeInTheDocument();
    expect(row?.getAttribute('aria-selected')).toBe('true');
  });

  it('supports multi-year chart ranges up to 5Y', async () => {
    renderChart();
    await screen.findByRole('button', { name: 'Auto Tune' });

    for (const label of ['2年', '3年', '4年', '5年']) {
      expect(screen.getByRole('button', { name: label })).toBeInTheDocument();
    }

    fireEvent.click(screen.getByRole('button', { name: '5年' }));
    await waitFor(() => {
      const lastArgs = vi.mocked(stocksApi.getIndicators).mock.calls.at(-1)?.[1] as
        | Record<string, unknown>
        | undefined;
      expect(lastArgs?.days).toBe(1825);
    });
  });

  it('sends test period and clipped train range when re-running auto tune', async () => {
    renderChart();
    const tuneButton = await screen.findByRole('button', { name: 'Auto Tune' });
    fireEvent.click(tuneButton);
    await screen.findAllByText('基线 A');

    // 结果头部展示实际使用的测试段长度
    expect(screen.getAllByText(/测试段 5年/).length).toBeGreaterThan(0);

    // 默认测试段为 3 年，可切换到其他年限
    const select = screen.getByDisplayValue('3年');
    fireEvent.change(select, { target: { value: '5' } });
    expect((select as HTMLSelectElement).value).toBe('5');

    // 双端滑杆裁剪训练段（千分比刻度）
    fireEvent.change(screen.getByLabelText('训练段开始日期'), { target: { value: '200' } });
    fireEvent.change(screen.getByLabelText('训练段结束日期'), { target: { value: '700' } });

    fireEvent.click(tuneButton);
    await waitFor(() => {
      const lastCall = vi.mocked(stocksApi.autoTune).mock.calls.at(-1);
      expect(lastCall?.[1]?.testYears).toBe(5);
      expect(String(lastCall?.[1]?.trainStartDate)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(String(lastCall?.[1]?.trainEndDate)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      expect(String(lastCall?.[1]?.trainStartDate) < String(lastCall?.[1]?.trainEndDate)).toBe(true);
    });
  });

  it('lets the trade window input be cleared and retyped before blur commits', async () => {
    renderChart();
    const tuneButton = await screen.findByRole('button', { name: 'Auto Tune' });

    const windowInput = screen.getByLabelText('交易窗口', { exact: false }) as HTMLInputElement;
    expect(windowInput.value).toBe('90');

    // Clearing the field must not snap back to the minimum.
    fireEvent.change(windowInput, { target: { value: '' } });
    expect(windowInput.value).toBe('');

    // Typing a fresh value then blurring commits it.
    fireEvent.change(windowInput, { target: { value: '120' } });
    fireEvent.blur(windowInput);
    expect(windowInput.value).toBe('120');

    fireEvent.click(tuneButton);
    await waitFor(() => {
      const lastCall = vi.mocked(stocksApi.autoTune).mock.calls.at(-1);
      expect(lastCall?.[1]?.windowDays).toBe(120);
    });
  });

  it('restores the default trade window when blurred while empty', async () => {
    renderChart();
    await screen.findByRole('button', { name: 'Auto Tune' });

    const windowInput = screen.getByLabelText('交易窗口', { exact: false }) as HTMLInputElement;
    fireEvent.change(windowInput, { target: { value: '' } });
    expect(windowInput.value).toBe('');
    fireEvent.blur(windowInput);
    expect(windowInput.value).toBe('90');
  });

  it('lets the history years input be cleared and retyped before blur commits', async () => {
    renderChart();
    const tuneButton = await screen.findByRole('button', { name: 'Auto Tune' });

    const yearsInput = screen.getByLabelText('历史', { exact: false }) as HTMLInputElement;
    expect(yearsInput.value).toBe('10');

    fireEvent.change(yearsInput, { target: { value: '' } });
    expect(yearsInput.value).toBe('');

    fireEvent.change(yearsInput, { target: { value: '15' } });
    fireEvent.blur(yearsInput);
    expect(yearsInput.value).toBe('15');

    fireEvent.click(tuneButton);
    await waitFor(() => {
      const lastCall = vi.mocked(stocksApi.autoTune).mock.calls.at(-1);
      expect(lastCall?.[1]?.years).toBe(15);
    });
  });

  it('notifies threshold listeners when a threshold input is committed', async () => {
    renderChart();
    await screen.findByRole('button', { name: 'Auto Tune' });

    const seen: string[] = [];
    const handler = (event: Event) => {
      seen.push((event as CustomEvent<{ stockCode: string }>).detail.stockCode);
    };
    window.addEventListener('dsa-indicator-thresholds-changed', handler);
    try {
      const buyInput = screen.getByLabelText('BUY 触发分') as HTMLInputElement;
      // Threshold edits commit on blur/Enter (typing alone only updates the
      // local draft to avoid reloading the chart on every keystroke).
      fireEvent.change(buyInput, { target: { value: '5' } });
      expect(seen).not.toContain('600519');
      fireEvent.blur(buyInput);
      expect(seen).toContain('600519');
    } finally {
      window.removeEventListener('dsa-indicator-thresholds-changed', handler);
    }
  });

  it('does not reload indicators while typing threshold drafts', async () => {
    renderChart();
    await screen.findByRole('button', { name: 'Auto Tune' });
    const callsBefore = vi.mocked(stocksApi.getIndicators).mock.calls.length;
    const buyInput = screen.getByLabelText('BUY 触发分') as HTMLInputElement;
    fireEvent.change(buyInput, { target: { value: '5' } });
    fireEvent.change(buyInput, { target: { value: '55' } });
    // Typing only updates the local draft; the chart must not reload (and
    // shift the page) on every keystroke.
    expect(vi.mocked(stocksApi.getIndicators).mock.calls.length).toBe(callsBefore);
    fireEvent.blur(buyInput);
    await waitFor(() => {
      expect(vi.mocked(stocksApi.getIndicators).mock.calls.length).toBeGreaterThan(callsBefore);
    });
    const lastArgs = vi.mocked(stocksApi.getIndicators).mock.calls.at(-1)?.[1] as Record<string, unknown>;
    expect(lastArgs?.compositeBuyThreshold).toBe(55);
  });
});
