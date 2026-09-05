import type { CSSProperties } from 'react';
import type { CompositeSummaryEntry } from '../../utils/compositeSummary';

export function getSummaryStockStyle(entry: CompositeSummaryEntry): CSSProperties | undefined {
  if (entry.tone === 'buy') {
    return entry.intensity === 'strong'
      ? { background: 'hsl(var(--success) / 0.35)' }
      : { background: 'hsl(var(--success) / 0.15)' };
  }
  if (entry.tone === 'sell') {
    return entry.intensity === 'strong'
      ? { background: 'hsl(var(--destructive) / 0.35)' }
      : { background: 'hsl(var(--destructive) / 0.15)' };
  }
  return undefined;
}
