import { describe, expect, it } from 'vitest';
import {
  buildCompositeSummaryEntries,
  COMPOSITE_LIGHT_WINDOW_DAYS,
  COMPOSITE_STRONG_WINDOW_DAYS,
  dayAgeInDays,
  findLatestCompositeTrigger,
  type CompositeTriggerInput,
} from '../compositeSummary';

const TODAY = '2026-09-03';

function dayKey(daysAgo: number): string {
  const ms = new Date(`${TODAY}T00:00:00Z`).getTime() - daysAgo * 24 * 60 * 60 * 1000;
  return new Date(ms).toISOString().slice(0, 10);
}

function makePayload(markers: { buy?: number[]; sell?: number[]; days?: number }): CompositeTriggerInput {
  const days = markers.days ?? 10;
  const dates = Array.from({ length: days }, (_, index) => dayKey(days - 1 - index));
  const buySignal = new Array<number | null>(days).fill(null);
  const sellSignal = new Array<number | null>(days).fill(null);
  for (const index of markers.buy ?? []) {
    buySignal[index] = 100;
  }
  for (const index of markers.sell ?? []) {
    sellSignal[index] = 100;
  }
  return {
    dates,
    composite: {
      buyScore: new Array<number>(days).fill(0),
      sellScore: new Array<number>(days).fill(0),
      buySignal,
      sellSignal,
      buyBreakdown: [],
      sellBreakdown: [],
    },
  };
}

describe('dayAgeInDays', () => {
  it('computes calendar-day age for day-only strings', () => {
    expect(dayAgeInDays(TODAY, TODAY)).toBe(0);
    expect(dayAgeInDays(dayKey(3), TODAY)).toBe(3);
    expect(dayAgeInDays(dayKey(7), TODAY)).toBe(7);
  });

  it('returns null for unparseable values', () => {
    expect(dayAgeInDays('not-a-date', TODAY)).toBeNull();
    expect(dayAgeInDays(TODAY, '')).toBeNull();
  });
});

describe('findLatestCompositeTrigger', () => {
  it('returns null when there is no composite payload', () => {
    expect(findLatestCompositeTrigger({ dates: [TODAY], composite: null })).toBeNull();
    expect(findLatestCompositeTrigger({ dates: [TODAY], composite: undefined })).toBeNull();
  });

  it('returns null when no markers exist', () => {
    expect(findLatestCompositeTrigger(makePayload({}))).toBeNull();
  });

  it('picks the latest marker across buy and sell sides', () => {
    const payload = makePayload({ buy: [3], sell: [7] });
    const trigger = findLatestCompositeTrigger(payload);
    expect(trigger?.side).toBe('sell');
    expect(trigger?.date).toBe(payload.dates[7]);
  });

  it('returns null when buy and sell tie on the same bar', () => {
    const payload = makePayload({ buy: [5], sell: [5] });
    expect(findLatestCompositeTrigger(payload)).toBeNull();
  });

  it('ignores markers beyond the dates array', () => {
    const payload = makePayload({ buy: [9], days: 10 });
    const shortened: CompositeTriggerInput = {
      dates: payload.dates.slice(0, 5),
      composite: payload.composite,
    };
    expect(findLatestCompositeTrigger(shortened)).toBeNull();
  });
});

describe('buildCompositeSummaryEntries', () => {
  it('marks triggers within the strong window as strong', () => {
    const entries = buildCompositeSummaryEntries({
      codes: ['600519'],
      triggers: { '600519': makePayload({ buy: [9], days: 10 }) },
      recordIds: { '600519': 7 },
      todayKey: TODAY,
    });
    expect(entries).toHaveLength(1);
    expect(entries[0]).toMatchObject({
      code: '600519',
      recordId: 7,
      tone: 'buy',
      intensity: 'strong',
      triggerDate: dayKey(0),
    });
  });

  it(`marks triggers older than ${COMPOSITE_STRONG_WINDOW_DAYS} days as light`, () => {
    const entries = buildCompositeSummaryEntries({
      codes: ['600519'],
      triggers: { '600519': makePayload({ sell: [5], days: 10 }) },
      todayKey: TODAY,
    });
    expect(entries[0]).toMatchObject({ tone: 'sell', intensity: 'light', triggerDate: dayKey(4) });
  });

  it(`drops tone for triggers older than ${COMPOSITE_LIGHT_WINDOW_DAYS} days`, () => {
    const entries = buildCompositeSummaryEntries({
      codes: ['600519'],
      triggers: { '600519': makePayload({ buy: [0], days: 10 }) },
      todayKey: TODAY,
    });
    expect(entries[0]).toMatchObject({ tone: 'none', intensity: 'none', triggerDate: dayKey(9) });
  });

  it('keeps future-dated markers uncolored', () => {
    const entries = buildCompositeSummaryEntries({
      codes: ['600519'],
      triggers: { '600519': makePayload({ buy: [9], days: 10 }) },
      todayKey: dayKey(5),
    });
    expect(entries[0]).toMatchObject({ tone: 'none', intensity: 'none' });
  });

  it('returns uncolored entries for missing payloads and missing record ids', () => {
    const entries = buildCompositeSummaryEntries({
      codes: ['600519', '00700'],
      triggers: {},
      todayKey: TODAY,
    });
    expect(entries).toEqual([
      { code: '600519', recordId: null, tone: 'none', intensity: 'none', triggerDate: null },
      { code: '00700', recordId: null, tone: 'none', intensity: 'none', triggerDate: null },
    ]);
  });
});
