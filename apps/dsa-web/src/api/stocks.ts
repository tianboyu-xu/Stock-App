import apiClient from './index';
import { toCamelCase } from './utils';

export type ExtractItem = {
  code?: string | null;
  name?: string | null;
  confidence: string;
};

export interface KLineData {
  date: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number | null;
  amount?: number | null;
  changePercent?: number | null;
}

export interface StockHistoryResponse {
  stockCode: string;
  stockName?: string | null;
  period: string;
  data: KLineData[];
}

export type IndicatorSeries = Array<number | null>;

export interface IndicatorTriggers {
  macdBuy: IndicatorSeries;
  macdSell: IndicatorSeries;
  kdjBuy: IndicatorSeries;
  kdjSell: IndicatorSeries;
  rsiBuy: IndicatorSeries;
  rsiSell: IndicatorSeries;
  obvBuy: IndicatorSeries;
  obvSell: IndicatorSeries;
  // Extension-factor triggers (BOLL %B / CCI / DMI / MFI). Optional so older
  // cached payloads without these groups still render.
  bollBuy?: IndicatorSeries;
  bollSell?: IndicatorSeries;
  cciBuy?: IndicatorSeries;
  cciSell?: IndicatorSeries;
  dmiBuy?: IndicatorSeries;
  dmiSell?: IndicatorSeries;
  mfiBuy?: IndicatorSeries;
  mfiSell?: IndicatorSeries;
}

export interface IndicatorThresholds {
  bolConstant: number;
  macdBuy: number;
  macdSell: number;
  kdjBuy: number;
  kdjSell: number;
  rsiBuy: number;
  rsiSell: number;
  compositeBuyThreshold: number;
  compositeSellThreshold: number;
  macdLookback: number;
  macdLowPercentile: number;
  macdHighPercentile: number;
  rsiLow: number;
  rsiHigh: number;
  kdjLow: number;
  kdjHigh: number;
  trendPeriod: number;
  bollBuyLevel?: number;
  bollSellLevel?: number;
  bollWeight?: number;
  cciBuyLevel?: number;
  cciSellLevel?: number;
  cciWeight?: number;
  adxMinLevel?: number;
  dmiWeight?: number;
  mfiBuyLevel?: number;
  mfiSellLevel?: number;
  mfiWeight?: number;
  volumeConfirmLevel?: number;
  volumeWeight?: number;
  range52HighLevel?: number;
  range52LowLevel?: number;
  range52Weight?: number;
}export interface CompositeBreakdown {
  macd: number;
  kdj: number;
  rsi: number;
  regime: number;
  momentum: number;
  boll?: number;
  cci?: number;
  dmi?: number;
  mfi?: number;
  volume?: number;
  range52?: number;
}

export interface CompositeSignals {
  buyScore: number[];
  sellScore: number[];
  buySignal: IndicatorSeries;
  sellSignal: IndicatorSeries;
  buyBreakdown: CompositeBreakdown[];
  sellBreakdown: CompositeBreakdown[];
  maxBuyScore?: number;
  maxSellScore?: number;
}

export interface StockIndicatorsResponse {
  stockCode: string;
  stockName?: string | null;
  period: string;
  dates: string[];
  close: number[];
  sma: Record<string, IndicatorSeries>;
  ema: Record<string, IndicatorSeries>;
  macd: IndicatorSeries;
  macdSignal: IndicatorSeries;
  k: IndicatorSeries;
  d: IndicatorSeries;
  j: IndicatorSeries;
  rsi: IndicatorSeries;
  rsi6: IndicatorSeries;
  rsi14: IndicatorSeries;
  bolu: IndicatorSeries;
  bold: IndicatorSeries;
  cci: IndicatorSeries;
  obv: IndicatorSeries;
  obvMa: Record<string, IndicatorSeries>;
  triggers: IndicatorTriggers;
  composite?: CompositeSignals | null;
  thresholds: IndicatorThresholds;
  benefitSeriesByTrigger?: Record<string, IndicatorSeries>;
  benefitByTrigger?: Record<string, number>;
}

export type AutoTuneSegmentKey = 'train' | 'validation' | 'test' | 'trainValidation';

export interface AutoTuneSegmentMetrics {
  totalReturnPct: number;
  cagrPct: number;
  afterTaxTotalReturnPct: number;
  afterTaxCagrPct: number;
  maxDrawdownPct: number;
  sharpe: number;
  sortino: number;
  profitFactor: number | null;
  trades: number;
  winRatePct: number;
  avgTradePct: number;
  avgHoldingDays: number;
  exposurePct: number;
  tradesPerYear: number;
}

