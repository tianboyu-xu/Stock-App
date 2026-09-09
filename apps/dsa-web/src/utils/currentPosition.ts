export const POSITION_ACCOUNT_OPTIONS = ['Robinhood', 'RSU', '401K', 'HSA'] as const;
export type PositionAccount = typeof POSITION_ACCOUNT_OPTIONS[number];

export interface CurrentPosition {
  id: string;
  code: string;
  name: string;
  market?: string;
  purchaseDate: string;
  purchasePrice: number;
  quantity: number;
  account: PositionAccount;
}

export interface CurrentPositionMetrics {
  currentValue: number | null;
  gainLossAmount: number | null;
  gainLossPct: number | null;
  afterTaxCagrPct: number | null;
  holdingDays: number | null;
  taxRatePct: number | null;
}

export const CURRENT_POSITIONS_STORAGE_KEY = 'dsa.home.currentPositions.v1';
export const CURRENT_POSITIONS_COLLAPSED_STORAGE_KEY = 'dsa.home.currentPositionsCollapsed.v1';
export const SHORT_TERM_CAPITAL_GAINS_TAX_PCT = 35;
export const LONG_TERM_CAPITAL_GAINS_TAX_PCT = 15;
export const LONG_TERM_HOLDING_DAYS = 365;

const DAY_MS = 24 * 60 * 60 * 1000;
const DAYS_PER_YEAR = 365;

function parseDate(value: string | Date): Date | null {
  if (value instanceof Date) {
    return Number.isNaN(value.getTime()) ? null : value;
  }

  const trimmed = value.trim();
  const parsed = /^\d{4}-\d{2}-\d{2}$/.test(trimmed)
    ? new Date(`${trimmed}T00:00:00Z`)
    : new Date(trimmed);
  return Number.isNaN(parsed.getTime()) ? null : parsed;
}

function isPositionAccount(value: unknown): value is PositionAccount {
  return typeof value === 'string'
    && POSITION_ACCOUNT_OPTIONS.includes(value as PositionAccount);
}

export function getHoldingDays(purchaseDate: string, asOf: string | Date = new Date()): number | null {
  const purchase = parseDate(purchaseDate);
  const end = parseDate(asOf);
  if (!purchase || !end) return null;
  return Math.floor((end.getTime() - purchase.getTime()) / DAY_MS);
}

export function calculateCurrentPositionMetrics(
  position: Pick<CurrentPosition, 'purchaseDate' | 'purchasePrice' | 'quantity'>
    & Partial<Pick<CurrentPosition, 'account'>>,
  currentPrice: number | null | undefined,
  asOf: string | Date = new Date(),
): CurrentPositionMetrics {
  const purchasePrice = Number(position.purchasePrice);
  const quantity = Number(position.quantity);
  const price = Number(currentPrice);
  const holdingDays = getHoldingDays(position.purchaseDate, asOf);
  const taxRatePct = position.account === '401K' || position.account === 'HSA'
    ? 0
    : holdingDays !== null && holdingDays >= LONG_TERM_HOLDING_DAYS
      ? LONG_TERM_CAPITAL_GAINS_TAX_PCT
      : holdingDays !== null && holdingDays >= 0
        ? SHORT_TERM_CAPITAL_GAINS_TAX_PCT
        : null;

  if (
    !Number.isFinite(purchasePrice)
    || purchasePrice <= 0
    || !Number.isFinite(quantity)
    || quantity <= 0
    || !Number.isFinite(price)
    || price <= 0
  ) {
    return {
      currentValue: null,
      gainLossAmount: null,
      gainLossPct: null,
      afterTaxCagrPct: null,
      holdingDays,
      taxRatePct,
    };
  }

  const returnRatio = price / purchasePrice - 1;
  const afterTaxReturnRatio = returnRatio > 0
    ? returnRatio * (1 - (taxRatePct ?? SHORT_TERM_CAPITAL_GAINS_TAX_PCT) / 100)
    : returnRatio;
  const afterTaxGrowth = 1 + afterTaxReturnRatio;
  const years = holdingDays !== null ? holdingDays / DAYS_PER_YEAR : 0;
  let afterTaxCagrPct: number | null = null;

  if (years > 0 && afterTaxGrowth > 0) {
    afterTaxCagrPct = (Math.pow(afterTaxGrowth, 1 / years) - 1) * 100;
  } else if (years > 0 && afterTaxGrowth === 0) {
    afterTaxCagrPct = -100;
  }

  return {
    currentValue: price * quantity,
    gainLossAmount: (price - purchasePrice) * quantity,
    gainLossPct: returnRatio * 100,
    afterTaxCagrPct,
    holdingDays,
    taxRatePct,
  };
}

function isCurrentPosition(value: unknown): value is CurrentPosition {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<CurrentPosition>;
  return (
    typeof candidate.id === 'string'
    && typeof candidate.code === 'string'
    && candidate.code.trim().length > 0
    && typeof candidate.name === 'string'
    && typeof candidate.purchaseDate === 'string'
    && (candidate.account === undefined || isPositionAccount(candidate.account))
    && Number.isFinite(candidate.purchasePrice)
    && Number(candidate.purchasePrice) > 0
    && Number.isFinite(candidate.quantity)
    && Number(candidate.quantity) > 0
  );
}

export function readStoredCurrentPositions(): CurrentPosition[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(CURRENT_POSITIONS_STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter(isCurrentPosition).map((position) => ({
        ...position,
        // Positions saved before accounts were added belong to the default taxable account.
        account: position.account ?? 'Robinhood',
      }))
      : [];
  } catch {
    return [];
  }
}

