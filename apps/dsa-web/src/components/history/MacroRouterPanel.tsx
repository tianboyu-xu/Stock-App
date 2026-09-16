import type { MacroRouterReport } from '../../api/stocks';

const number = (value: number | null | undefined, digits = 3) =>
  typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
const percent = (value: number | null | undefined) =>
  typeof value === 'number' && Number.isFinite(value) ? `${value >= 0 ? '+' : ''}${value.toFixed(2)}%` : '—';

const REGIMES: Record<string, [string, string]> = {
  goldilocks: ['Goldilocks', '温和增长 / 通胀回落'],
  reflation: ['Reflation', '再通胀'],
  stagflation: ['Stagflation', '滞胀'],
  slowdown: ['Slowdown', '增长放缓'],
  recession: ['Recession risk', '衰退风险'],
  recovery: ['Recovery', '复苏'],
  expansion: ['Expansion', '扩张'],
  disinflation: ['Disinflation', '通胀回落'],
  unknown: ['Insufficient evidence', '证据不足'],
};
const FACTORS: Record<string, [string, string]> = {
  growth: ['Growth', '增长'], inflation: ['Inflation momentum', '通胀动量'],
  labor: ['Labor market', '劳动力市场'], liquidity: ['Financial conditions', '金融条件'],
};

