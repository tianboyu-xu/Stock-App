import { CartesianGrid, Legend, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { AutoTuneResponse } from '../../api/stocks';
import { STRATEGY_FAMILIES, STRATEGY_FAMILY_COLORS, combinedStrategyCurves, formatTriggerText, isVisibleTradeMark, strategyFamilyForView, strategyPresentation, type StrategyFamily } from './autoTunePresentation';

const pct = (value?: number | null) => value == null ? '—' : `${value.toFixed(1)}%`;

interface AutoTuneStrategyViewProps {
  report: AutoTuneResponse;
  language: string;
  selectedFamily: StrategyFamily;
  selectedStrategyKey?: string | null;
  days: number;
}

export function AutoTuneStrategyView({ report, language, selectedFamily, selectedStrategyKey, days }: AutoTuneStrategyViewProps) {
  const zh = language === 'zh';
  const text = (en: string, cn: string) => zh ? cn : en;
  const displayFamily = strategyFamilyForView(report, selectedFamily, selectedStrategyKey);
  const family = STRATEGY_FAMILIES.find(item => item.key === displayFamily)!;
  const familyName = zh ? family.zh : family.en;
  const view = strategyPresentation(report, displayFamily);
  const combined = combinedStrategyCurves(report, [displayFamily]);
  const rows = days > 0 ? combined.rows.slice(-days) : combined.rows;
  const visibleMarks = view.marks.filter(isVisibleTradeMark);

  return <section className="my-3 space-y-3 text-xs" aria-label={text('Selected strategy results', '当前策略结果')}>
    <p className="text-secondary-text">
      {text(
        `Selected strategy: ${familyName}. Trade markers are shown on the technical price chart; this chart uses the same ${days}-bar range.`,
        `当前策略：${familyName}。交易标记显示在技术指标价格图中；本图使用相同的 ${days} 根数据范围。`,
      )}
    </p>
    <div className="space-y-3 rounded-xl border border-border p-3" data-testid="strategy-combined-chart">
      <div className="flex flex-wrap items-center gap-3">
        <h3 className="font-semibold">{text('Adaptive budget / NAV', '自适应预算 / NAV')}</h3>
        <span className="text-secondary-text">{familyName}</span>
        <span className="ml-auto text-secondary-text">{text('Last', '最近')} {days} {text('bars', '根')}</span>
      </div>
      <div aria-label="NAV / S&P 500 / growth target" data-testid="strategy-nav-chart">
        {!combined.hasBenchmark && <p>{text('Adjusted SPY benchmark unavailable; no substitute is plotted.', '缺少复权 SPY 基准，不绘制替代基准。')}</p>}
        {rows.length && !view.unavailable ? <ResponsiveContainer width="100%" height={260}>
          <LineChart data={rows} margin={{ top: 15, right: 25, bottom: 10, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={.2} />
            <XAxis dataKey="date" minTickGap={65} tick={{ fontSize: 10 }} />
            <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10 }} tickFormatter={value => Number(value).toFixed(2)} />
            <Tooltip formatter={value => typeof value === 'number' ? value.toFixed(4) : value} />
            <Legend />
            {!view.unavailable ? <Line
              dataKey={`nav:${displayFamily}`}
              name={`${familyName} NAV`}
              stroke={STRATEGY_FAMILY_COLORS[displayFamily]}
              dot={false}
              connectNulls={false}
              isAnimationActive={false}
            /> : null}
            <Line dataKey="benchmarkNav" name="S&P 500 (SPY adjusted)" stroke="#a78bfa" dot={false} connectNulls={false} isAnimationActive={false} />
            <Line dataKey="requiredNav" name={`${Math.round(combined.target * 100)}% CAGR ${text('target', '目标')}`} stroke="#fbbf24" strokeDasharray="5 4" dot={false} connectNulls={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer> : <p role="status">
          {view.unavailable
            ? text('This strategy has no saved result. Run Auto Tune again.', '该策略没有已保存结果，请重新运行 Auto Tune。')
            : text('No NAV curve is available for this range.', '该范围没有可用的 NAV 曲线。')}
        </p>}
      </div>
      <details>
        <summary>{text('Executed trade details', '已成交交易明细')} ({visibleMarks.length})</summary>
        <div className="max-h-64 overflow-auto">
          <ul className="space-y-2 py-2">
            {visibleMarks.map((mark, index) => (
              <li key={`${mark.date}-${index}`}>
                {mark.date} · {mark.side} · {formatTriggerText(mark)} · {mark.reason}
              </li>
            ))}
          </ul>
        </div>
      </details>
    </div>
    {view.legacy ? <p>
      {familyName} · {text('Validation-selected variant', '按验证期选择的版本')}: {view.legacy.key} · {text('Test history only; signals fill at the next open, with protective exits and a final liquidation.', '仅展示测试期历史；信号次日开盘成交，包含保护性退出和期末平仓。')}
    </p> : null}
    {view.policy ? <>
      <p className="font-medium">{familyName} · {text('Backtest completed', '回测完成')} · {view.policy.name}</p>
      <div className="flex flex-wrap gap-x-5 gap-y-2 rounded border border-border p-3 tabular-nums">
        <span>{text('Return', '收益')}: {pct(view.policy.metrics.test.totalReturnPct)}</span>
        <span>{text('Max drawdown', '最大回撤')}: {pct(view.policy.metrics.test.maxDrawdownPct)}</span>
        <span>{text('Trades', '成交次数')}: {view.policy.metrics.test.tradeCount}</span>
        <span>{text('Final NAV', '期末净值')}: {view.policy.metrics.test.finalNav?.toFixed(4) ?? '—'}</span>
      </div>
      {view.diagnostic && selectedFamily !== 'aces' ? <p>{text('Diagnostic simulation — no policy passed selection', '诊断模拟：没有策略通过筛选')}</p> : null}
    </> : null}
    {view.policy && view.readiness && view.readiness.status !== 'PASS' ? <p className="text-secondary-text">
      {text('Research assessment: not accepted. The backtest above includes all gains and losses; validation checks do not suppress its results.', '研究评估：未通过。上方回测完整展示盈亏，验证检查不会隐藏结果。')}
    </p> : null}
    {view.simulationNotes?.map((note, index) => <p key={index} className="text-secondary-text">{note}</p>)}
    </section>;
}
