import { useState } from 'react';
import type { AllocationReport } from '../../api/stocks';
import { AutoTuneEconomicChart } from './AutoTuneEconomicChart';

const reasonLabels: Record<string, [string, string]> = {
  TARGET_EXPOSURE: ['调整到目标仓位', 'Rebalanced to target'],
  BUDGET_CONSTRAINED: ['现金约束', 'Cash constrained'],
  SAME_TARGET: ['仓位已达目标', 'Already at target'],
  POLICY_HOLD: ['策略选择持有', 'Policy chose HOLD'],
  TRADE_COOLDOWN: ['交易冷却期', 'Trade cooldown'],
  ENTRY_COOLDOWN: ['买入间隔限制', 'Buy interval limit'],
  ENTRY_FILTER: ['未通过入场过滤', 'Entry filter blocked'],
  NO_NEXT_BAR: ['无下一交易日', 'No next trading bar'],
  PRICE_DRIFT_DIRECTION_HOLD: ['跳空会反转信号方向，持有', 'Price drift would reverse direction; HOLD'],
  FIXED_MAPPING: ['固定目标映射', 'Fixed target mapping'],
  DIRECTION_MASK_HOLD: ['信号方向限制，持有', 'Direction constraint; HOLD'],
  NEUTRAL_HOLD: ['中性信号，持有', 'Neutral signal; HOLD'],
  LOW_SAMPLE_FALLBACK: ['训练支持不足，使用调优固定目标', 'Low training support; using tuned fixed target'],
  GREEDY_Q: ['选择最高 Q 值', 'Highest supported Q value'],
  CURRENT_SCORE_BUDGET: ['原评分预算规则', 'Current score-budget rule'],
  CURRENT_EXIT: ['原全部卖出规则', 'Current full-exit rule'],
  POSITION_OPEN: ['原单仓策略不加仓', 'Current policy does not add shares'],
  GAP_TOO_LARGE: ['开盘跳空超过限制', 'Opening gap exceeds limit'],
  FULLY_EXPOSED: ['已全部持有，无错失上涨', 'Fully exposed; no missed upside'],
  CASH_AVAILABLE_BUT_NOT_USED: ['有现金但未使用', 'Cash available but not used'],
  EXPOSURE_NOT_REDUCED: ['未减仓', 'Exposure not reduced'],
  EXECUTION_CONSTRAINED: ['执行受限', 'Execution constrained'],
  THRESHOLD_MISSED_TRIGGER: ['阈值未触发', 'Threshold missed trigger'],
  NO_REGRET: ['无机会遗憾', 'No opportunity regret'],
};

