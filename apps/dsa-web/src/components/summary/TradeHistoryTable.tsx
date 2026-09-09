import type React from 'react';
import { useMemo, useState } from 'react';
import { Check, ChevronDown, Pencil, Trash2, Undo2, X } from 'lucide-react';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { getTodayInShanghai } from '../../utils/format';
import {
  readStoredTradeHistoryCollapsed,
  reconcileSaleEdit,
  writeStoredTradeHistoryCollapsed,
  type ClosedSale,
} from '../../utils/currentPosition';
import { Button } from '../common';
import { DashboardPanelHeader, DashboardStateBlock } from '../dashboard';

type SaleEditDraft = {
  sellDate: string;
  sellPrice: string;
  quantity: string;
};

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

interface TradeHistoryTableProps {
  sales: ClosedSale[];
  onSaveSale: (sale: ClosedSale) => void;
  onDeleteSale: (id: string) => void;
  onRevertSale: (id: string) => void;
}

export const TradeHistoryTable: React.FC<TradeHistoryTableProps> = ({
  sales,
  onSaveSale,
  onDeleteSale,
  onRevertSale,
}) => {
  const { language, t } = useUiLanguage();
  const today = getTodayInShanghai();
  const [isCollapsed, setIsCollapsed] = useState<boolean>(readStoredTradeHistoryCollapsed);
  const [editingSaleId, setEditingSaleId] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState<SaleEditDraft | null>(null);
  const [editError, setEditError] = useState<string | null>(null);

  const sortedSales = useMemo(
    () => [...sales].sort((left, right) => (
      right.sellDate.localeCompare(left.sellDate) || right.id.localeCompare(left.id)
    )),
    [sales],
  );

  const handleCollapsedToggle = () => {
    setIsCollapsed((previous) => {
      const next = !previous;
      writeStoredTradeHistoryCollapsed(next);
      return next;
    });
  };

  const startEditSale = (sale: ClosedSale) => {
    setEditingSaleId(sale.id);
    setEditDraft({
      sellDate: sale.sellDate,
      sellPrice: String(sale.sellPrice),
      quantity: String(sale.quantity),
    });
    setEditError(null);
  };

  const cancelEditSale = () => {
    setEditingSaleId(null);
    setEditDraft(null);
    setEditError(null);
  };

  const saveEditSale = (sale: ClosedSale) => {
    if (!editingSaleId || !editDraft) return;
    const sellPrice = Number(editDraft.sellPrice);
    const quantity = Number(editDraft.quantity);
    if (!editDraft.sellDate || editDraft.sellDate < sale.purchaseDate) {
      setEditError(t('home.tradeHistoryDateInvalid'));
      return;
    }
    if (!Number.isFinite(sellPrice) || sellPrice <= 0) {
      setEditError(t('home.tradeHistoryPriceRequired'));
      return;
    }
    if (!Number.isFinite(quantity) || quantity <= 0) {
      setEditError(t('home.tradeHistoryQuantityInvalid'));
      return;
    }
    const reconciled = reconcileSaleEdit(sale, {
      sellDate: editDraft.sellDate,
      sellPrice,
      quantity,
    });
    if (!reconciled) {
      setEditError(t('home.tradeHistoryQuantityInvalid'));
      return;
    }
    onSaveSale(reconciled.sale);
    cancelEditSale();
  };

  return (
    <section
      data-testid="trade-history-table"
      aria-label={t('home.tradeHistoryTableAria')}
      className="border-t border-subtle"
    >
      <div className="space-y-1 px-3 py-3 sm:px-4">
        <DashboardPanelHeader
          className="mb-0"
          title={t('home.tradeHistoryTitle')}
          titleClassName="text-sm font-medium"
          leading={<span className="h-2 w-2 rounded-full bg-primary shadow-glow-cyan" aria-hidden="true" />}
          actions={(
            <div className="flex items-center gap-1.5">
              <span className="text-[11px] text-muted-text">
                {t('common.itemsCount', { count: sales.length })}
              </span>
              <Button
                type="button"
                variant="ghost"
                size="xsm"
                className="h-7 w-7 px-0"
                aria-expanded={!isCollapsed}
                aria-label={isCollapsed ? t('home.tradeHistoryExpandAria') : t('home.tradeHistoryCollapseAria')}
                onClick={handleCollapsedToggle}
              >
                <ChevronDown
                  className={`h-4 w-4 transition-transform ${isCollapsed ? '-rotate-90' : ''}`}
                  aria-hidden="true"
                />
              </Button>
            </div>
          )}
        />
        <p className="text-[11px] leading-relaxed text-muted-text">
          {t('home.tradeHistoryDescription')}
        </p>
      </div>

      {isCollapsed ? null : (
        sortedSales.length === 0 ? (
          <DashboardStateBlock
            compact
            title={t('home.tradeHistoryEmptyTitle')}
            description={t('home.tradeHistoryEmptyDescription')}
            className="px-3 py-3 sm:px-4"
          />
        ) : (
          <div className="overflow-x-auto px-3 pb-3 sm:px-4">
            {editError ? <p className="mb-2 text-xs text-danger" role="alert">{editError}</p> : null}
            <table className="min-w-[900px] w-full text-xs" aria-label={t('home.tradeHistoryTableAria')}>
              <thead className="border-b border-subtle text-[11px] text-secondary-text">
                <tr>
                  <th scope="col" className="whitespace-nowrap px-2 py-2 text-left font-medium">{t('home.tradeHistoryStock')}</th>
                  <th scope="col" className="whitespace-nowrap px-2 py-2 text-left font-medium">{t('home.tradeHistoryBuyDate')}</th>
                  <th scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">{t('home.tradeHistoryBuyPrice')}</th>
                  <th scope="col" className="whitespace-nowrap px-2 py-2 text-left font-medium">{t('home.tradeHistorySellDate')}</th>
                  <th scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">{t('home.tradeHistorySellPrice')}</th>
                  <th scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">{t('home.tradeHistoryQuantity')}</th>
                  <th scope="col" className="whitespace-nowrap px-2 py-2 text-right font-medium">{t('home.tradeHistoryProfit')}</th>
                  <th scope="col" className="px-2 py-2 text-right font-medium"><span className="sr-only">{t('common.delete')}</span></th>
                </tr>
              </thead>
              <tbody>
                {sortedSales.map((sale) => {
                  const isEditing = editingSaleId === sale.id && editDraft !== null;
                  return (
                    <tr
                      key={sale.id}
                      data-testid={`trade-history-row-${sale.id}`}
                      className="border-b border-subtle last:border-b-0"
                    >
                      <td className="whitespace-nowrap px-2 py-2.5 text-left">
                        <span className="home-history-item inline-flex max-w-full items-center px-2.5 py-1.5 font-mono text-xs text-foreground">
                          {sale.code}
                        </span>
                      </td>
                      <td className="whitespace-nowrap px-2 py-2.5 text-left tabular-nums text-secondary-text">
                        {sale.purchaseDate}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums text-foreground">
                        {formatValue(sale.purchasePrice, language)}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2.5 text-left tabular-nums text-secondary-text">
                        {isEditing ? (
                          <input
                            type="date"
                            value={editDraft.sellDate}
                            min={sale.purchaseDate}
                            max={today}
                            onChange={(event) => setEditDraft((previous) => previous ? ({ ...previous, sellDate: event.target.value }) : previous)}
                            className="input-surface h-8 rounded-lg border bg-transparent px-2 text-xs text-foreground focus:outline-none"
                            aria-label={t('home.tradeHistorySellDate')}
                          />
                        ) : sale.sellDate}
                      </td>
                      <td className="whitespace-nowrap px-2 py-2.5 text-right tabular-nums text-foreground">
                        {isEditing ? (
                          <input
                            type="number"
                            min="0"
                            step="0.0001"
                            value={editDraft.sellPrice}
                            onChange={(event) => setEditDraft((previous) => previous ? ({ ...previous, sellPrice: event.target.value }) : previous)}
                            className="input-surface h-8 w-24 rounded-lg border bg-transparent px-2 text-right text-xs text-foreground focus:outline-none"
                            aria-label={t('home.tradeHistorySellPrice')}
                          />
                        ) : formatValue(sale.sellPrice, language)}
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
                            aria-label={t('home.tradeHistoryQuantity')}
                          />
                        ) : formatValue(sale.quantity, language)}
                      </td>
                      <td className={`whitespace-nowrap px-2 py-2.5 text-right tabular-nums ${valueTone(sale.profit)}`}>
                        {formatValue(sale.profit, language, true)}
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
                                onClick={() => saveEditSale(sale)}
                                aria-label={t('home.tradeHistorySaveEditAria', { code: sale.code })}
                              >
                                <Check className="h-3.5 w-3.5 text-success" aria-hidden="true" />
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="xsm"
                                className="h-7 w-7 px-0"
                                onClick={cancelEditSale}
                                aria-label={t('home.tradeHistoryCancelEditAria', { code: sale.code })}
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
                                onClick={() => startEditSale(sale)}
                                aria-label={t('home.tradeHistoryEditAria', { code: sale.code })}
                              >
                                <Pencil className="h-3.5 w-3.5 text-primary" aria-hidden="true" />
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="xsm"
                                className="h-7 w-7 px-0"
                                onClick={() => onRevertSale(sale.id)}
                                aria-label={t('home.tradeHistoryRevertAria', { code: sale.code })}
                              >
                                <Undo2 className="h-3.5 w-3.5 text-warning" aria-hidden="true" />
                              </Button>
                              <Button
                                type="button"
                                variant="ghost"
                                size="xsm"
                                className="h-7 w-7 px-0"
                                onClick={() => onDeleteSale(sale.id)}
                                aria-label={t('home.tradeHistoryDeleteAria', { code: sale.code })}
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
          </div>
        )
      )}
    </section>
  );
};

export default TradeHistoryTable;
