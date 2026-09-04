import type { CompositeSignals } from '../api/stocks';

export type CompositeTriggerTone = 'buy' | 'sell' | 'none';
export type CompositeTriggerIntensity = 'strong' | 'light' | 'none';

export interface CompositeTriggerInfo {
  side: 'buy' | 'sell';
  date: string;
  index: number;
}

export interface CompositeSummaryEntry {
  code: string;
  recordId: number | null;
  tone: CompositeTriggerTone;
  intensity: CompositeTriggerIntensity;
  triggerDate: string | null;
}

export interface CompositeTriggerInput {
  dates: string[];
  composite: CompositeSignals | null | undefined;
}

export const COMPOSITE_SUMMARY_FETCH_DAYS = 30;
export const COMPOSITE_STRONG_WINDOW_DAYS = 3;
export const COMPOSITE_LIGHT_WINDOW_DAYS = 7;

const DAY_MS = 24 * 60 * 60 * 1000;

function parseDayKey(value: string): number | null {
  const dayPart = value.slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(dayPart)) {
    return null;
  }
  const ms = new Date(`${dayPart}T00:00:00Z`).getTime();
  return Number.isNaN(ms) ? null : ms;
}

export function dayAgeInDays(dayValue: string, todayKey: string): number | null {
  const dayMs = parseDayKey(dayValue);
  const todayMs = parseDayKey(todayKey);
  if (dayMs === null || todayMs === null) {
    return null;
  }
  return Math.round((todayMs - dayMs) / DAY_MS);
}

function latestMarkerIndex(series: Array<number | null> | undefined, length: number): number {
  if (!series) {
    return -1;
  }
  const end = Math.min(series.length, length);
  for (let i = end - 1; i >= 0; i -= 1) {
    if (series[i] !== null && series[i] !== undefined) {
      return i;
    }
  }
  return -1;
}

export function findLatestCompositeTrigger(input: CompositeTriggerInput): CompositeTriggerInfo | null {
  const dates = input.dates ?? [];
  const buyIndex = latestMarkerIndex(input.composite?.buySignal, dates.length);
  const sellIndex = latestMarkerIndex(input.composite?.sellSignal, dates.length);
  if (buyIndex < 0 && sellIndex < 0) {
    return null;
  }
  if (buyIndex === sellIndex) {
    // The backend never emits buy and sell on the same bar; a tie means the
    // payload is ambiguous, so report no trigger rather than guessing a side.
    return null;
  }
  if (buyIndex > sellIndex) {
    return { side: 'buy', date: dates[buyIndex], index: buyIndex };
  }
  return { side: 'sell', date: dates[sellIndex], index: sellIndex };
}

export interface BuildCompositeSummaryArgs {
  codes: string[];
  triggers: Record<string, CompositeTriggerInput | null | undefined>;
  recordIds?: Record<string, number | null | undefined>;
  todayKey: string;
}

export function buildCompositeSummaryEntries(args: BuildCompositeSummaryArgs): CompositeSummaryEntry[] {
  return args.codes.map((code) => {
    const fallback: CompositeSummaryEntry = {
      code,
      recordId: args.recordIds?.[code] ?? null,
      tone: 'none',
      intensity: 'none',
      triggerDate: null,
    };
    const payload = args.triggers[code];
    if (!payload) {
      return fallback;
    }
    const trigger = findLatestCompositeTrigger(payload);
    if (!trigger) {
      return fallback;
    }
    const age = dayAgeInDays(trigger.date, args.todayKey);
    if (age === null || age < 0 || age > COMPOSITE_LIGHT_WINDOW_DAYS) {
      return { ...fallback, triggerDate: trigger.date };
    }
    return {
      code,
      recordId: fallback.recordId,
      tone: trigger.side,
      intensity: age <= COMPOSITE_STRONG_WINDOW_DAYS ? 'strong' : 'light',
      triggerDate: trigger.date,
    };
  });
}