export function AutoTuneAllocationPanel({ report, language, onApplyThresholds }: {
  report?: AllocationReport | null; language: string; onApplyThresholds?: (buy: number, sell: number) => void;
}) {
  const [inspected, setInspected] = useState<string | null>(null);
  const [stateFilter, setStateFilter] = useState('');
  if (!report) return null;
  const text = (zh: string, en: string) => language === 'zh' ? zh : en;
  const reason = (value: string) => reasonLabels[value]?.[language === 'zh' ? 0 : 1] ?? value;
  const pct = (n: number | null | undefined) => n == null ? 'HOLD' : `${(n * 100).toFixed(1)}%`;
  const names: Record<string, string> = {
    BUY_HOLD: text('买入持有', 'Buy & Hold'), CURRENT: text('原单仓配置', 'Current single-position'),
    FIXED: text('固定目标', 'Fixed targets'), TUNED_FIXED: text('调优固定目标', 'Tuned Fixed'), Q_LEARNING: 'Q-learning',
    THRESHOLD_CURRENT: text('调优阈值 + 原配置', 'Tuned thresholds + Current'),
  };
  const selected = report.policies.find(p => p.name === (inspected ?? report.selectedPolicy)) ?? report.policies[0];
  const rows = report.qTable.filter(row => JSON.stringify(row.state).toLowerCase().includes(stateFilter.toLowerCase()));
  const largestThresholdMiss = selected?.scoreObservations?.filter(o => o.missedBuyRegret + o.missedSellRegret > 0)
    .sort((a, b) => b.missedBuyRegret + b.missedSellRegret - a.missedBuyRegret - a.missedSellRegret)[0];
  return (
    <section className="mt-4 rounded-lg border border-border/60 p-3 text-xs" aria-label={text('资金配置策略', 'Allocation policy')}>
      <h3 className="font-semibold">{text('资金配置策略', 'Allocation policy')} · {report.selectedPolicy ? names[report.selectedPolicy] ?? report.selectedPolicy : text('未选出候选策略', 'No selected candidate')}</h3>
      {report.benchmarkStatus === 'BENCHMARK_DATA_MISSING' && <p role="status" className="my-2 text-amber-500">
        {text('缺少完整、同日复权标普数据：基准奖励已禁用，不代表基准收益为零。', 'BENCHMARK_DATA_MISSING: benchmark reward disabled; benchmark return is unknown, not zero.')}</p>}
      {report.testRiskStatus === 'BREACH' && <p role="status" className="my-2 text-red-500">{text('验证选中的策略在最终测试超过回撤限制；已禁止应用，未使用测试集重新选择策略。', 'The validation-selected policy breached the final-test drawdown limit. Applying it is blocked; the test did not select a replacement.')}</p>}
      <p className="my-2 text-secondary-text">
        {text('联合比较买卖阈值与资金配置，每组阈值独立训练，滚动验证后冻结。上方 A–F 表仍为原配置参考。实际收益含交易成本、税前；机会遗憾是反事实估计，不是真实亏损。',
          'BUY/SELL thresholds and allocation are compared jointly; each threshold pair trains independently and freezes for walk-forward validation. The A–F table remains a Current reference. Actual returns include trading costs, before tax. Opportunity regret is a counterfactual estimate, not a realized loss.')}
        {report.technicalStrategyKey ? ` · ${report.technicalStrategyKey}` : ''}
      </p>
      {report.jointThresholds && <div className="my-3 rounded border border-border/40 p-2">
        <h4 className="font-medium">{text('联合阈值优化', 'Joint threshold optimization')}</h4>
        <p>BUY {report.jointThresholds.original.buy} → {report.jointThresholds.selected.buy}
          {' · SELL '}{report.jointThresholds.original.sell} → {report.jointThresholds.selected.sell}
          {' · '}{report.jointThresholds.candidatesEvaluated} {text('候选', 'candidates')}</p>
        {report.jointThresholds.selectedValidation && <p>{text('验证中位收益 / 最差收益', 'Median / worst validation return')}: {pct(report.jointThresholds.selectedValidation.medianValidationReturn)} / {pct(report.jointThresholds.selectedValidation.worstValidationReturn)}
          {' · '}{text('正收益折数', 'Positive folds')}: {report.jointThresholds.selectedValidation.positiveFolds}/{report.jointThresholds.folds.length}</p>}
        <p>{text('阈值跨折标准差 BUY / SELL', 'Threshold standard deviation BUY / SELL')}: {report.jointThresholds.thresholdStability.buyStd.toFixed(2)} / {report.jointThresholds.thresholdStability.sellStd.toFixed(2)}</p>
        <p className="text-secondary-text">{text('表内训练/验证为最新折；全部折明细见下方。最终测试不参与选择。', 'Table train/validation metrics describe the latest fold; all folds are available below. Final test never selects parameters.')}</p>
        {onApplyThresholds && report.selectedPolicy && report.testRiskStatus !== 'BREACH' && <button type="button" className="my-2 text-primary underline"
          onClick={() => onApplyThresholds(report.jointThresholds!.selected.buy, report.jointThresholds!.selected.sell)}>
          {text('应用联合优化的触发阈值', 'Apply joint trigger thresholds')}</button>}
        <details><summary>{text('全部候选与滚动折', 'All candidates and walk-forward folds')}</summary><pre className="max-h-64 overflow-auto">{JSON.stringify(report.jointThresholds, null, 2)}</pre></details>
      </div>}
      <div className="overflow-x-auto">
        <table className="w-full whitespace-nowrap text-left">
          <thead><tr>{[text('策略', 'Policy'), text('训练收益', 'Train return'), text('验证收益', 'Validation return'),
            text('测试收益', 'Test return'), text('测试 CAGR', 'Test CAGR'), text('测试 Sharpe', 'Test Sharpe'),
            text('测试最大回撤', 'Test Max DD'), text('测试换手', 'Test turnover'), text('测试机会遗憾', 'Test opportunity regret')]
            .map(label => <th className="p-2" key={label}>{label}</th>)}</tr></thead>
          <tbody>{report.policies.map(policy => <tr key={policy.name} className="border-t border-border/40">
            <td className="p-2"><button type="button" className="text-primary underline" onClick={() => setInspected(policy.name)}>
              {names[policy.name] ?? policy.name}{policy.name === report.selectedPolicy ? ' ✓' : ''}</button></td>
            <td className="p-2">{policy.metrics.train ? `${policy.metrics.train.totalReturnPct.toFixed(2)}%` : '—'}</td>
            <td className="p-2">{policy.metrics.validation ? `${policy.metrics.validation.totalReturnPct.toFixed(2)}%` : '—'}</td>
            <td className="p-2">{policy.metrics.test.totalReturnPct.toFixed(2)}%</td>
            <td className="p-2">{policy.metrics.test.actualCagr === null ? text('未成熟', 'Immature') : `${((policy.metrics.test.actualCagr ?? policy.metrics.test.cagrPct / 100) * 100).toFixed(2)}%`}</td>
            <td className="p-2">{policy.metrics.test.sharpe.toFixed(2)}</td>
            <td className="p-2">{policy.metrics.test.maxDrawdownPct.toFixed(2)}%</td>
            <td className="p-2">{policy.metrics.test.turnover.toFixed(2)}×</td>
            <td className="p-2">{policy.name === 'BUY_HOLD' ? '—' : `${((policy.metrics.test.opportunityRegret ?? 0) * 100).toFixed(2)} ${text('对数点', 'log points')}`}</td>
          </tr>)}</tbody>
        </table>
      </div>
      {selected && <>
        <AutoTuneEconomicChart policy={selected} language={language} />
        {selected.metrics.test.requiredNav != null && <div className="my-2 rounded border border-border/40 p-2">
          <p>{text('目标 / 实际 NAV', 'Target / actual NAV')}: {selected.metrics.test.requiredNav.toFixed(4)} / {selected.metrics.test.finalNav.toFixed(4)}
            {' · '}{text('最大仓位', 'Maximum exposure')}: {pct(selected.metrics.test.maximumExposure)}</p>
          {selected.thresholds && <p>BUY {selected.thresholds.buy} / SELL {selected.thresholds.sell}</p>}
          {selected.metrics.test.finalBudget != null && <p>{text('实际期末资金', 'Actual ending budget')}: {selected.metrics.test.finalBudget.toFixed(2)}
            {' · '}{text('持有收益捕获', 'Buy & Hold return capture')}: {selected.metrics.test.returnCaptureVsHold == null ? '—' : pct(selected.metrics.test.returnCaptureVsHold)}
            {' · '}{text('回撤降低百分点', 'Drawdown reduction pp')}: {selected.metrics.test.drawdownReductionPp?.toFixed(2)}
            {' · '}{text('Sharpe 改善', 'Sharpe improvement')}: {selected.metrics.test.sharpeImprovement?.toFixed(3)}</p>}
          <p>{text('标普收益 / 超额收益', 'S&P return / excess return')}: {selected.metrics.test.benchmarkReturn == null ? '—' : pct(selected.metrics.test.benchmarkReturn)} / {selected.metrics.test.excessReturn == null ? '—' : pct(selected.metrics.test.excessReturn)}</p>
          <p>{text('击败标普区间', 'Beat S&P intervals')}: {selected.metrics.test.benchmarkBeatPeriods ?? 0} / {selected.metrics.test.totalEvaluationPeriods ?? 0}
            {' · '}{text('基准奖励 / CAGR 惩罚', 'Benchmark reward / CAGR penalty')}: {(selected.metrics.test.benchmarkReward ?? 0).toFixed(5)} / {(selected.metrics.test.cagrPenalty ?? 0).toFixed(5)}</p>
          {selected.metrics.test.riskRejected && <p className="text-red-500">{text('该区间超过硬回撤限制，不能由奖励抵消。', 'This segment breaches the hard drawdown limit; rewards cannot override it.')}</p>}
          <p className="text-secondary-text">{text('增长目标是用户设定的门槛，不是收益保证。奖励不计入真实 NAV。', 'The growth target is a user-defined hurdle, not a return guarantee. Rewards are not added to NAV.')}</p>
        </div>}
        <div className="my-3 rounded border border-border/40 p-2" aria-label={text('机会分析', 'Opportunity Analysis')}>
          <h4 className="font-medium">{text('机会分析', 'Opportunity Analysis')}</h4>
          <p>{text('错失盈利 BUY / 未避免下跌 SELL 次数', 'Missed profitable BUY / downside-avoidance SELL counts')}: {selected.metrics.test.missedUpsideCount ?? 0} / {selected.metrics.test.missedDownsideCount ?? 0}</p>
          <p>{text('错失上涨 / 未避免下跌', 'Missed upside / downside avoidance')}: {((selected.metrics.test.missedUpsideRegret ?? 0) * 100).toFixed(2)} / {((selected.metrics.test.missedDownsideRegret ?? 0) * 100).toFixed(2)} {text('对数点', 'log points')}</p>
          <p>{text('阈值未触发 BUY / SELL', 'Threshold-missed BUY / SELL')}: {selected.metrics.test.thresholdMissedBuyCount ?? 0} / {selected.metrics.test.thresholdMissedSellCount ?? 0}
            {' · '}{text('现金约束触发', 'Budget-constrained triggers')}: {selected.metrics.test.budgetConstrainedDecisions}</p>
          <p className="text-secondary-text">{text('单股全部持有不会因现金为零而受罚。阈值诊断使用下一交易日开盘至收盘，单独显示，不与反事实遗憾重复相加。', 'Full same-stock exposure is not penalized for having zero cash. Threshold diagnostics use the next open-to-close interval and are reported separately, without adding them again to counterfactual regret.')}</p>
          <p>{text('阈值估计错失收益', 'Estimated threshold-missed return')}: {(((selected.metrics.test.thresholdUpsideRegret ?? 0) + (selected.metrics.test.thresholdDownsideRegret ?? 0)) * 100).toFixed(2)}% {text('NAV 等值（诊断）', 'NAV-equivalent (diagnostic)')}</p>
          {largestThresholdMiss && <p>{text('最大阈值错失', 'Largest threshold miss')}: {largestThresholdMiss.date}
            {' · '}{largestThresholdMiss.missedBuyRegret > 0 ? `BUY ${largestThresholdMiss.buyScore} / ${largestThresholdMiss.buyThreshold}` : `SELL ${largestThresholdMiss.sellScore} / ${largestThresholdMiss.sellThreshold}`}
            {' · '}{text('后续行情', 'Forward move')}: {pct(largestThresholdMiss.assetForwardReturn)}</p>}
          <details><summary>{text('逐日评分与未触发机会', 'Daily scores and missed-trigger opportunities')}</summary>
            <pre className="max-h-64 overflow-auto">{JSON.stringify(selected.scoreObservations ?? [], null, 2)}</pre></details>
        </div>
        <h4 className="mt-3 font-medium">{text('测试期预算 / 仓位时间线', 'Test budget / exposure timeline')} · {names[selected.name]}</h4>
        <p className="my-2 text-secondary-text">
          NAV {selected.metrics.test.initialNav.toFixed(4)} → {selected.metrics.test.finalNav.toFixed(4)}
          {' · '}{text('交易', 'Fills')} {selected.metrics.test.tradeCount}
          {' · '}{text('费用', 'Costs')} {selected.metrics.test.transactionCost.toFixed(6)}
          {' · '}{text('平均仓位', 'Average exposure')} {selected.metrics.test.averageExposurePct.toFixed(1)}%
          {' · '}{text('低样本回退', 'Low-support fallback')} {selected.metrics.test.fallbackPct.toFixed(1)}%
        </p>
        <div className="max-h-80 overflow-auto">
          <table className="w-full text-left">
            <thead><tr>{[text('日期 / 信号', 'Date / trigger'), text('执行后 NAV', 'NAV after fill'),
              text('现金 / 仓位', 'Cash / exposure'), text('目标 → 实际', 'Target → actual'), text('奖励', 'Reward'), text('明细', 'Details')]
              .map(label => <th className="p-2" key={label}>{label}</th>)}</tr></thead>
            <tbody>{selected.transitions.map((transition, index) => {
              const portfolio = transition.execution?.after ?? transition.portfolioBefore;
              return <tr key={index} className="border-t border-border/30 align-top">
                <td className="p-2 whitespace-nowrap">{transition.triggerDate}<br />{transition.triggerDirection} {transition.triggerScore}</td>
                <td className="p-2 tabular-nums">{portfolio.nav.toFixed(4)}</td>
                <td className="p-2 tabular-nums">{pct(portfolio.cash / portfolio.nav)} / {pct(portfolio.currentExposure)}
                  <div className="mt-1 h-1.5 w-28 bg-secondary-text/20" role="img" aria-label={`${text('股票仓位', 'Stock exposure')}: ${pct(portfolio.currentExposure)}`}>
                    <div className="h-full bg-primary" style={{ width: pct(portfolio.currentExposure) }} />
                  </div></td>
                <td className="p-2">{pct(transition.requestedTargetExposure)} → {pct(portfolio.currentExposure)}
                  {transition.riskReason && transition.riskReason !== 'NOT_APPLICABLE' && <div>{text('风险允许', 'Risk allowed')}: {pct(transition.allowedTargetExposure)} · {transition.riskReason}</div>}</td>
                <td className="p-2 tabular-nums">{transition.reward.toFixed(6)}
                  <div>{text('学习', 'Learning')}: {(transition.rewardAfterRegret ?? transition.reward).toFixed(6)}</div>
                  <div>{reason(transition.opportunityReason ?? 'NO_REGRET')}</div></td>
                <td className="p-2"><details><summary className="cursor-pointer">{reason(transition.executionReason)} · {reason(transition.policyReason)}</summary>
                  <p className="my-1">{transition.stateBefore.triggerBucket} · {transition.stateBefore.pnlBucket} · {transition.stateBefore.regime} · Cash {transition.stateBefore.cashBucket ?? '—'}</p>
                  {transition.stateBefore.volatilityRegime && <p>{transition.signalStatus} · {transition.stateBefore.volatilityRegime} · DD {transition.stateBefore.drawdownBucket} · Q {transition.qConfidence}</p>}
                  <p>{text('执行', 'Execution')}: {transition.executionDate ?? '—'} · {transition.execution?.side ?? 'HOLD'}
                    {' · '}{text('金额', 'Notional')}: {transition.execution?.tradeValue.toFixed(6) ?? '0'}
                    {' · '}{text('费用', 'Cost')}: {transition.execution?.transactionCost.toFixed(6) ?? '0'}</p>
                  {transition.tradeNavFraction != null && <p>{text('交易占当前预算', 'Trade / current NAV')}: {pct(transition.tradeNavFraction)}
                    {transition.cashSpentFraction != null ? ` · ${text('使用现金', 'Cash spent')}: ${pct(transition.cashSpentFraction)}` : ''}</p>}
                  <p>{text('下一触发', 'Next trigger')}: {transition.nextTriggerDate} · {transition.durationDays}D
                    {' · NAV '}{transition.navAtNextTrigger.toFixed(4)} · {text('行情变化', 'Market move')} {pct(transition.marketMove)}</p>
                  <p>{text('训练日期支持数', 'Training-date support')}: {transition.visitCount}</p>
                  <pre className="mt-2 max-w-lg overflow-auto text-[10px]">{JSON.stringify(transition, null, 2)}</pre>
                </details></td>
              </tr>;
            })}</tbody>
          </table>
        </div>
        <details className="mt-2"><summary className="cursor-pointer">{text('完整指标与保护性 / 期末成交', 'Full metrics and protective / terminal executions')}</summary>
          <pre className="max-h-64 overflow-auto text-[10px]">{JSON.stringify({ metrics: selected.metrics, executions: selected.executions }, null, 2)}</pre>
        </details>
      </>}
      <details className="mt-3"><summary className="cursor-pointer">{text('Q 表检查', 'Q-table inspection')} · {report.uniqueStatesVisited} {text('状态', 'states')}</summary>
        <p className="my-2 text-secondary-text">{text('访问数按不同训练触发日期统计；更新次数包含重复训练回合。勾选为离散仓位桶下的推荐，真实决策仍按实际仓位过滤。',
          'Visits count distinct training trigger dates; updates include repeated episodes. A check marks the recommendation at the encoded exposure bucket; actual decisions use continuous exposure masks.')}</p>
        <input className="my-2 rounded border border-border bg-card p-2" value={stateFilter} onChange={e => setStateFilter(e.target.value)}
          placeholder="STRONG_BUY" aria-label={text('筛选 Q 状态', 'Filter Q states')} />
        <div className="max-h-64 overflow-auto"><table className="w-full text-left">
          <thead><tr>{[text('状态', 'State'), text('目标', 'Target'), 'Q', text('访问 / 更新', 'Visits / updates')].map(label => <th className="p-2" key={label}>{label}</th>)}</tr></thead>
          <tbody>{rows.map((row, index) => <tr className="border-t border-border/30" key={index}>
            <td className="p-2">{row.state.triggerBucket} · {pct(row.state.exposureBucket)} · Cash {row.state.cashBucket ?? '—'} · {row.state.pnlBucket} · {row.state.regime}
              {row.state.volatilityRegime ? ` · ${row.state.volatilityRegime} · DD ${row.state.drawdownBucket}` : ''}</td>
            <td className="p-2">{pct(row.targetExposure)}{row.recommendedAtBucket ? ' ✓' : ''}{row.validAtBucket ? '' : ' ×'}</td>
            <td className="p-2">{row.qValue.toFixed(6)}</td><td className="p-2">{row.visitCount} / {row.updateCount}</td>
          </tr>)}</tbody>
        </table></div>
        <pre className="mt-2 overflow-auto text-[10px]">{JSON.stringify(report.config, null, 2)}</pre>
      </details>
    </section>
  );
}