export function MacroRouterPanel({ report, language }: { report?: MacroRouterReport | null; language: string }) {
  const zh = language === 'zh';
  const text = (en: string, cn: string) => zh ? cn : en;
  const regimeName = (key: string) => REGIMES[key.toLowerCase()]?.[zh ? 1 : 0] ?? key;
  const strategyName = (key: string) => key === 'CASH' ? text('CASH · stay in cash', 'CASH · 保持现金') : `${text('Strategy', '策略')} ${key}`;
  const current = report?.current;
  const diagnostics = report?.diagnostics;
  const reason = report?.reason;

  return <section className="mt-3 space-y-3 rounded-xl border border-cyan-500/30 bg-cyan-500/5 p-4 text-xs" aria-label={text('MATR macro strategy router', 'MATR 宏观策略路由')} data-testid="macro-router-panel">
    <div className="flex flex-wrap items-center justify-between gap-2">
      <h3 className="text-sm font-semibold">{text('MATR · Quarterly macro strategy', 'MATR · 季度宏观策略')}</h3>
      <span className="rounded border border-border px-2 py-1">{text('2 weeks · at most 1 buy + 1 sell per window', '双周窗口 · 每窗最多买入、卖出各一次')}</span>
    </div>
    <p className="text-secondary-text">{text(
      'At each quarter start, use the previous quarter’s data available at that time to select A–F or cash. Refit on completed historical quarters; the selected strategy stays fixed for the quarter.',
      '每季度开始时，使用当时已发布的上季度数据，在 A–F 与现金中选择；仅用已完成的历史季度重新训练，季度内固定所选策略。',
    )}</p>
    {!report ? <p role="status">{text('Run Auto Tune to include MATR in the strategy comparison and build the quarterly macro report.', '运行 Auto Tune，将 MATR 加入策略对比并生成季度宏观报告。')}</p> : null}
    {report && report.status !== 'READY' ? <div role="status" className="rounded-lg border border-amber-500/30 bg-amber-500/5 p-3">
      <p className="font-medium">{report.status === 'INSUFFICIENT_HISTORY'
        ? text('Not enough completed quarters to validate the router', '已完成的历史季度不足，暂无法验证路由策略')
        : text('Macro strategy data unavailable', '宏观策略数据暂不可用')}</p>
      {reason ? <p className="mt-1 break-words">{reason}</p> : null}
      {reason && /FRED.*(KEY|CONFIG)|API_KEY/i.test(reason) ? <p className="mt-1">{text(
        'Configure FRED_API_KEY on the server, then rerun Auto Tune. Historical publication vintages are required.',
        '在服务端配置 FRED_API_KEY 后重新运行 Auto Tune；需要宏观数据的历史发布版本。',
      )}</p> : null}
    </div> : null}
    {current ? <>
      <div className="grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-border bg-background/50 p-3">
          <p className="text-secondary-text">{current.quarter} · {text('Quarter-start regime estimate', '季初宏观阶段估计')}</p>
          <p className="mt-1 text-base font-semibold text-foreground">{regimeName(current.regime.key)}</p>
          <p className="mt-1 text-secondary-text">{text('Prior-quarter observations', '上季观测值')}: {current.featureQuarter}</p>
        </div>
        <div className="rounded-lg border border-border bg-background/50 p-3">
          <p className="text-secondary-text">{text('Strategy to reference this quarter', '本季度参考策略')}</p>
          <p className="mt-1 text-base font-semibold text-cyan-600 dark:text-cyan-400">{strategyName(current.selectedStrategy)}</p>
          <p className="mt-1 text-secondary-text">{text('Confidence', '置信度')}: {zh ? { low: '低', medium: '中', high: '高' }[current.confidence] : current.confidence}</p>
        </div>
        <div className="rounded-lg border border-border bg-background/50 p-3 tabular-nums">
          <p className="text-secondary-text">{text('Training evidence', '训练证据')}</p>
          <p className="mt-1 text-base font-semibold text-foreground">{current.trainingQuarters} {text('quarters', '个季度')}</p>
          <p className="mt-1 text-secondary-text">{text('Ranking gap (utility)', '排名差距（效用）')}: {number(current.scoreGap)}</p>
          {current.cashMargin != null ? <p className="mt-1 text-secondary-text">{text('Advantage over cash / required margin', '相对现金优势 / 所需门槛')}: {number(current.cashMargin)} / {number(current.confidenceThreshold)}</p> : null}
        </div>
      </div>
      <p className="text-secondary-text">{text(
        `Known by ${current.asOf}. This is an estimate from information available at the quarter start, not a confirmed current economic phase.`,
        `数据截至 ${current.asOf} 已知。这是基于季初可得信息的阶段估计，并非已确认的当前经济阶段。`,
      )}</p>
      <div className="overflow-x-auto">
        <table className="w-full text-left tabular-nums" aria-label={text('Current quarter strategy ranking', '本季度策略排名')}>
          <thead><tr className="border-b border-border text-secondary-text">
            <th className="p-2">{text('Strategy', '策略')}</th>
            <th className="p-2 text-right">{text('Expected utility', '预期效用')}</th>
            <th className="p-2 text-right">{text('Similar-quarter utility', '相似季度效用')}</th>
          </tr></thead>
          <tbody>{current.ranking.map(row => <tr key={row.strategyKey} className={row.strategyKey === current.selectedStrategy ? 'bg-cyan-500/10 font-medium' : ''}>
            <td className="p-2">{strategyName(row.strategyKey)}</td>
            <td className="p-2 text-right">{number(row.expectedUtility)}</td>
            <td className="p-2 text-right">{number(row.analogUtility)}</td>
          </tr>)}</tbody>
        </table>
      </div>
      <p className="text-secondary-text">{text('Utility and ranking gaps are model scores, not forecast return percentages. Confidence is an evidence category, not a probability of profit.', '效用及排名差距是模型评分，不是预测收益率；置信度表示证据强弱，并非盈利概率。')}</p>
      <details>
        <summary className="cursor-pointer font-medium">{text('Macro factors and selected features', '宏观因子与入选特征')}</summary>
        <dl className="mt-2 grid gap-x-6 gap-y-2 sm:grid-cols-2">{Object.entries(current.regime.factors).map(([key, value]) => <div className="flex justify-between gap-3" key={key}>
          <dt className="break-words text-secondary-text">{FACTORS[key]?.[zh ? 1 : 0] ?? key}</dt><dd className="tabular-nums">{number(value)}</dd>
        </div>)}</dl>
        {current.topFeatures?.length ? <p className="mt-2">{text('Selected features', '入选特征')}: {current.topFeatures.join(', ')}</p> : null}
        <p className="mt-2 break-all text-secondary-text">{text('Historical snapshot', '历史数据快照')}: {current.snapshotId}</p>
      </details>
    </> : null}
    {report?.correlations.length ? <details>
      <summary className="cursor-pointer font-medium">{text('Historical macro / strategy correlations', '历史宏观 / 策略相关性')}</summary>
      <p className="mt-2 text-secondary-text">{text('Associations use historical training quarters only. They do not establish causality.', '相关性仅使用历史训练季度，不代表因果关系。')}</p>
      <div className="mt-2 max-h-72 overflow-auto"><table className="w-full text-left tabular-nums" aria-label={text('Macro strategy correlations', '宏观策略相关性')}>
        <thead><tr className="border-b border-border text-secondary-text">
          <th className="p-2">{text('Feature', '特征')}</th><th className="p-2">{text('Strategy', '策略')}</th>
          <th className="p-2 text-right">{text('Correlation', '相关系数')}</th>
          <th className="p-2 text-right">{text('Sign stability', '方向稳定度')}</th><th className="p-2 text-right">{text('Quarters', '季度数')}</th>
        </tr></thead>
        <tbody>{report.correlations.map((row, i) => <tr key={`${row.feature}-${row.strategyKey}-${i}`}>
          <td className="p-2">{row.feature}</td><td className="p-2">{row.strategyKey}</td>
          <td className="p-2 text-right">{number(row.correlation)}</td><td className="p-2 text-right">{number(row.signStability, 2)}</td><td className="p-2 text-right">{row.sampleCount}</td>
        </tr>)}</tbody>
      </table></div>
    </details> : null}
    {diagnostics ? <>
      <div className="flex flex-wrap gap-x-5 gap-y-2 rounded-lg border border-border p-3 tabular-nums" aria-label={text('Out-of-sample results', '样本外结果')}>
        <span>{text('Completed OOS quarters', '已完成样本外季度')}: {diagnostics.oosQuarters}</span>
        {diagnostics.startDate && diagnostics.endDate ? <span>{diagnostics.startDate} ~ {diagnostics.endDate}</span> : null}
        <span>{text('Net return', '净收益')}: {percent(diagnostics.totalReturnPct)}</span>
        <span>SPY: {percent(diagnostics.spyTotalReturnPct)}</span>
        <span>{text('Win rate', '胜率')}: {number(diagnostics.winRatePct, 1)}%</span>
        <span>{text('Beat SPY', '跑赢 SPY')}: {number(diagnostics.beatSpyRatePct, 1)}%</span>
        <span>{text('Mean regret (utility)', '平均后悔值（效用）')}: {number(diagnostics.meanRegret)}</span>
        {diagnostics.cashQuarterRatePct != null ? <span>{text('Cash quarters', '现金季度占比')}: {number(diagnostics.cashQuarterRatePct, 1)}%</span> : null}
        {diagnostics.tradeCount != null ? <span>{text('Trades', '交易次数')}: {diagnostics.tradeCount}</span> : null}
        {diagnostics.activeWindowRatePct != null ? <span>{text('Windows with trades', '有交易窗口占比')}: {number(diagnostics.activeWindowRatePct, 1)}%</span> : null}
        {diagnostics.exposureRatePct != null ? <span>{text('Sessions with exposure', '持仓交易日占比')}: {number(diagnostics.exposureRatePct, 1)}%</span> : null}
      </div>
      <p className="text-secondary-text">{text('These totals use completed quarters. The NAV chart also includes completed windows from the current quarter, and may show a shorter common comparison period.', '此处汇总仅统计已完成季度；NAV 图还包含当前季度已完成的窗口，并可能显示较短的共同对比区间。')}</p>
      {diagnostics.familyComparisons?.length ? <details>
        <summary className="cursor-pointer font-medium">{text('Routing attribution: each family with the same two-week execution', '路由归因：各策略采用相同双周执行')}</summary>
        <p className="mt-2 text-secondary-text">{text('All rows use the same completed quarters and costs as MATR, with parameters selected before each window. This comparison separates routing choices from technical strategy performance; it differs from the global Auto Tune test split.', '所有行使用与 MATR 相同的已完成季度、费用及双周执行，并在每个窗口开始前选定参数。此对比用于区分路由选择与技术策略自身的表现，其区间和普通 Auto Tune 测试划分不同。')}</p>
        <div className="mt-2 overflow-auto"><table className="w-full text-left tabular-nums" aria-label={text('Two-week family comparisons', '双周策略对比')}>
          <thead><tr className="border-b border-border text-secondary-text">
            <th className="p-2">{text('Strategy', '策略')}</th><th className="p-2 text-right">{text('Net return', '净收益')}</th>
            <th className="p-2 text-right">{text('Max drawdown', '最大回撤')}</th><th className="p-2 text-right">{text('Trades', '交易次数')}</th>
            <th className="p-2 text-right">{text('Windows with trades', '有交易窗口')}</th><th className="p-2 text-right">{text('Sessions with exposure', '持仓交易日')}</th>
          </tr></thead>
          <tbody>{diagnostics.familyComparisons.map(row => <tr key={row.strategyKey}>
            <td className="p-2">{strategyName(row.strategyKey)}</td><td className="p-2 text-right">{percent(row.totalReturnPct)}</td>
            <td className="p-2 text-right">{number(row.maxDrawdownPct, 2)}%</td><td className="p-2 text-right">{row.tradeCount}</td>
            <td className="p-2 text-right">{number(row.activeWindowRatePct, 1)}%</td><td className="p-2 text-right">{number(row.exposureRatePct, 1)}%</td>
          </tr>)}</tbody>
        </table></div>
      </details> : null}
    </> : null}
    {report?.history.length ? <details>
      <summary className="cursor-pointer font-medium">{text('Historical quarter and two-week window results', '历史季度与双周交易窗口结果')} ({report.history.length})</summary>
      <p className="mt-2 text-secondary-text">{text('Regret compares the selected strategy with the best strategy known after that quarter. It is a diagnostic and is not used to select that quarter’s strategy.', '后悔值对比所选策略与当季结束后才知道的最优策略，仅用于诊断，不用于选择该季度策略。')}</p>
      <div className="mt-2 space-y-2">{report.history.slice().reverse().map(quarter => <details className="rounded-lg border border-border p-2" key={quarter.quarter}>
        <summary className="cursor-pointer tabular-nums">{quarter.quarter}{quarter.complete === false ? text(' (in progress)', '（进行中）') : ''} · {strategyName(quarter.selectedStrategy)} · {regimeName(quarter.regime)} · {percent(quarter.netReturnPct)} · SPY {percent(quarter.spyReturnPct)} · {text('Regret', '后悔值')} {number(quarter.regret)}</summary>
        <div className="mt-2 overflow-auto"><table className="w-full text-left tabular-nums" aria-label={`${quarter.quarter} ${text('trade windows', '交易窗口')}`}>
          <thead><tr className="border-b border-border text-secondary-text">
            <th className="p-2">{text('Window', '窗口')}</th><th className="p-2">{text('Strategy', '策略')}</th>
            <th className="p-2">{text('Buy / sell', '买入 / 卖出')}</th><th className="p-2 text-right">{text('Net return', '净收益')}</th><th className="p-2 text-right">SPY</th>
          </tr></thead>
          <tbody>{quarter.windows.map(window => <tr key={window.startDate}>
            <td className="whitespace-nowrap p-2">{window.startDate} ~ {window.endDate}</td><td className="p-2">{window.strategyKey}</td>
            <td className="whitespace-nowrap p-2">{window.entryDate ?? '—'} / {window.exitDate ?? '—'}</td>
            <td className="p-2 text-right">{percent(window.netReturnPct)}</td><td className="p-2 text-right">{percent(window.spyReturnPct)}</td>
          </tr>)}</tbody>
        </table></div>
      </details>)}</div>
    </details> : null}
    {report?.warnings?.map((warning, i) => <p key={i} className="text-secondary-text">{warning}</p>)}
  </section>;
}
