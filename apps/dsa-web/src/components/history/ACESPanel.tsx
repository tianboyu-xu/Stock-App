import { useState } from 'react';
import type { ACESReport, AllocationReport } from '../../api/stocks';
import { AutoTuneAllocationPanel } from './AutoTuneAllocationPanel';

export function ACESSetup({ onChange, language, disabled, initiallyEnabled = false }: {
  initiallyEnabled?: boolean;
  onChange: (value: Record<string, unknown> | undefined, valid: boolean) => void;
  language: string; disabled: boolean;
}) {
  const zh = language === 'zh';
  const [enabled, setEnabled] = useState(initiallyEnabled);
  const [budget, setBudget] = useState(10000);
  const [cagr, setCagr] = useState(30);
  const [exposure, setExposure] = useState(100);
  const [drawdown, setDrawdown] = useState(15);
  const [volatility, setVolatility] = useState(true);
  const [gap, setGap] = useState(true);
  const [opportunity, setOpportunity] = useState(true);
  const [mode, setMode] = useState('COMPARE');
  const [buy, setBuy] = useState('4,5,6,7,8');
  const [sell, setSell] = useState('-4,-5,-6,-7,-8');
  const [folds, setFolds] = useState(3);
  const [advanced, setAdvanced] = useState('{}');
  const [error, setError] = useState('');
  const current = { enabled, budget, cagr, exposure, drawdown, volatility, gap, opportunity, mode, buy, sell, folds, advanced };
  function update(patch: Partial<typeof current>) {
    const next = { ...current, ...patch };
    try {
      const buys = next.buy.split(',').map(Number), sells = next.sell.split(',').map(Number);
      if (!(next.budget > 0 && next.budget <= 1e12) || ![next.cagr, next.exposure, next.drawdown].every(v => Number.isFinite(v) && v >= 0 && v <= 100)
        || !Number.isInteger(next.folds) || next.folds < 2 || next.folds > 5
        || ![buys, sells].every(a => a.length >= 1 && a.length <= 7 && new Set(a).size === a.length)
        || !buys.every(v => Number.isInteger(v) && v > 0 && v <= 30) || !sells.every(v => Number.isInteger(v) && v < 0 && v >= -30)) throw new Error(zh ? '请检查预算、阈值及风险范围。' : 'Check budget, thresholds and risk ranges.');
      const overrides = JSON.parse(next.advanced) as Record<string, unknown>;
      if (!overrides || Array.isArray(overrides) || typeof overrides !== 'object') throw new Error('Advanced settings must be an object.');
      const allocation = (overrides.allocation ?? {}) as Record<string, unknown>;
      const risk = (overrides.risk ?? {}) as Record<string, unknown>;
      const execution = (overrides.execution ?? {}) as Record<string, unknown>;
      const config = { ...overrides, version: 1, enabled: next.enabled, initial_budget: next.budget,
        policy_mode: next.mode, buy_thresholds: buys, sell_thresholds: sells,
        allocation: { ...allocation, validation_folds: next.folds, lambda_opportunity: next.opportunity ? .25 : 0,
          economic: { ...(allocation.economic as object ?? {}), target_cagr: next.cagr / 100, allowed_max_drawdown: next.drawdown / 100 } },
        risk: { ...risk, maximum_exposure: next.exposure / 100, volatility_control: next.volatility },
        execution: { ...execution, max_entry_gap_atr: next.gap ? 1 : null } };
      setError(''); onChange(next.enabled ? config : undefined, true);
    } catch (e) { setError(String(e)); onChange(undefined, !next.enabled); }
  }
  const inputClass = 'rounded border border-border bg-transparent p-1 w-28';
  const label = (en: string, cn: string) => zh ? cn : en;
  return <fieldset disabled={disabled} className="my-3 rounded border border-border p-3 text-xs">
    <legend>Strategy G — ACES · {label('Adaptive Capital Efficiency', '自适应资金效率')}</legend>
    <label><input type="checkbox" checked={enabled} onChange={e => { setEnabled(e.target.checked); update({ enabled: e.target.checked }); }} /> {label('Include ACES alongside A–F', '独立运行 ACES，并保留 A–F 对比')}</label>
    {enabled && <>
      <p className="my-2">{label('Optimizes triggers and capital allocation with portfolio, time-value, benchmark and risk constraints. Ticker and history/test dates use the Auto Tune controls above.', '在预算、时间价值、基准及风险约束下优化触发和配置。股票及历史/测试日期使用上方 Auto Tune 设置。')}</p>
      <div className="my-2 flex flex-wrap gap-3">
        <label>{label('Preset', '预设')} <select className={inputClass} defaultValue="Balanced" onChange={e => {
          const value = e.target.value; const cap = value === 'Conservative' ? 60 : 100; const dd = value === 'Conservative' ? 10 : value === 'Aggressive' ? 25 : 15;
          setExposure(cap); setDrawdown(dd); update({ exposure: cap, drawdown: dd });
        }}><option>Conservative</option><option>Balanced</option><option>Aggressive</option></select></label>
        <label>{label('Initial budget', '初始预算')} <input className={inputClass} type="number" min="1" max="1000000000000" value={budget} onChange={e => { setBudget(+e.target.value); update({ budget: +e.target.value }); }} /></label>
        <label>{label('Allocation policy', '配置策略')} <select className={inputClass} value={mode} onChange={e => { setMode(e.target.value); update({ mode: e.target.value }); }}><option value="COMPARE">Compare Both</option><option value="TUNED_FIXED">Tuned Fixed</option><option value="Q_LEARNING">Q-learning</option><option value="FIXED">Fixed</option></select></label>
        <label>{label('Target CAGR %', '目标 CAGR %')} <input className={inputClass} type="number" min="0" max="100" value={cagr} onChange={e => { setCagr(+e.target.value); update({ cagr: +e.target.value }); }} /></label>
        <label>{label('Maximum drawdown %', '最大回撤 %')} <input className={inputClass} type="number" min="0" max="100" value={drawdown} onChange={e => { setDrawdown(+e.target.value); update({ drawdown: +e.target.value }); }} /></label>
        <label>{label('Maximum exposure %', '最大仓位 %')} <input className={inputClass} type="number" min="0" max="100" value={exposure} onChange={e => { setExposure(+e.target.value); update({ exposure: +e.target.value }); }} /></label>
        <label>BUY <input className={inputClass} value={buy} onChange={e => { setBuy(e.target.value); update({ buy: e.target.value }); }} /></label>
        <label>SELL <input className={inputClass} value={sell} onChange={e => { setSell(e.target.value); update({ sell: e.target.value }); }} /></label>
        <label>{label('Validation folds', '验证折数')} <input className={inputClass} type="number" min="2" max="5" value={folds} onChange={e => { setFolds(+e.target.value); update({ folds: +e.target.value }); }} /></label>
      </div>
      <div className="flex flex-wrap gap-3">
        <label><input type="checkbox" checked={volatility} onChange={e => { setVolatility(e.target.checked); update({ volatility: e.target.checked }); }} /> {label('Volatility control', '波动率控制')}</label>
        <label><input type="checkbox" checked={gap} onChange={e => { setGap(e.target.checked); update({ gap: e.target.checked }); }} /> {label('Gap protection', '跳空保护')}</label>
        <label><input type="checkbox" checked={opportunity} onChange={e => { setOpportunity(e.target.checked); update({ opportunity: e.target.checked }); }} /> {label('Opportunity cost', '机会成本')}</label>
        <span>{label('No leverage · S&P 500 · Stock Buy & Hold · 20% allocation steps', '无杠杆 · 标普500 · 个股买入持有 · 20% 仓位步长')}</span>
      </div>
      <p className="my-2">{label('30% CAGR is a performance hurdle, not a guaranteed return. Research uses a 252-bar purge. When research data is insufficient, ACES still backtests its fixed allocation rules and reports the result.', '30% CAGR 是门槛而非收益保证。研究默认隔离 252 个交易日；研究数据不足时，ACES 仍按固定资金规则回测并展示结果。')}</p>
      <details><summary>{label('Advanced settings', '高级设置')}</summary>
        <p>{label('Versioned JSON overrides for Q, reward, risk, execution and purge. Basic controls take precedence. Numeric rates use fractions [0,1]; Q episodes 1–2000, minimum visits ≥1, purge 1–1260 bars. Defaults and complete ranges: docs/aces.md.', '使用版本化 JSON 配置 Q、奖励、风险、执行及隔离期。基础控件优先。比例 [0,1]，Q 回合 1–2000，访问次数至少 1，隔离期 1–1260 日。完整默认值及范围见 docs/aces.md。')}</p>
        <textarea aria-label="ACES advanced JSON" className="w-full rounded border border-border bg-transparent p-2 font-mono" rows={6} value={advanced} onChange={e => { setAdvanced(e.target.value); update({ advanced: e.target.value }); }} />
      </details>
      {error && <p role="alert">{error}</p>}
    </>}
  </fieldset>;
}

