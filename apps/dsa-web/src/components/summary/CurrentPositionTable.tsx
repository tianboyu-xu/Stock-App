import type React from 'react';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Banknote, Check, ChevronDown, CircleAlert, GripVertical, Loader2, Pencil, Plus, RefreshCw, Trash2, X } from 'lucide-react';
import { stocksApi } from '../../api/stocks';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { getTodayInShanghai } from '../../utils/format';
import {
  calculateCurrentPositionMetrics,
  POSITION_ACCOUNT_OPTIONS,
  readStoredClosedSales,
  readStoredCurrentPositions,
  readStoredCurrentPositionsCollapsed,
  reconcileSaleDelete,
  writeStoredClosedSales,
  writeStoredCurrentPositions,
  writeStoredCurrentPositionsCollapsed,
  type ClosedSale,
  type CurrentPosition,
  type PositionAccount,
} from '../../utils/currentPosition';
import { Button } from '../common';
import { DashboardPanelHeader, DashboardStateBlock } from '../dashboard';
import { StockAutocomplete } from '../StockAutocomplete';
import type { Market } from '../../types/stockIndex';
import {
  buildCompositeSummaryEntries,
  COMPOSITE_SUMMARY_FETCH_DAYS,
  type CompositeSummaryEntry,
} from '../../utils/compositeSummary';
import { readStoredIndicatorThresholds } from '../../utils/indicatorThresholds';
import { areStockCodesEquivalent, normalizeStockCode } from '../../utils/stockCode';
import { CurrentPositionProfitChart } from './CurrentPositionProfitChart';
import { SellPositionDialog, type SellPositionConfirm } from './SellPositionDialog';
import { TradeHistoryTable } from './TradeHistoryTable';
import { getSummaryStockStyle } from './summaryStockStyle';

type QuoteState = {
  status: 'loading' | 'ready' | 'error';
  price?: number;
};

type PositionDraft = {
  code: string;
  name: string;
  market?: Market;
  purchaseDate: string;
  purchasePrice: string;
  quantity: string;
  account: PositionAccount;
};

function createEmptyDraft(): PositionDraft {
  return {
    code: '',
    name: '',
    purchaseDate: getTodayInShanghai(),
    purchasePrice: '',
    quantity: '1',
    account: 'Robinhood',
  };
}

function formatValue(value: number | null, language: 'zh' | 'en', signed = false): string {
  if (value === null || Number.isNaN(value)) return '--';
  const formatted = value.toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return signed && value > 0 ? `+${formatted}` : formatted;
}

function valueTone(value: number | null): string {
  if (value === null) return 'text-muted-text';
  return value >= 0 ? 'text-success' : 'text-danger';
}

interface CurrentPositionTableProps {
  entries: CompositeSummaryEntry[];
}

