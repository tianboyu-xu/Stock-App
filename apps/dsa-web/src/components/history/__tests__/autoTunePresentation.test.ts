import { describe, expect, it } from 'vitest';
import type { AutoTuneResponse } from '../../../api/stocks';
import { combinedStrategyCurves } from '../autoTunePresentation';

describe('shared strategy NAV comparison', () => {
  it('compares MATR and technical strategies from the same actual date and NAV origin', () => {
    const report = { strategies: [
      { key: 'A', testEquity: { dates: ['2024-01-02', '2024-01-03', '2024-01-04', '2024-01-05'],
        values: [0, 20, 32, -100] } },
      { key: 'C', validationScore: 1, testEquity: { dates: ['2024-01-03', '2024-01-05', '2024-01-08'],
        values: [50, 65, 80] } },
    ], macroRouter: { targetCagr: 0.3,
      testEquity: { dates: ['2023-12-29', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-08'],
        values: [0, 100, 80, 120, 130] },
      benchmarkEquity: { dates: ['2023-12-29', '2024-01-03', '2024-01-04', '2024-01-05', '2024-01-08'],
        values: [0, 200, 206, 212, 215] },
    } } as unknown as AutoTuneResponse;
    const combined = combinedStrategyCurves(report, ['baseline', 'trend', 'macro_router']);
    expect(combined.anchorDate).toBe('2024-01-03');
    expect(combined.endDate).toBe('2024-01-05');
    expect(combined.rows.map(row => row.date)).toEqual(['2024-01-03', '2024-01-04', '2024-01-05']);
    expect(combined.rows[0]).toEqual({ date: '2024-01-03', 'nav:baseline': 1, 'nav:trend': 1,
      'nav:macro_router': 1, benchmarkNav: 1, requiredNav: 1 });
    expect(combined.rows[1]['nav:baseline']).toBeCloseTo(1.1);
    expect(combined.rows[1]['nav:trend']).toBeNull();
    expect(combined.rows[1]['nav:macro_router']).toBeCloseTo(0.9);
    expect(combined.rows[2]['nav:baseline']).toBe(0); // Bankruptcy must remain visible.
    expect(combined.rows[2]['nav:trend']).toBeCloseTo(1.1);
    expect(combined.rows[2]['nav:macro_router']).toBeCloseTo(1.1);
    expect(combined.rows[2].benchmarkNav).toBeCloseTo(1.04);
    expect(combined.rows[2].requiredNav).toBeCloseTo(1.3 ** (2 / 365.25));
    // Cropping is presentation only: the original research equity is unchanged.
    expect(report.macroRouter?.testEquity?.values).toEqual([0, 100, 80, 120, 130]);
  });

  it('keeps old results available when optional MATR has no history and never invents SPY data', () => {
    const report = { strategies: [{ key: 'A', testEquity: {
      dates: ['2024-01-02', '2024-01-03'], values: [20, 32],
    } }], macroRouter: { status: 'UNAVAILABLE', reason: 'FRED_API_KEY_MISSING' } } as unknown as AutoTuneResponse;
    const combined = combinedStrategyCurves(report, ['baseline', 'macro_router']);
    expect(combined.rows).toHaveLength(2);
    expect(combined.rows[1]['nav:baseline']).toBeCloseTo(1.1);
    expect(combined.views.find(item => item.family === 'macro_router')?.view.unavailable).toBe('FRED_API_KEY_MISSING');
    expect(combined.hasBenchmark).toBe(false);
    expect(combined.rows.every(row => row.benchmarkNav == null && row['nav:macro_router'] == null)).toBe(true);
  });

  it('does not splice nonoverlapping evaluations or fill a benchmark gap', () => {
    const report = { strategies: [{ key: 'A', testEquity: {
      dates: ['2024-01-02', '2024-01-03', '2024-01-04'], values: [0, 5, 10],
    } }], macroRouter: {
      testEquity: { dates: ['2023-01-02', '2023-01-03'], values: [0, 10] },
    } } as unknown as AutoTuneResponse;
    expect(combinedStrategyCurves(report, ['baseline', 'macro_router']).rows).toEqual([]);
    report.macroRouter!.testEquity = { dates: ['2024-01-02', '2024-01-03', '2024-01-04'], values: [0, 5, 10] };
    report.macroRouter!.benchmarkEquity = { dates: ['2024-01-02', '2024-01-04'], values: [50, 65] };
    const combined = combinedStrategyCurves(report, ['baseline', 'macro_router']);
    expect(combined.rows[0].benchmarkNav).toBe(1);
    expect(combined.rows[1].benchmarkNav).toBeNull();
    expect(combined.rows[2].benchmarkNav).toBeCloseTo(1.1);
  });
});
