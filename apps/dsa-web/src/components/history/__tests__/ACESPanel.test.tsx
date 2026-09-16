import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { ACESResults, ACESSetup } from '../ACESPanel';
import type { ACESReport } from '../../../api/stocks';

describe('independent Strategy G setup', () => {
  it('is always on, produces versioned aggressive defaults', () => {
    const onChange = vi.fn();
    render(<ACESSetup onChange={onChange} language="en" disabled={false} />);
    expect(screen.getByLabelText('Initial budget')).toBeInTheDocument();
    expect(screen.queryByLabelText('Include ACES alongside A–F')).not.toBeInTheDocument();
    expect(onChange.mock.lastCall?.[0]).toMatchObject({ version: 1, enabled: true, policy_mode: 'COMPARE', initial_budget: 10000,
      buy_thresholds: [6, 7, 8], sell_thresholds: [-6, -7, -8],
      risk: { maximum_exposure: 1 },
      allocation: { economic: { target_cagr: .3, allowed_max_drawdown: .25 } } });
  });

  it('blocks invalid thresholds and lets presets populate risk inputs', () => {
    const onChange = vi.fn();
    render(<ACESSetup onChange={onChange} language="en" disabled={false} />);
    fireEvent.change(screen.getByLabelText('Preset'), { target: { value: 'Conservative' } });
    expect(onChange.mock.lastCall?.[0]).toMatchObject({ risk: { maximum_exposure: .6 }, allocation: { economic: { allowed_max_drawdown: .1 } } });
    fireEvent.change(screen.getByLabelText('BUY'), { target: { value: '-6' } });
    expect(onChange).toHaveBeenLastCalledWith(undefined, false);
    expect(screen.getByRole('alert')).toBeInTheDocument();
  });

  it('explains a blocked run without an apply action', () => {
    render(<ACESResults language="en" report={{ strategyKey: 'G', version: 1, error: 'SYSTEM_SAFE_MODE: PREVIEW', readiness: { status: 'FAIL', checks: {} } } as ACESReport} />);
    expect(screen.getByRole('heading')).toHaveTextContent('Strategy G — ACES · FAIL');
    expect(screen.getByRole('alert')).toHaveTextContent('PREVIEW');
    expect(screen.queryByRole('button')).not.toBeInTheDocument();
  });
});