export const CurrentPositionTable: React.FC<CurrentPositionTableProps> = ({ entries }) => {
  const { language, t } = useUiLanguage();
  const asOfDate = getTodayInShanghai();
  const [positions, setPositions] = useState<CurrentPosition[]>(readStoredCurrentPositions);
  const [closedSales, setClosedSales] = useState<ClosedSale[]>(readStoredClosedSales);
  const [isCollapsed, setIsCollapsed] = useState<boolean>(readStoredCurrentPositionsCollapsed);
  const [quoteStates, setQuoteStates] = useState<Record<string, QuoteState>>({});
  const [quoteRefreshVersion, setQuoteRefreshVersion] = useState(0);
  const [showAddForm, setShowAddForm] = useState(false);
  const [draft, setDraft] = useState<PositionDraft>(createEmptyDraft);
  const [formError, setFormError] = useState<string | null>(null);
  const [editingPositionId, setEditingPositionId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<PositionDraft | null>(null);
  const [editError, setEditError] = useState<string | null>(null);
  const [sellingPosition, setSellingPosition] = useState<CurrentPosition | null>(null);
  const [positionTriggers, setPositionTriggers] = useState<CompositeSummaryEntry[]>([]);
  const [dragPositionId, setDragPositionId] = useState<string | null>(null);
  const dragPositionIdRef = useRef<string | null>(null);
  const quoteRequestRef = useRef(0);

  useEffect(() => {
    writeStoredCurrentPositions(positions);
  }, [positions]);

  useEffect(() => {
    writeStoredClosedSales(closedSales);
  }, [closedSales]);

  const handleCollapsedToggle = () => {
    setIsCollapsed((previous) => {
      const next = !previous;
      writeStoredCurrentPositionsCollapsed(next);
      return next;
    });
  };

  useEffect(() => {
    const requestId = quoteRequestRef.current + 1;
    quoteRequestRef.current = requestId;
    let cancelled = false;

    if (positions.length === 0) {
      setQuoteStates({});
      return () => {
        cancelled = true;
      };
    }

    setQuoteStates((previous) => {
      const next: Record<string, QuoteState> = {};
      for (const position of positions) {
        next[position.id] = {
          status: 'loading',
          price: previous[position.id]?.price,
        };
      }
      return next;
    });

    const uniqueCodes = Array.from(new Map(
      positions.map((position) => [normalizeStockCode(position.code).toUpperCase(), position.code]),
    ).entries());
    const loadQuotes = async () => {
      const quoteByCode = new Map<string, QuoteState>();
      await Promise.all(uniqueCodes.map(async ([key, code]) => {
        try {
          const quote = await stocksApi.getQuote(code);
          const price = Number(quote.currentPrice);
          if (!Number.isFinite(price) || price <= 0) {
            throw new Error('invalid quote');
          }
          quoteByCode.set(key, { status: 'ready', price });
        } catch {
          quoteByCode.set(key, { status: 'error' });
        }
      }));

      const next: Record<string, QuoteState> = {};
      for (const position of positions) {
        next[position.id] = quoteByCode.get(normalizeStockCode(position.code).toUpperCase()) ?? { status: 'error' };
      }

      if (!cancelled && quoteRequestRef.current === requestId) {
        setQuoteStates(next);
      }
    };

    void loadQuotes();
    return () => {
      cancelled = true;
    };
  }, [positions, quoteRefreshVersion]);

  const quotesLoading = positions.some((position) => quoteStates[position.id]?.status === 'loading');

  const validateDraft = (candidate: PositionDraft): string | null => {
    const code = candidate.code.trim();
    const purchasePrice = Number(candidate.purchasePrice);
    const quantity = Number(candidate.quantity);

    if (!code) {
      return t('home.currentPositionsStockRequired');
    }
    if (!candidate.purchaseDate || candidate.purchaseDate > asOfDate) {
      return t('home.currentPositionsDateInvalid');
    }
    if (!Number.isFinite(purchasePrice) || purchasePrice <= 0) {
      return t('home.currentPositionsPurchasePriceRequired');
    }
    if (!Number.isFinite(quantity) || quantity <= 0) {
      return t('home.currentPositionsQuantityRequired');
    }
    return null;
  };

  const buildPosition = (candidate: PositionDraft, id: string): CurrentPosition => ({
    id,
    code: candidate.code.trim(),
    name: candidate.name.trim() || candidate.code.trim(),
    market: candidate.market,
    purchaseDate: candidate.purchaseDate,
    purchasePrice: Number(candidate.purchasePrice),
    quantity: Number(candidate.quantity),
    account: candidate.account,
  });

  const handleStockSubmit = (
    code: string,
    name?: string,
    _source?: 'manual' | 'autocomplete',
    metadata?: { market?: Market; displayCode?: string },
  ) => {
    const displayCode = metadata?.displayCode?.trim() || code.trim();
    if (!displayCode) return;
    setDraft((previous) => ({
      ...previous,
      code: displayCode,
      name: name?.trim() || previous.name,
      market: metadata?.market || previous.market,
    }));
    setFormError(null);
  };

  const handleEditStockSubmit = (
    code: string,
    name?: string,
    _source?: 'manual' | 'autocomplete',
    metadata?: { market?: Market; displayCode?: string },
  ) => {
    const displayCode = metadata?.displayCode?.trim() || code.trim();
    if (!displayCode) return;
    setEditDraft((previous) => previous ? ({
      ...previous,
      code: displayCode,
      name: name?.trim() || previous.name,
      market: metadata?.market || previous.market,
    }) : previous);
    setEditError(null);
  };

  const handleAddPosition = (event: React.FormEvent) => {
    event.preventDefault();
    const error = validateDraft(draft);
    if (error) {
      setFormError(error);
      return;
    }

    const position = buildPosition(draft, `${Date.now()}-${Math.random().toString(36).slice(2)}`);
    setPositions((previous) => [...previous, position]);
    setDraft(createEmptyDraft());
    setFormError(null);
    setShowAddForm(false);
  };

  const startEditPosition = (position: CurrentPosition) => {
    setShowAddForm(false);
    setEditingPositionId(position.id);
    setEditDraft({
      code: position.code,
      name: position.name,
      market: position.market as Market | undefined,
      purchaseDate: position.purchaseDate,
      purchasePrice: String(position.purchasePrice),
      quantity: String(position.quantity),
      account: position.account,
    });
    setEditError(null);
  };

  const cancelEditPosition = () => {
    setEditingPositionId(null);
    setEditDraft(null);
    setEditError(null);
  };

  const saveEditPosition = () => {
    if (!editingPositionId || !editDraft) return;
    const error = validateDraft(editDraft);
    if (error) {
      setEditError(error);
      return;
    }

    const updated = buildPosition(editDraft, editingPositionId);
    setPositions((previous) => previous.map((position) => (
      position.id === editingPositionId ? updated : position
    )));
    cancelEditPosition();
  };

  const handleRemovePosition = (id: string) => {
    setPositions((previous) => previous.filter((position) => position.id !== id));
    if (editingPositionId === id) {
      cancelEditPosition();
    }
    if (sellingPosition?.id === id) {
      setSellingPosition(null);
    }
  };

  const handleConfirmSell = (sale: SellPositionConfirm) => {
    if (!sellingPosition) return;
    const position = sellingPosition;
    const record: ClosedSale = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2)}`,
      positionId: position.id,
      code: position.code,
      name: position.name,
      market: position.market,
      purchaseDate: position.purchaseDate,
      purchasePrice: position.purchasePrice,
      quantity: sale.quantity,
      sellDate: sale.sellDate,
      sellPrice: sale.sellPrice,
      profit: sale.profit,
      account: position.account,
    };
    setClosedSales((previous) => [...previous, record]);
    const remaining = position.quantity - sale.quantity;
    if (remaining <= 1e-9) {
      setPositions((previous) => previous.filter((item) => item.id !== position.id));
      if (editingPositionId === position.id) {
        cancelEditPosition();
      }
    } else {
      setPositions((previous) => previous.map((item) => (
        item.id === position.id ? { ...item, quantity: remaining } : item
      )));
    }
    setSellingPosition(null);
  };

  const handleSaveSale = (sale: ClosedSale) => {
    setClosedSales((previous) => previous.map((item) => (item.id === sale.id ? sale : item)));
  };

  const handleDeleteSale = (id: string) => {
    setClosedSales((previous) => previous.filter((item) => item.id !== id));
  };

  const handleRevertSale = (id: string) => {
    const sale = closedSales.find((item) => item.id === id);
    if (!sale) return;
    const reconciled = reconcileSaleDelete(sale, closedSales, positions);
    setClosedSales(reconciled.sales);
    setPositions(reconciled.positions);
  };

  const updatePositionAccount = (id: string, account: PositionAccount) => {
    setPositions((previous) => previous.map((position) => (
      position.id === id ? { ...position, account } : position
    )));
  };

  const valuationSummary = useMemo(() => {
    const metricsByPositionId = new Map<string, ReturnType<typeof calculateCurrentPositionMetrics>>();
    const accountTotals = new Map<PositionAccount, number>();

    for (const position of positions) {
      const quote = quoteStates[position.id];
      const currentPrice = typeof quote?.price === 'number' ? quote.price : null;
      const metrics = calculateCurrentPositionMetrics(position, currentPrice, asOfDate);
      metricsByPositionId.set(position.id, metrics);
      if (metrics.currentValue !== null) {
        accountTotals.set(position.account, (accountTotals.get(position.account) ?? 0) + metrics.currentValue);
      }
    }

    return { metricsByPositionId, accountTotals };
  }, [asOfDate, positions, quoteStates]);

  const totalRealized = useMemo(
    () => closedSales.reduce((sum, sale) => sum + sale.profit, 0),
    [closedSales],
  );

  const handlePositionDragStart = (id: string) => {
    dragPositionIdRef.current = id;
    setDragPositionId(id);
  };

  const handlePositionDragEnd = () => {
    dragPositionIdRef.current = null;
    setDragPositionId(null);
  };

  const handlePositionDrop = (targetId: string) => {
    const dragId = dragPositionIdRef.current;
    dragPositionIdRef.current = null;
    setDragPositionId(null);
    if (!dragId || dragId === targetId || editingPositionId) return;
    setPositions((previous) => {
      const from = previous.findIndex((position) => position.id === dragId);
      const to = previous.findIndex((position) => position.id === targetId);
      if (from < 0 || to < 0) return previous;
      const next = [...previous];
      const [moved] = next.splice(from, 1);
      next.splice(to, 0, moved);
      return next;
    });
  };

  useEffect(() => {
    let cancelled = false;
    const missingCodes = Array.from(new Map(
      positions.map((position) => [normalizeStockCode(position.code).toUpperCase(), position.code]),
    ).values()).filter((code) => {
      const existing = entries.find((entry) => areStockCodesEquivalent(entry.code, code));
      if (!existing) return true;
      return !existing.triggerDate && typeof existing.triggerPrice !== 'number';
    });

    if (missingCodes.length === 0) {
      setPositionTriggers([]);
      return () => {
        cancelled = true;
      };
    }

    const loadTriggers = async () => {
      const results = await Promise.all(missingCodes.map(async (code) => {
        try {
          const storedThresholds = readStoredIndicatorThresholds(code);
          const response = await stocksApi.getIndicators(code, {
            period: 'daily',
            days: COMPOSITE_SUMMARY_FETCH_DAYS,
            ...(storedThresholds ?? {}),
          });
          const built = buildCompositeSummaryEntries({
            codes: [code],
            triggers: { [code]: { dates: response.dates ?? [], composite: response.composite ?? null } },
            todayKey: asOfDate,
          });
          return built[0] ?? null;
        } catch {
          return null;
        }
      }));

      if (!cancelled) {
        setPositionTriggers(results.filter((item): item is CompositeSummaryEntry => item !== null));
      }
    };

    void loadTriggers();
    return () => {
      cancelled = true;
    };
  }, [asOfDate, entries, positions]);

  const combinedEntries = useMemo(() => {
    const seen = new Set(entries.map((entry) => normalizeStockCode(entry.code).toUpperCase()));
    const merged = [...entries];
    for (const entry of positionTriggers) {
      const key = normalizeStockCode(entry.code).toUpperCase();
      if (!seen.has(key)) {
        seen.add(key);
        merged.push(entry);
      }
    }
    return merged;
  }, [entries, positionTriggers]);

  return (
    <section
      data-testid="current-position-table"
      aria-label={t('home.currentPositionsTableAria')}
      className="border-t border-subtle"
    >
      <div className="space-y-1 px-3 py-3 sm:px-4">
        <DashboardPanelHeader
          className="mb-0"
          title={t('home.currentPositionsTitle')}
          titleClassName="text-sm font-medium"
          leading={<span className="h-2 w-2 rounded-full bg-primary shadow-glow-cyan" aria-hidden="true" />}
          actions={(
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-muted-text">
                {t('common.itemsCount', { count: positions.length })}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="xsm"
                className="h-7 w-7 px-0"
                aria-expanded={!isCollapsed}
                aria-label={isCollapsed ? t('home.currentPositionsExpandAria') : t('home.currentPositionsCollapseAria')}
                onClick={handleCollapsedToggle}
              >
                <ChevronDown
                  className={`h-4 w-4 transition-transform ${isCollapsed ? '-rotate-90' : ''}`}
                  aria-hidden="true"
                />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="xsm"
                className="h-7 w-7 px-0"
                disabled={positions.length === 0 || quotesLoading}
                onClick={() => setQuoteRefreshVersion((version) => version + 1)}
                aria-label={t('home.currentPositionsRefreshAria')}
              >
                <RefreshCw className={`h-3.5 w-3.5 ${quotesLoading ? 'animate-spin' : ''}`} aria-hidden="true" />
              </Button>
              <Button
                type="button"
                variant="ghost"
                size="xsm"
                className={`h-7 w-7 px-0 ${showAddForm ? 'bg-primary/15 text-primary' : ''}`}
                onClick={() => {
                  if (editingPositionId) {
                    cancelEditPosition();
                  }
                  setShowAddForm((visible) => !visible);
                  setFormError(null);
                }}
                aria-label={t('home.currentPositionsAddAria')}
                aria-expanded={showAddForm}
              >
                <Plus className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          )}
        />
        <p className="text-[11px] leading-relaxed text-muted-text">
          {t('home.currentPositionsDescription')}
        </p>
      </div>

      {isCollapsed ? null : (
      <>
      {showAddForm ? (
        <form
          data-testid="current-position-form"
          className="border-y border-subtle bg-subtle-soft px-3 py-3 sm:px-4"
          onSubmit={handleAddPosition}
        >
          <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-5">
            <label className="min-w-0 sm:col-span-2 xl:col-span-1">
              <span className="mb-1 block text-[11px] text-secondary-text">{t('home.currentPositionsStock')}</span>
              <StockAutocomplete
                value={draft.code}
                onChange={(value) => setDraft((previous) => ({ ...previous, code: value }))}
                onSubmit={handleStockSubmit}
                placeholder={t('home.currentPositionsStockPlaceholder')}
                ariaLabel={t('home.currentPositionsStock')}
              />
            </label>
            <label>
              <span className="mb-1 block text-[11px] text-secondary-text">{t('home.currentPositionsPurchaseDate')}</span>
              <input
                type="date"
                value={draft.purchaseDate}
                max={asOfDate}
                onChange={(event) => setDraft((previous) => ({ ...previous, purchaseDate: event.target.value }))}
                className="input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-3 text-sm transition-all focus:outline-none"
                aria-label={t('home.currentPositionsPurchaseDate')}
                required
              />
            </label>
            <label>
              <span className="mb-1 block text-[11px] text-secondary-text">{t('home.currentPositionsPurchasePrice')}</span>
              <input
                type="number"
                min="0"
                step="0.0001"
                value={draft.purchasePrice}
                onChange={(event) => setDraft((previous) => ({ ...previous, purchasePrice: event.target.value }))}
                className="input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-3 text-sm transition-all focus:outline-none"
                placeholder="0.00"
                aria-label={t('home.currentPositionsPurchasePrice')}
                required
              />
            </label>
            <label>
              <span className="mb-1 block text-[11px] text-secondary-text">{t('home.currentPositionsQuantity')}</span>
              <input
                type="number"
                min="0"
                step="0.0001"
                value={draft.quantity}
                onChange={(event) => setDraft((previous) => ({ ...previous, quantity: event.target.value }))}
                className="input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-3 text-sm transition-all focus:outline-none"
                aria-label={t('home.currentPositionsQuantity')}
                required
              />
            </label>
            <label>
              <span className="mb-1 block text-[11px] text-secondary-text">{t('home.currentPositionsAccount')}</span>
              <select
                value={draft.account}
                onChange={(event) => setDraft((previous) => ({
                  ...previous,
                  account: event.target.value as PositionAccount,
                }))}
                className="input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-3 text-sm transition-all focus:outline-none"
                aria-label={t('home.currentPositionsAccount')}
              >
                {POSITION_ACCOUNT_OPTIONS.map((account) => (
                  <option key={account} value={account}>{account}</option>
                ))}
              </select>
            </label>
          </div>
          {formError ? <p className="mt-2 text-xs text-danger" role="alert">{formError}</p> : null}
          <div className="mt-3 flex justify-end gap-2">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                setShowAddForm(false);
                setFormError(null);
              }}
            >
              <X className="h-3.5 w-3.5" aria-hidden="true" />
              {t('common.cancel')}
            </Button>
            <Button type="submit" variant="primary" size="sm">
              <Plus className="h-3.5 w-3.5" aria-hidden="true" />
              {t('home.currentPositionsSave')}
            </Button>
          </div>
        </form>
      ) : null}

      {positions.length === 0 ? (
        <DashboardStateBlock
          compact
          title={t('home.currentPositionsEmptyTitle')}
          description={t('home.currentPositionsEmptyDescription')}
          className="px-3 py-3 sm:px-4"
        />
      ) : (
        <div className="overflow-x-auto px-3 pb-3 sm:px-4">
          {editError ? <p className="mb-2 text-xs text-danger" role="alert">{editError}</p> : null}
          <table className="min-w-[1300px] w-full text-xs" aria-label={t('home.currentPositionsTableAria')}>
            <thead className="border-b border-subtle text-[11px] text-secondary-text">
              <tr>
                <th scope="col" className="whitespace-nowrap px-2 py-2 text-left font-medium">{t('home.currentPositionsStock')}</th>
                <th scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">{t('home.currentPositionsAccountPct')}</th>
                <th scope="col" className="whitespace-nowrap px-2 py-2 text-left font-medium">{t('home.currentPositionsAccount')}</th>
                <th scope="col" className="whitespace-nowrap px-2 py-2 text-left font-medium">{t('home.currentPositionsPurchaseDate')}</th>
                <th scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">{t('home.currentPositionsPurchasePrice')}</th>
                <th scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">{t('home.currentPositionsQuantity')}</th>
                <th scope="col" className="whitespace-nowrap px-2 py-2 text-left font-medium">{t('home.currentPositionsLastTriggerDate')}</th>
                <th scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">{t('home.currentPositionsLastTriggerPrice')}</th>
                <th scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">{t('home.currentPositionsCurrentPrice')}</th>
                <th scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">{t('home.currentPositionsTotalPrice')}</th>
                <th scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">{t('home.currentPositionsGainLoss')}</th>
                <th scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">{t('home.currentPositionsGainLossPct')}</th>
                <th scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">
                  {t('home.currentPositionsAfterTaxCagr')}
                </th>
                <th scope="col" className="px-2 py-2 text-right font-medium"><span className="sr-only">{t('common.delete')}</span></th>
              </tr>
            </thead>
            <tbody>
              {positions.map((position) => {
                const quote = quoteStates[position.id];
                const currentPrice = typeof quote?.price === 'number' ? quote.price : null;
                const metrics = valuationSummary.metricsByPositionId.get(position.id)
                  ?? calculateCurrentPositionMetrics(position, currentPrice, asOfDate);
                const accountTotal = valuationSummary.accountTotals.get(position.account) ?? 0;
                const accountPct = metrics.currentValue !== null && accountTotal > 0
                  ? metrics.currentValue / accountTotal * 100
                  : null;
                const trigger = combinedEntries.find((entry) => areStockCodesEquivalent(entry.code, position.code));
                const triggerSide = trigger?.triggerSide ?? (trigger?.tone === 'buy' || trigger?.tone === 'sell' ? trigger.tone : null);
                const isEditing = editingPositionId === position.id && editDraft !== null;
                const isDragging = dragPositionId === position.id;
                return (
                  <tr
                    key={position.id}
                    data-testid={`position-row-${position.id}`}
                    draggable={!isEditing && editingPositionId === null}
                    onDragStart={(event) => {
                      try {
                        if (event.dataTransfer) {
                          event.dataTransfer.effectAllowed = 'move';
                          event.dataTransfer.setData('text/plain', position.id);
                        }
                      } catch {
                        // Some test environments do not implement dataTransfer.
                      }
                      handlePositionDragStart(position.id);
                    }}
                    onDragOver={(event) => {
                      event.preventDefault();
                    }}
                    onDrop={(event) => {
                      event.preventDefault();
                      handlePositionDrop(position.id);
                    }}
                    onDragEnd={handlePositionDragEnd}
                    className={`border-b border-subtle last:border-b-0 ${isDragging ? 'opacity-40' : ''}`}
                  >
                    <td className="whitespace-nowrap px-2 py-2.5 text-left">
                      <div className="flex items-center gap-1">
                        <span
                          className="flex shrink-0 cursor-grab items-center text-muted-text active:cursor-grabbing"
                          role="img"
                          aria-label={t('home.currentPositionsDragAria', { code: position.code })}
                        >
                          <GripVertical className="h-4 w-4" aria-hidden="true" />
                        </span>
                        {isEditing ? (
                          <div className="flex-1 rounded-xl" style={trigger ? getSummaryStockStyle(trigger) : undefined}>
                            <StockAutocomplete
                              value={editDraft.code}
                              onChange={(value) => setEditDraft((previous) => previous ? ({ ...previous, code: value }) : previous)}
                              onSubmit={handleEditStockSubmit}
                              placeholder={t('home.currentPositionsStockPlaceholder')}
                              ariaLabel={t('home.currentPositionsStock')}
                            />
                          </div>
                        ) : (
                          <span
                            className="home-history-item inline-flex max-w-full items-center px-2.5 py-1.5 font-mono text-xs text-foreground"
                            style={trigger ? getSummaryStockStyle(trigger) : undefined}
                          >
                            {position.code}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums text-foreground">
                      {accountPct === null ? '--' : `${accountPct.toFixed(2)}%`}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2.5 text-left">
                      <select
                        value={isEditing ? editDraft.account : position.account}
                        onChange={(event) => {
                          const account = event.target.value as PositionAccount;
                          if (isEditing) {
                            setEditDraft((previous) => previous ? ({ ...previous, account }) : previous);
                          } else {
                            updatePositionAccount(position.id, account);
                          }
                        }}
                        className="input-surface h-8 rounded-lg border bg-transparent px-2 text-xs text-foreground focus:outline-none"
                        aria-label={t('home.currentPositionsAccountFor', { code: position.code })}
                      >
                        {POSITION_ACCOUNT_OPTIONS.map((account) => (
                          <option key={account} value={account}>{account}</option>
                        ))}
                      </select>
                    </td>
                    <td className="whitespace-nowrap px-2 py-2.5 text-left tabular-nums text-secondary-text">
                      {isEditing ? (
                        <input
                          type="date"
                          value={editDraft.purchaseDate}
                          max={asOfDate}
                          onChange={(event) => setEditDraft((previous) => previous ? ({ ...previous, purchaseDate: event.target.value }) : previous)}
                          className="input-surface h-8 rounded-lg border bg-transparent px-2 text-xs text-foreground focus:outline-none"
                          aria-label={t('home.currentPositionsPurchaseDate')}
                        />
                      ) : position.purchaseDate}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums text-foreground">
                      {isEditing ? (
                        <input
                          type="number"
                          min="0"
                          step="0.0001"
                          value={editDraft.purchasePrice}
                          onChange={(event) => setEditDraft((previous) => previous ? ({ ...previous, purchasePrice: event.target.value }) : previous)}
                          className="input-surface h-8 w-24 rounded-lg border bg-transparent px-2 text-right text-xs text-foreground focus:outline-none"
                          aria-label={t('home.currentPositionsPurchasePrice')}
                        />
                      ) : formatValue(position.purchasePrice, language)}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums text-foreground">
                      {isEditing ? (
                        <input
                          type="number"
                          min="0"
                          step="0.0001"
                          value={editDraft.quantity}
                          onChange={(event) => setEditDraft((previous) => previous ? ({ ...previous, quantity: event.target.value }) : previous)}
                          className="input-surface h-8 w-20 rounded-lg border bg-transparent px-2 text-right text-xs text-foreground focus:outline-none"
                          aria-label={t('home.currentPositionsQuantity')}
                        />
                      ) : formatValue(position.quantity, language)}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2.5 text-left tabular-nums text-secondary-text">
                      {trigger?.triggerDate ? (
                        <span
                          className="home-history-item inline-flex items-center px-2 py-1 font-mono text-[11px] text-foreground"
                          style={getSummaryStockStyle(trigger)}
                        >
                          {trigger.triggerDate}
                        </span>
                      ) : '--'}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums text-foreground">
                      {typeof trigger?.triggerPrice === 'number' ? (
                        <span className="inline-flex items-baseline justify-end gap-1">
                          <span>{formatValue(trigger.triggerPrice, language)}</span>
                          {triggerSide === 'buy' || triggerSide === 'sell' ? (
                            <span className="text-[10px] text-secondary-text">
                              ({triggerSide === 'buy'
                                ? t('home.currentPositionsTriggerSideBuy')
                                : t('home.currentPositionsTriggerSideSell')})
                            </span>
                          ) : null}
                        </span>
                      ) : '--'}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums text-foreground">
                      <span className="inline-flex items-center justify-end gap-1">
                        {formatValue(currentPrice, language)}
                        {quote?.status === 'loading' ? <Loader2 className="h-3 w-3 animate-spin text-muted-text" aria-label={t('home.currentPositionsQuoteLoading')} /> : null}
                        {quote?.status === 'error' ? <CircleAlert className="h-3 w-3 text-warning" aria-label={t('home.currentPositionsQuoteUnavailable')} /> : null}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums text-foreground">
                      {formatValue(metrics.currentValue, language)}
                    </td>
                    <td className={`whitespace-nowrap px-2 py-2.5 text-right tabular-nums ${valueTone(metrics.gainLossAmount)}`}>
                      {formatValue(metrics.gainLossAmount, language, true)}
                    </td>
                    <td className={`whitespace-nowrap px-2 py-2.5 text-right tabular-nums ${valueTone(metrics.gainLossPct)}`}>
                      {metrics.gainLossPct === null ? '--' : `${metrics.gainLossPct > 0 ? '+' : ''}${metrics.gainLossPct.toFixed(2)}%`}
                    </td>
                    <td className={`whitespace-nowrap px-2 py-2.5 text-right tabular-nums ${valueTone(metrics.afterTaxCagrPct)}`}>
                      {metrics.afterTaxCagrPct === null ? '--' : `${metrics.afterTaxCagrPct > 0 ? '+' : ''}${metrics.afterTaxCagrPct.toFixed(2)}%`}
                    </td>
                    <td className="whitespace-nowrap px-2 py-2.5 text-right">
                      <div className="flex justify-end gap-1">
                        {isEditing ? (
                          <>
                            <Button
                              type="button"
                              variant="ghost"
                              size="xsm"
                              className="h-7 w-7 px-0"
                              onClick={saveEditPosition}
                              aria-label={t('home.currentPositionsSaveEditAria', { code: position.code })}
                            >
                              <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" />
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="xsm"
                              className="h-7 w-7 px-0"
                              onClick={cancelEditPosition}
                              aria-label={t('home.currentPositionsCancelEditAria', { code: position.code })}
                            >
                              <X className="h-3.5 w-3.5 text-muted-text" aria-hidden="true" />
                            </Button>
                          </>
                        ) : (
                          <>
                            <Button
                              type="button"
                              variant="ghost"
                              size="xsm"
                              className="h-7 w-7 px-0"
                              onClick={() => startEditPosition(position)}
                              aria-label={t('home.currentPositionsEditAria', { code: position.code })}
                            >
                              <Pencil className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="xsm"
                              className="h-7 w-7 px-0"
                              onClick={() => {
                                if (editingPositionId) {
                                  cancelEditPosition();
                                }
                                setSellingPosition(position);
                              }}
                              aria-label={t('home.currentPositionsSellAria', { code: position.code })}
                            >
                              <Banknote className="h-3.5 w-3.5 text-success" aria-hidden="true" />
                            </Button>
                            <Button
                              type="button"
                              variant="ghost"
                              size="xsm"
                              className="h-7 w-7 px-0"
                              onClick={() => handleRemovePosition(position.id)}
                              aria-label={t('home.currentPositionsDeleteAria', { code: position.code })}
                            >
                              <Trash2 className="h-3.5 w-3.5 text-danger" aria-hidden="true" />
                            </Button>
                          </>
                        )}
                      </div>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
           <p className="mt-2 text-[10px] leading-relaxed text-muted-text">
            {t('home.currentPositionsTaxNote')}
          </p>
        </div>
      )}
      {positions.length > 0 || closedSales.length > 0 ? (
        <CurrentPositionProfitChart positions={positions} closedSales={closedSales} />
      ) : null}
      {closedSales.length > 0 ? (
        <div className="border-t border-subtle px-3 py-2 sm:px-4" data-testid="closed-sales-summary">
          <p className="text-[11px] text-muted-text">
            {t('home.currentPositionsRealizedTotal')}:{' '}
            <span className={totalRealized >= 0 ? 'text-success' : 'text-danger'}>
              {formatValue(totalRealized, language, true)}
            </span>
            {' '}({t('common.itemsCount', { count: closedSales.length })})
          </p>
        </div>
      ) : null}
      {positions.length > 0 || closedSales.length > 0 ? (
        <TradeHistoryTable
          sales={closedSales}
          onSaveSale={handleSaveSale}
          onDeleteSale={handleDeleteSale}
          onRevertSale={handleRevertSale}
        />
      ) : null}
      {sellingPosition ? (
        <SellPositionDialog
          position={sellingPosition}
          onConfirm={handleConfirmSell}
          onCancel={() => setSellingPosition(null)}
        />
      ) : null}
      </>
      )}
    </section>
  );
};

export default CurrentPositionTable;
