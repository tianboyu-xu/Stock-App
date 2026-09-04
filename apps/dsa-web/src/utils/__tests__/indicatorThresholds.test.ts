import { describe, expect, it, vi } from 'vitest';
import {
  INDICATOR_THRESHOLDS_CHANGED_EVENT,
  notifyIndicatorThresholdsChanged,
  type IndicatorThresholdsChangedDetail,
} from '../indicatorThresholds';

describe('notifyIndicatorThresholdsChanged', () => {
  it('dispatches the thresholds-changed event with the stock code', () => {
    const listener = vi.fn();
    const handler = (event: Event) => {
      listener((event as CustomEvent<IndicatorThresholdsChangedDetail>).detail);
    };
    window.addEventListener(INDICATOR_THRESHOLDS_CHANGED_EVENT, handler);
    try {
      notifyIndicatorThresholdsChanged('600519');
      expect(listener).toHaveBeenCalledWith({ stockCode: '600519' });
    } finally {
      window.removeEventListener(INDICATOR_THRESHOLDS_CHANGED_EVENT, handler);
    }
  });
});
