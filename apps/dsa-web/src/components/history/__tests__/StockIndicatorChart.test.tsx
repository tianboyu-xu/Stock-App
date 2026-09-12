import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { AUTO_TUNE_METHODOLOGY_VERSION, stocksApi, type AutoTuneResponse, type AllocationMetrics, type AllocationTransition } from '../../../api/stocks';
import { UiLanguageProvider } from '../../../contexts/UiLanguageContext';
import { UI_LANGUAGE_STORAGE_KEY } from '../../../utils/uiLanguage';
import { StockIndicatorChart } from '../StockIndicatorChart';
import { strategyPresentation } from '../autoTunePresentation';
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
      obvBuy: [null, null, null, null, null, null],
      obvSell: [null, null, null, null, null, null],
      bollBuy: [null, null, null, 110, null, null],
      bollSell: [null, null, null, null, null, null],
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

  it('shows the five strategy options and shares selection and range with the NAV chart', async () => {
    renderChart();
    await runAutoTuneAndGetPlot();

    const strategySelect = screen.getByTestId('trigger-strategy-select') as HTMLSelectElement;
    expect(strategySelect.options).toHaveLength(5);
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
    expect(lastCall?.[1]?.acesConfig).toEqual({ version: 1, enabled: true, allocation: { economic: { allowed_max_drawdown: .15 } } });
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

  it('collapses thresholds and advanced inputs by default', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    renderChart();
    await screen.findByRole('button', { name: 'Auto Tune' });
    expect(screen.getByText('Trigger thresholds').closest('details')).not.toHaveAttribute('open');
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

  it('replaces legacy indicator trigger toggles with the strategy select', async () => {
    window.localStorage.setItem(UI_LANGUAGE_STORAGE_KEY, 'en');
    renderChart();
    await screen.findByRole('button', { name: 'Auto Tune' });

    const strategySelect = screen.getByTestId('trigger-strategy-select') as HTMLSelectElement;
    expect(strategySelect).toBeDisabled();
    expect(Array.from(strategySelect.options).map(option => option.textContent)).toEqual([
      'Baseline', 'Trend', 'Multi-factor', 'Adaptive Budget', 'ACES',
    ]);
    expect(screen.queryByText('BOLL Buy Trigger')).not.toBeInTheDocument();
    expect(screen.queryByText('Composite BUY Signal')).not.toBeInTheDocument();
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

  it('notifies threshold listeners when a threshold input changes', async () => {
    renderChart();
    await screen.findByRole('button', { name: 'Auto Tune' });

    const seen: string[] = [];
    const handler = (event: Event) => {
      seen.push((event as CustomEvent<{ stockCode: string }>).detail.stockCode);
    };
    window.addEventListener('dsa-indicator-thresholds-changed', handler);
    try {
      const buyInput = screen.getByLabelText('BUY 触发分') as HTMLInputElement;
      fireEvent.change(buyInput, { target: { value: '5' } });
      expect(seen).toContain('600519');
    } finally {
      window.removeEventListener('dsa-indicator-thresholds-changed', handler);
    }
  });
});