export interface AutoTuneParams {
  thresholds: Record<string, number>;
  stopMultipleAtr: number | null;
  trailMultipleAtr: number | null;
}

export interface AutoTuneEquitySeries {
  dates: string[];
  values: number[];
}

export interface AutoTuneStrategyResult {
  key: string;
  nameZh: string;
  nameEn: string;
  descriptionZh: string;
  descriptionEn: string;
  tuned: boolean;
  params: AutoTuneParams;
  metrics: Record<AutoTuneSegmentKey | string, AutoTuneSegmentMetrics>;
  objectives: Record<string, number>;
  paramRobustness: number | null;
  testEquity: AutoTuneEquitySeries | null;
}

export interface AutoTuneBenchmarkMetrics {
  trainValidation: AutoTuneSegmentMetrics | null;
  test: AutoTuneSegmentMetrics | null;
}

export interface AutoTuneBenchmark {
  key: string;
  nameZh: string;
  nameEn: string;
  descriptionZh: string;
  descriptionEn: string;
  available: boolean;
  metrics: AutoTuneBenchmarkMetrics;
  testEquity: AutoTuneEquitySeries | null;
}

export interface AutoTuneParamDisplay {
  key: string;
  value: number;
  default: number | null;
}

export interface AutoTuneRecommended {
  strategyKey: string;
  reasonCode: string;
  eps: number;
  thresholds: Partial<IndicatorThresholds>;
  risk: {
    useTrendFilter?: boolean;
    useVolumeFilter?: boolean;
    stopMultipleAtr?: number | null;
    trailMultipleAtr?: number | null;
  };
  paramsDisplay: AutoTuneParamDisplay[];
}

export interface FineTuneSweepPosition {
  positionIndex: number;
  trainStart: string;
  trainEnd: string;
  trainBars: number;
  validationStart: string;
  validationEnd: string;
  bestStrategyKey: string;
  testCagr: number;
  testSharpe: number;
  testMaxDd: number;
  testTrades: number;
  validationScore: number;
  thresholds: Record<string, number>;
  stopMultipleAtr: number | null;
  trailMultipleAtr: number | null;
  allStrategies: AutoTuneStrategyResult[];
}

export interface FineTuneResult {
  windowDays: number;
  step: number;
  positionsTested: number;
  bestPositionIndex: number;
  sweep: FineTuneSweepPosition[];
}

export interface AutoTuneResponse {
  windowDays: number;
  history: {
    bars: number;
    startDate: string;
    endDate: string;
    yearsRequested: number;
    yearsUsed: number;
    testYearsRequested?: number;
    testYearsUsed?: number;
  };
  split: Record<string, { startDate: string; endDate: string; bars: number }>;
  assumptions: Record<string, string | number>;
  fixedParameters: { keys: string[]; reasonCode: string };
  strategies: AutoTuneStrategyResult[];
  benchmarks: AutoTuneBenchmark[];
  recommended: AutoTuneRecommended;
  fineTune?: FineTuneResult | null;
}

export type ExtractFromImageResponse = {
  codes: string[];
  items?: ExtractItem[];
  rawText?: string;
};