export function writeStoredCurrentPositions(positions: CurrentPosition[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(CURRENT_POSITIONS_STORAGE_KEY, JSON.stringify(positions));
  } catch {
    // Browser storage is best-effort; the table remains usable in memory.
  }
}

export function readStoredCurrentPositionsCollapsed(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(CURRENT_POSITIONS_COLLAPSED_STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

export function writeStoredCurrentPositionsCollapsed(collapsed: boolean): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(CURRENT_POSITIONS_COLLAPSED_STORAGE_KEY, String(collapsed));
  } catch {
    // Browser storage is best-effort; the toggle remains usable in memory.
  }
}

export interface ClosedSale {
  id: string;
  positionId?: string | null;
  code: string;
  name: string;
  market?: string;
  purchaseDate: string;
  purchasePrice: number;
  quantity: number;
  sellDate: string;
  sellPrice: number;
  profit: number;
  account: PositionAccount;
}

export const CLOSED_SALES_STORAGE_KEY = 'dsa.home.closedSales.v1';

export function calculateClosedSaleProfit(
  purchasePrice: number,
  sellPrice: number,
  quantity: number,
): number | null {
  const buy = Number(purchasePrice);
  const sell = Number(sellPrice);
  const qty = Number(quantity);
  if (
    !Number.isFinite(buy)
    || buy <= 0
    || !Number.isFinite(sell)
    || sell <= 0
    || !Number.isFinite(qty)
    || qty <= 0
  ) {
    return null;
  }
  return (sell - buy) * qty;
}

function isClosedSale(value: unknown): value is ClosedSale {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<ClosedSale>;
  return (
    typeof candidate.id === 'string'
    && typeof candidate.code === 'string'
    && candidate.code.trim().length > 0
    && typeof candidate.name === 'string'
    && typeof candidate.purchaseDate === 'string'
    && typeof candidate.sellDate === 'string'
    && (candidate.account === undefined || isPositionAccount(candidate.account))
    && Number.isFinite(candidate.purchasePrice)
    && Number(candidate.purchasePrice) > 0
    && Number.isFinite(candidate.sellPrice)
    && Number(candidate.sellPrice) > 0
    && Number.isFinite(candidate.quantity)
    && Number(candidate.quantity) > 0
    && Number.isFinite(candidate.profit)
  );
}

export function readStoredClosedSales(): ClosedSale[] {
  if (typeof window === 'undefined') return [];
  try {
    const raw = window.localStorage.getItem(CLOSED_SALES_STORAGE_KEY);
    if (!raw) return [];
    const parsed: unknown = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter(isClosedSale).map((sale) => ({
        ...sale,
        // Sales saved before accounts were backfilled belong to the default taxable account.
        account: sale.account ?? 'Robinhood',
      }))
      : [];
  } catch {
    return [];
  }
}

export function writeStoredClosedSales(sales: ClosedSale[]): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(CLOSED_SALES_STORAGE_KEY, JSON.stringify(sales));
  } catch {
    // Browser storage is best-effort; the table remains usable in memory.
  }
}

export const TRADE_HISTORY_COLLAPSED_STORAGE_KEY = 'dsa.home.tradeHistoryCollapsed.v1';

export function readStoredTradeHistoryCollapsed(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(TRADE_HISTORY_COLLAPSED_STORAGE_KEY) === 'true';
  } catch {
    return false;
  }
}

export function writeStoredTradeHistoryCollapsed(collapsed: boolean): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(TRADE_HISTORY_COLLAPSED_STORAGE_KEY, String(collapsed));
  } catch {
    // Browser storage is best-effort; the toggle remains usable in memory.
  }
}

export interface ReconciledSaleEdit {
  sale: ClosedSale;
  profit: number;
}

export function reconcileSaleEdit(
  sale: ClosedSale,
  patch: { sellDate: string; sellPrice: number; quantity: number },
): ReconciledSaleEdit | null {
  const sellPrice = Number(patch.sellPrice);
  const quantity = Number(patch.quantity);
  if (
    !patch.sellDate
    || patch.sellDate < sale.purchaseDate
    || !Number.isFinite(sellPrice)
    || sellPrice <= 0
    || !Number.isFinite(quantity)
    || quantity <= 0
  ) {
    return null;
  }
  const profit = calculateClosedSaleProfit(sale.purchasePrice, sellPrice, quantity);
  if (profit === null) return null;
  return {
    sale: { ...sale, sellDate: patch.sellDate, sellPrice, quantity, profit },
    profit,
  };
}

export interface ReconciledSaleDelete {
  sales: ClosedSale[];
  positions: CurrentPosition[];
}

export function reconcileSaleDelete(
  sale: ClosedSale,
  sales: ClosedSale[],
  positions: CurrentPosition[],
): ReconciledSaleDelete {
  const remainingSales = sales.filter((item) => item.id !== sale.id);
  const restored: CurrentPosition = {
    id: sale.positionId ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`,
    code: sale.code,
    name: sale.name,
    market: sale.market,
    purchaseDate: sale.purchaseDate,
    purchasePrice: sale.purchasePrice,
    quantity: sale.quantity,
    account: sale.account,
  };
  const existingIndex = sale.positionId
    ? positions.findIndex((position) => position.id === sale.positionId)
    : -1;
  if (existingIndex >= 0) {
    const existing = positions[existingIndex];
    const merged = {
      ...existing,
      quantity: existing.quantity + sale.quantity,
    };
    return {
      sales: remainingSales,
      positions: positions.map((position, index) => (index === existingIndex ? merged : position)),
    };
  }
  return { sales: remainingSales, positions: [...positions, restored] };
}