export function ACESResults({ report, language }: { report?: ACESReport | null; language: string }) {
  if (!report) return null;
  const zh = language === 'zh';
  return <section className="my-4 rounded border border-border p-3 text-xs" aria-label="Strategy G ACES results">
    <h3 className="font-semibold">Strategy G — ACES · {report.readiness.status}</h3>
    {report.error ? <p role="alert">{report.error}</p> : <>
      <p>{report.inspectedOnly ? (zh ? '没有通过验证及压力测试的策略。下方仅作诊断。' : 'No policy passed validation and stress checks. The following results are diagnostic only.') : `${report.selectedPolicy} · BUY ${report.selectedThresholds?.buy} / SELL ${report.selectedThresholds?.sell}`}</p>
      <p>{zh ? '资金表现与优化奖励分开；不安装实盘策略。' : 'Real money performance is separate from optimization reward. This result does not install a live policy.'}</p>
      <AutoTuneAllocationPanel report={{ ...report, config: (report.config.allocation ?? {}) as AllocationReport['config'] }} language={language} />
      <div className="my-3 max-h-80 overflow-auto">
        <h4 className="font-medium">{zh ? '验证压力测试（不使用最终测试）' : 'Validation stress tests (final test excluded)'}</h4>
        <table className="w-full text-left"><thead><tr>{['Policy', 'Scenario', 'Worst fold return', 'Worst DD', 'Result'].map(h => <th className="p-2" key={h}>{h}</th>)}</tr></thead>
          <tbody>{report.robustness?.flatMap((group, i) => group.scenarios.map(s => <tr key={`${i}-${s.scenario}`}>
            <td className="p-2">{group.candidate.policy} · {group.candidate.thresholds.join(' / ')}</td><td>{s.scenario}</td>
            <td>{Math.min(...s.folds.map(f => f.metrics.totalReturnPct)).toFixed(2)}%</td>
            <td>{Math.min(...s.folds.map(f => f.metrics.maxDrawdownPct)).toFixed(2)}%</td><td>{s.passed ? 'PASS' : 'FAIL'}</td>
          </tr>))}</tbody></table>
        <p>{report.robustness?.map(g => `${g.candidate.policy}: ${g.scenarios.every(s => s.passed) ? 'ROBUST' : g.scenarios.filter(s => s.passed).length / g.scenarios.length >= .75 ? 'MODERATE' : 'FRAGILE'}`).join(' · ')}</p>
      </div>
      <details><summary>{zh ? '个股持有对比' : 'Stock Buy & Hold comparison'}</summary><pre className="overflow-auto">{JSON.stringify(report.buyHoldMetrics, null, 2)}</pre></details>
      <details><summary>{zh ? '验证折与候选' : 'Validation folds and candidates'}</summary><pre className="max-h-96 overflow-auto">{JSON.stringify({ folds: report.folds, candidates: report.candidates }, null, 2)}</pre></details>
      <details><summary>{zh ? '压力测试与参数稳定性' : 'Stress tests and parameter stability'}</summary><pre className="max-h-96 overflow-auto">{JSON.stringify({ stability: report.parameterStabilityScore, robustness: report.robustness }, null, 2)}</pre></details>
      <details><summary>{zh ? '就绪检查、配置与复现信息' : 'Readiness, configuration and reproducibility'}</summary><pre className="max-h-96 overflow-auto">{JSON.stringify({ readiness: report.readiness, config: report.config, provenance: report.provenance, complexity: report.searchComplexity }, null, 2)}</pre></details>
    </>}
  </section>;
}
