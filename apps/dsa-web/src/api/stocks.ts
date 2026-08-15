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
}

export interface IndicatorThresholds {
  bolConstant: number;
  macdBuy: number;
  macdSell: number;
  kdjBuy: number;
  kdjSell: number;
  rsiBuy: number;
  rsiSell: number;
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
  thresholds: IndicatorThresholds;
  benefitSeries?: IndicatorSeries;
  benefitSeriesByTrigger?: Record<string, IndicatorSeries>;
  benefitByTrigger?: Record<string, number>;
  optimization?: {
    trigger: string;
    windowDays: number;
    thresholds: IndicatorThresholds;
    accumulatedBenefitPct: number;
    transactions: Array<Record<string, unknown>>;
  } | null;
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
    params: { period?: 'daily' | 'weekly' | 'monthly'; days?: number; optimize?: boolean; trigger?: string; transactionWindow?: number } & Partial<IndicatorThresholds> = {},
  ): Promise<StockIndicatorsResponse> {
    const queryParams: Record<string, string | number> = { period: params.period ?? 'daily' };
    if (params.days != null) queryParams.days = params.days;
    if (params.optimize != null) queryParams.optimize = params.optimize ? 'true' : 'false';
    if (params.trigger != null) queryParams.trigger = params.trigger;
    if (params.transactionWindow != null) queryParams.transaction_window = params.transactionWindow;
    const thresholdKeys: Array<[keyof IndicatorThresholds, string]> = [
      ['bolConstant', 'bol_constant'],
      ['macdBuy', 'macd_buy'],
      ['macdSell', 'macd_sell'],
      ['kdjBuy', 'kdj_buy'],
      ['kdjSell', 'kdj_sell'],
      ['rsiBuy', 'rsi_buy'],
      ['rsiSell', 'rsi_sell'],
    ];
    for (const [key, queryKey] of thresholdKeys) {
      const value = params[key];
      if (value != null) queryParams[queryKey] = value;
    }
    const response = await apiClient.get<Record<string, unknown>>(
      `/api/v1/stocks/${encodeURIComponent(code)}/indicators`,
      { params: queryParams },
    );
    return toCamelCase<StockIndicatorsResponse>(response.data);
  },
};