export const stocksApi = {
  async extractFromImage(file: File): Promise<ExtractFromImageResponse> {
    const formData = new FormData();
    formData.append('file', file);

    const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
    const response = await apiClient.post(
      '/api/v1/stocks/extract-from-image',
      formData,
      {
        headers,
        timeout: 60000, // Vision API can be slow; 60s
      },
    );

    const data = response.data as { codes?: string[]; items?: ExtractItem[]; raw_text?: string };
    return {
      codes: data.codes ?? [],
      items: data.items,
      rawText: data.raw_text,
    };
  },

  async parseImport(file?: File, text?: string): Promise<ExtractFromImageResponse> {
    if (file) {
      const formData = new FormData();
      formData.append('file', file);
      const headers: { [key: string]: string | undefined } = { 'Content-Type': undefined };
      const response = await apiClient.post('/api/v1/stocks/parse-import', formData, { headers });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    if (text) {
      const response = await apiClient.post('/api/v1/stocks/parse-import', { text });
      const data = response.data as { codes?: string[]; items?: ExtractItem[] };
      return { codes: data.codes ?? [], items: data.items };
    }
    throw new Error('请提供文件或粘贴文本');
  },

  /**
   * Fetch historical K-line data for a stock.
   * Backend: GET /api/v1/stocks/{stock_code}/history?period=daily&days=N
   */
  async getHistory(
    code: string,
    params: { period?: 'daily' | 'weekly' | 'monthly'; days?: number } = {},
  ): Promise<StockHistoryResponse> {
    const queryParams: Record<string, string | number> = { period: params.period ?? 'daily' };
    if (params.days != null) queryParams.days = params.days;
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/stocks/${encodeURIComponent(code)}/history`,
      { params: queryParams },
    );
    return toCamelCase<StockHistoryResponse>(response.data);
  },

  /**
   * Fetch computed technical indicators (Excel "300 Plot" logic).
   * Backend: GET /api/v1/stocks/{stock_code}/indicators?period=daily&days=N
   */
  async getIndicators(
    code: string,
    params: { period?: 'daily' | 'weekly' | 'monthly'; days?: number; transactionWindow?: number } & Partial<IndicatorThresholds> = {},
  ): Promise<StockIndicatorsResponse> {
    const queryParams: Record<string, string | number> = { period: params.period ?? 'daily' };
    if (params.days != null) queryParams.days = params.days;
    if (params.transactionWindow != null) queryParams.transaction_window = params.transactionWindow;
    const thresholdKeys: Array<[keyof IndicatorThresholds, string]> = [
      ['bolConstant', 'bol_constant'],
      ['macdBuy', 'macd_buy'],
      ['macdSell', 'macd_sell'],
      ['kdjBuy', 'kdj_buy'],
      ['kdjSell', 'kdj_sell'],
      ['rsiBuy', 'rsi_buy'],
      ['rsiSell', 'rsi_sell'],
      ['compositeBuyThreshold', 'composite_buy_threshold'],
      ['compositeSellThreshold', 'composite_sell_threshold'],
      ['macdLookback', 'macd_lookback'],
      ['macdLowPercentile', 'macd_low_percentile'],
      ['macdHighPercentile', 'macd_high_percentile'],
      ['rsiLow', 'rsi_low'],
      ['rsiHigh', 'rsi_high'],
      ['kdjLow', 'kdj_low'],
      ['kdjHigh', 'kdj_high'],
      ['trendPeriod', 'trend_period'],
      ['bollBuyLevel', 'boll_buy_level'],
      ['bollSellLevel', 'boll_sell_level'],
      ['bollWeight', 'boll_weight'],
      ['cciBuyLevel', 'cci_buy_level'],
      ['cciSellLevel', 'cci_sell_level'],
      ['cciWeight', 'cci_weight'],
      ['adxMinLevel', 'adx_min_level'],
      ['dmiWeight', 'dmi_weight'],
      ['mfiBuyLevel', 'mfi_buy_level'],
      ['mfiSellLevel', 'mfi_sell_level'],
      ['mfiWeight', 'mfi_weight'],
      ['volumeConfirmLevel', 'volume_confirm_level'],
      ['volumeWeight', 'volume_weight'],
      ['range52HighLevel', 'range52_high_level'],
      ['range52LowLevel', 'range52_low_level'],
      ['range52Weight', 'range52_weight'],
    ];
    for (const [key, queryKey] of thresholdKeys) {
      const value = params[key];
      if (value != null) queryParams[queryKey] = value;
    }
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/stocks/${encodeURIComponent(code)}/indicators`,
      // 多年历史请求在数据源降级重试时可能远超默认 30s，放宽到与 Auto Tune 一致
      { params: queryParams, timeout: 180000 },
    );
    return toCamelCase<StockIndicatorsResponse>(response.data);
  },

  /**
   * Auto Tune 参数寻优：基于多年历史对复合评分阈值做多代际训练/验证/测试寻优。
   * Backend: GET /api/v1/stocks/{stock_code}/auto-tune?window_days=90&years=10&test_years=5
   */
  async autoTune(
    code: string,
    params: {
      windowDays?: number;
      years?: number;
      testYears?: number;
      trainStartDate?: string;
      trainEndDate?: string;
      fineTuneWindowDays?: number;
    } = {},
  ): Promise<AutoTuneResponse> {
    const queryParams: Record<string, string | number> = {};
    if (params.windowDays != null) queryParams.window_days = params.windowDays;
    if (params.years != null) queryParams.years = params.years;
    if (params.testYears != null) queryParams.test_years = params.testYears;
    if (params.trainStartDate) queryParams.train_start_date = params.trainStartDate;
    if (params.trainEndDate) queryParams.train_end_date = params.trainEndDate;
    if (params.fineTuneWindowDays != null) queryParams.fine_tune_window_days = params.fineTuneWindowDays;
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/stocks/${encodeURIComponent(code)}/auto-tune`,
      // 个股与标普500 基准两次串行取数，数据源降级时各需 ~130s，放宽超时上限
      { params: queryParams, timeout: 300000 },
    );
    return toCamelCase<AutoTuneResponse>(response.data);
  },
};
