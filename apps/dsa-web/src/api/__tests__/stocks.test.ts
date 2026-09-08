import { expect, it, vi } from 'vitest';
import { stocksApi } from '../stocks';

const { get } = vi.hoisted(() => ({ get: vi.fn() }));

vi.mock('../index', () => ({ default: { get } }));

it('converts the Auto Tune methodology, validation and final-test contract at the API boundary', async () => {
  get.mockResolvedValueOnce({
    data: {
      methodology_version: 2,
      walk_forward: { minimum_extra_validation_bars: 270 },
      strategies: [{
        key: 'A',
        validation_score: 0.7,
        validation_positive_folds: 2,
        validation_worst_cagr_pct: -1,
        validation_eligible_folds: 3,
        test_confidence: { sharpe_ci_lower: -0.4, positive_sharpe_fraction: 0.75 },
      }],
      fine_tune: {
        selection_basis: 'validation',
        sweep: [{ validation_cagr: 12, validation_score: 0.7, test_cagr: null }],
        final_test: { strategy_key: 'A', position_index: 2, confidence: { sharpe_ci_upper: 1.8 } },
      },
    },
  });

  const result = await stocksApi.autoTune('BRK/B', { fineTuneWindowDays: 360 });

  expect(get).toHaveBeenCalledWith('/api/v1/stocks/BRK%2FB/auto-tune', {
    params: { fine_tune_window_days: 360 }, timeout: 300000,
  });
  expect(result.methodologyVersion).toBe(2);
  expect(result.walkForward?.minimumExtraValidationBars).toBe(270);
  expect(result.strategies[0]).toMatchObject({
    validationScore: 0.7,
    validationPositiveFolds: 2,
    validationWorstCagrPct: -1,
    validationEligibleFolds: 3,
    testConfidence: { sharpeCiLower: -0.4, positiveSharpeFraction: 0.75 },
  });
  expect(result.fineTune).toMatchObject({
    selectionBasis: 'validation',
    sweep: [{ validationCagr: 12, validationScore: 0.7, testCagr: null }],
    finalTest: { strategyKey: 'A', positionIndex: 2, confidence: { sharpeCiUpper: 1.8 } },
  });
});
