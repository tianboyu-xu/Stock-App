import type React from 'react';
import { useState } from 'react';
import { createPortal } from 'react-dom';
import { useUiLanguage } from '../../contexts/UiLanguageContext';
import { getTodayInShanghai } from '../../utils/format';
import {
  calculateClosedSaleProfit,
  type CurrentPosition,
} from '../../utils/currentPosition';
import { Button } from '../common';

export interface SellPositionConfirm {
  sellDate: string;
  sellPrice: number;
  quantity: number;
  profit: number;
}

interface SellPositionDialogProps {
  position: CurrentPosition;
  onConfirm: (sale: SellPositionConfirm) => void;
  onCancel: () => void;
}

function formatPreview(value: number | null, language: 'zh' | 'en'): string {
  if (value === null || Number.isNaN(value)) return '--';
  const formatted = value.toLocaleString(language === 'zh' ? 'zh-CN' : 'en-US', {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return value > 0 ? `+${formatted}` : formatted;
}

export const SellPositionDialog: React.FC<SellPositionDialogProps> = ({
  position,
  onConfirm,
  onCancel,
}) => {
  const { language, t } = useUiLanguage();
  const today = getTodayInShanghai();
  const [sellDate, setSellDate] = useState(today);
  const [sellPrice, setSellPrice] = useState('');
  const [sellQuantity, setSellQuantity] = useState(String(position.quantity));
  const [error, setError] = useState<string | null>(null);

  const previewProfit = calculateClosedSaleProfit(
    position.purchasePrice,
    Number(sellPrice),
    Number(sellQuantity),
  );

  const handleConfirm = () => {
    const price = Number(sellPrice);
    const quantity = Number(sellQuantity);
    if (!sellDate || sellDate < position.purchaseDate || sellDate > today) {
      setError(t('home.currentPositionsSellDateInvalid'));
      return;
    }
    if (!Number.isFinite(price) || price <= 0) {
      setError(t('home.currentPositionsSellPriceRequired'));
      return;
    }
    if (!Number.isFinite(quantity) || quantity <= 0 || quantity - position.quantity > 1e-9) {
      setError(t('home.currentPositionsSellQuantityInvalid'));
      return;
    }
    const profit = calculateClosedSaleProfit(position.purchasePrice, price, quantity) ?? 0;
    setError(null);
    onConfirm({ sellDate, sellPrice: price, quantity, profit });
  };

  const dialog = (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm transition-all"
      onClick={onCancel}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-label={t('home.currentPositionsSellAria', { code: position.code })}
        className="mx-4 w-full max-w-sm rounded-xl border border-border/70 bg-elevated p-6 shadow-2xl animate-in fade-in zoom-in duration-200"
        onClick={(event) => event.stopPropagation()}
      >
        <h3 className="mb-1 text-lg font-medium text-foreground">{t('home.currentPositionsSellTitle')}</h3>
        <p className="mb-4 text-xs text-secondary-text">
          {position.code} · {position.purchaseDate} · {formatPreview(position.purchasePrice, language)} × {position.quantity}
        </p>
        <div className="space-y-3">
          <label className="block">
            <span className="mb-1 block text-[11px] text-secondary-text">{t('home.currentPositionsSellDate')}</span>
            <input
              type="date"
              value={sellDate}
              min={position.purchaseDate}
              max={today}
              onChange={(event) => { setSellDate(event.target.value); setError(null); }}
              className="input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-3 text-sm transition-all focus:outline-none"
              aria-label={t('home.currentPositionsSellDate')}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] text-secondary-text">{t('home.currentPositionsSellPrice')}</span>
            <input
              type="number"
              min="0"
              step="0.0001"
              value={sellPrice}
              onChange={(event) => { setSellPrice(event.target.value); setError(null); }}
              className="input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-3 text-sm transition-all focus:outline-none"
              placeholder="0.00"
              aria-label={t('home.currentPositionsSellPrice')}
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-[11px] text-secondary-text">{t('home.currentPositionsSellQuantity')}</span>
            <input
              type="number"
              min="0"
              step="0.0001"
              value={sellQuantity}
              onChange={(event) => { setSellQuantity(event.target.value); setError(null); }}
              className="input-surface input-focus-glow h-11 w-full rounded-xl border bg-transparent px-3 text-sm transition-all focus:outline-none"
              aria-label={t('home.currentPositionsSellQuantity')}
            />
          </label>
        </div>
        <p className="mt-3 text-sm text-foreground" aria-live="polite">
          {t('home.currentPositionsSellProfit')}:{' '}
          <span className={previewProfit === null ? 'text-muted-text' : previewProfit >= 0 ? 'text-success' : 'text-danger'}>
            {formatPreview(previewProfit, language)}
          </span>
        </p>
        {error ? <p className="mt-2 text-xs text-danger" role="alert">{error}</p> : null}
        <div className="mt-4 flex justify-end gap-2">
          <Button type="button" variant="ghost" size="sm" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
          <Button type="button" variant="primary" size="sm" onClick={handleConfirm}>
            {t('home.currentPositionsSellConfirm')}
          </Button>
        </div>
      </div>
    </div>
  );

  return createPortal(dialog, document.body);
};

export default SellPositionDialog;
