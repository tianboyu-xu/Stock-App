import { CartesianGrid, Legend, Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { AutoTuneResponse } from '../../api/stocks';
import { MacroRouterPanel } from './MacroRouterPanel';
import { STRATEGY_FAMILIES, STRATEGY_FAMILY_COLORS, BENCHMARK_LINE_COLOR, TARGET_LINE_COLOR, TRADE_SIDE_COLORS, combinedStrategyCurves, formatTriggerText, isVisibleTradeMark, navTradeDots, rebaseRowsFromPurchaseDate, strategyFamilyForView, strategyPresentation, withTradePnL, type HoldingAnchor, type StrategyFamily } from './autoTunePresentation';

const pct = (value?: number | null) => value == null ? '—' : `${value.toFixed(1)}%`;
const signedPct = (value?: number | null) => value == null
  ? '—'
  : `${value >= 0 ? '+' : ''}${value.toFixed(1)}%`;
const price = (value?: number | null) => typeof value === 'number' && Number.isFinite(value)
  ? value.toFixed(2)
  : '—';

interface AutoTuneStrategyViewProps {
  report: AutoTuneResponse;
  language: string;
  selectedFamily: StrategyFamily;
  selectedStrategyKey?: string | null;
  days: number;
  holding: HoldingAnchor | null;
  holdingAnchored: boolean;
  onToggleHolding: () => void;
  shareDateAxis?: boolean;
}

export function AutoTuneStrategyView({ report, language, selectedFamily, selectedStrategyKey, days, holding, holdingAnchored, onToggleHolding, shareDateAxis = false }: AutoTuneStrategyViewProps) {
  const zh = language === 'zh';
  const text = (en: string, cn: string) => zh ? cn : en;
  const displayFamily = strategyFamilyForView(report, selectedFamily, selectedStrategyKey);
  const family = STRATEGY_FAMILIES.find(item => item.key === displayFamily)!;
  const familyName = zh ? family.zh : family.en;
  const view = strategyPresentation(report, displayFamily);
  const allFamilies = STRATEGY_FAMILIES.map(item => item.key);
  const combined = combinedStrategyCurves(report, allFamilies);
  // The holding toggle is only offered when the selected stock is held in
  // Current positions; anchoring restarts every NAV line from the buy date.
  // Toggle state lives in the parent, which also filters price-chart markers
  // and the shared date axis by it. The card itself never moves.
  const anchorActive = holdingAnchored && holding != null;
  const anchored = anchorActive && holding
    ? rebaseRowsFromPurchaseDate(combined.rows, holding.purchaseDate)
    : null;
  const baseRows = days > 0 ? combined.rows.slice(-days) : combined.rows;
  const rows = anchored ? anchored.rows : baseRows;
  const anchorDate = anchored?.anchorDate ?? null;
  const hasAnyStrategyLine = rows.some(row => allFamilies.some(item => row[`nav:${item}`] != null));
  const visibleFamilyCount = allFamilies.filter(item => rows.some(row => row[`nav:${item}`] != null)).length;
  // Families without a plottable curve are listed explicitly (with the saved
  // reason) instead of silently disappearing from the combined chart.
  const missingFamilies = combined.views.filter(
    ({ view: itemView }) => !itemView.curve.length,
  );
  const visibleMarks = view.marks.filter(isVisibleTradeMark);
  // When anchored, the details list follows the chart and only covers the
  // holding period, using the same buy-date cutoff as the price-chart
  // markers. Trades are grouped by side with explicit direction
  // colors (green = buy, red = sell), ordered by date, with fill price and
  // the sell's realized return versus the latest buy at the end of each row.
  const scopedMarks = anchorActive && holding
    ? visibleMarks.filter(mark => mark.date >= holding.purchaseDate)
    : visibleMarks;
  const periodMarks = withTradePnL(scopedMarks);
  const buyMarks = periodMarks.filter(mark => mark.side === 'BUY');
  const sellMarks = periodMarks.filter(mark => mark.side === 'SELL');
  const otherMarks = periodMarks.filter(mark => mark.side !== 'BUY' && mark.side !== 'SELL');
  const sideColor = (side: string) => side === 'BUY'
    ? TRADE_SIDE_COLORS.BUY
    : side === 'SELL' ? TRADE_SIDE_COLORS.SELL : undefined;
  const pnlColor = (pnl?: number | null) => pnl == null
    ? undefined
    : pnl >= 0 ? TRADE_SIDE_COLORS.BUY : TRADE_SIDE_COLORS.SELL;
  // Trade dots on the selected strategy's NAV line reuse the same executed
  // marks; dates outside the displayed rows are skipped automatically.
  const navDots = navTradeDots(rows, periodMarks, displayFamily);

  return <section className="mt-2 space-y-2 text-xs" aria-label={text('Selected strategy results', '当前策略结果')}>
    <div
      className="flex flex-col gap-2 p-2"
      data-testid="strategy-combined-chart"
    >
      <div className="order-3 flex flex-wrap items-center gap-3">
        <h3 className="font-semibold">{text('Adaptive budget / NAV', '自适应预算 / NAV')}</h3>
        <span className="text-secondary-text">{familyName}</span>
        {holding ? <button
          type="button"
          aria-pressed={anchorActive}
          data-testid="holding-anchor-toggle"
          title={text(
            `Holding ${holding.code} bought ${holding.purchaseDate} @ ${holding.purchasePrice}`,
            `持仓 ${holding.code} 买入 ${holding.purchaseDate} @ ${holding.purchasePrice}`,
          )}
          onClick={onToggleHolding}
          className={`inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-xs font-medium transition-colors ${
            anchorActive
              ? 'border-primary/50 bg-primary/10 text-primary'
              : 'border-border/70 bg-background/50 text-muted-text hover:bg-hover hover:text-secondary-text'
          }`}
        >
          <span className={`inline-block h-2 w-2 rounded-full ${anchorActive ? 'bg-primary' : 'bg-border'}`} />
          {anchorActive
            ? text(`Anchored @ ${holding.purchaseDate}`, `已锚定 ${holding.purchaseDate}`)
            : text(`From my holding ${holding.purchaseDate}`, `自持仓 ${holding.purchaseDate} 起`)}
        </button> : null}
        <span className="ml-auto text-secondary-text">{anchorActive && anchorDate
          ? text(`Since ${anchorDate} · ${rows.length} bars`, `自 ${anchorDate} 起 · ${rows.length} 根`)
          : text(`Last ${days} bars`, `最近 ${days} 根`)}</span>
      </div>
      {anchorActive && holding && anchorDate ? <p className="order-4 text-secondary-text">
        {text(
          `Holding ${holding.code} bought ${holding.purchaseDate} @ ${holding.purchasePrice} — all NAV lines restart from 1.0 there.`,
          `持仓 ${holding.code} 买入 ${holding.purchaseDate} @ ${holding.purchasePrice}——所有 NAV 线自 ${anchorDate} 按 1.0 起算。`,
        )}
      </p> : null}
      <div aria-label="NAV / S&P 500 / growth target" data-testid="strategy-nav-chart" className="order-1">
        {!combined.hasBenchmark && <p>{text('Adjusted SPY benchmark unavailable; no substitute is plotted.', '缺少复权 SPY 基准，不绘制替代基准。')}</p>}
        {rows.length && hasAnyStrategyLine ? <ResponsiveContainer width="100%" height={200}>
          {/* Stacked directly under the price chart: the date axis sits on top
              so both date rows meet in the middle, the plot area matches
              the price chart geometry ([12, width-60]) bar for bar, and the
              legend plus card info sit below the plot like one chart. */}
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 4, left: 12 }}>
            <CartesianGrid strokeDasharray="3 3" opacity={.2} />
            <XAxis dataKey="date" orientation="top" minTickGap={65} tick={{ fontSize: 10 }} hide={shareDateAxis} />
            <YAxis orientation="right" width={48} domain={['auto', 'auto']} tick={{ fontSize: 10 }} tickFormatter={value => Number(value).toFixed(2)} />
            <Tooltip formatter={value => typeof value === 'number' ? value.toFixed(4) : value} />
            <Legend verticalAlign="bottom" />
            {allFamilies.map(item => {
              const itemFamily = STRATEGY_FAMILIES.find(entry => entry.key === item)!;
              const itemName = zh ? itemFamily.zh : itemFamily.en;
              const hasLine = rows.some(row => row[`nav:${item}`] != null);
              if (!hasLine) return null;
              const isSelected = item === displayFamily;
              return <Line
                key={`nav:${item}`}
                dataKey={`nav:${item}`}
                name={`${itemName} NAV`}
                stroke={STRATEGY_FAMILY_COLORS[item]}
                strokeWidth={isSelected ? 2.5 : 1.5}
                strokeOpacity={isSelected ? 1 : 0.85}
                dot={false}
                connectNulls={false}
                isAnimationActive={false}
              />;
            })}
            <Line dataKey="benchmarkNav" name="S&P 500 (SPY adjusted)" stroke={BENCHMARK_LINE_COLOR} strokeDasharray="6 4" strokeWidth={1.5} strokeOpacity={0.9} dot={false} connectNulls={false} isAnimationActive={false} />
            <Line dataKey="requiredNav" name={`${Math.round(combined.target * 100)}% CAGR ${text('target', '目标')}`} stroke={TARGET_LINE_COLOR} strokeDasharray="2 3" strokeWidth={1.5} strokeOpacity={0.9} dot={false} connectNulls={false} isAnimationActive={false} />
            {navDots.map((dot, index) => (
              <ReferenceDot
                key={`trade-${dot.date}-${index}`}
                x={dot.date}
                y={dot.nav}
                r={4}
                fill={sideColor(dot.side) ?? '#fff'}
                stroke="#fff"
                strokeWidth={1}
              />
            ))}
          </LineChart>
        </ResponsiveContainer> : <p role="status">
          {anchorActive && holding && !anchorDate
            ? text(
              `Your holding starts ${holding.purchaseDate}, after the available test data.`,
              `持仓买入日 ${holding.purchaseDate} 晚于可用测试数据。`)
            : !rows.length || !hasAnyStrategyLine
              ? text('No shared NAV history is available for this range.', '该范围没有可用的共同 NAV 历史。')
              : view.unavailable
                ? text('This strategy has no saved result. Run Auto Tune again.', '该策略没有已保存结果，请重新运行 Auto Tune。')
                : text('No NAV curve is available for this range.', '该范围没有可用的 NAV 曲线。')}
        </p>}
      </div>
      <p className="order-2 text-secondary-text">
        {anchorActive && holding ? text(
          `${visibleFamilyCount} available strategies are shown together, restarted from ${anchorDate ?? holding.purchaseDate}. Trade markers are shown on the technical price chart.`,
          `${visibleFamilyCount} 条可用策略线同时展示，并自 ${anchorDate ?? holding.purchaseDate} 起算。交易标记显示在技术指标价格图中。`,
        ) : text(
          `${visibleFamilyCount} available strategies are shown together. Selected strategy: ${familyName}. Trade markers are shown on the technical price chart.`,
          `${visibleFamilyCount} 条可用策略线同时展示。当前策略：${familyName}。交易标记显示在技术指标价格图中。`,
        )}
        {!anchorActive && combined.anchorDate ? text(
          ` Common history: ${combined.anchorDate} to ${combined.endDate}; all NAV lines start at 1 on ${combined.anchorDate}.`,
          ` 共同历史：${combined.anchorDate} 至 ${combined.endDate}；所有 NAV 线于 ${combined.anchorDate} 按 1 起算。`,
        ) : null}
      </p>
      {missingFamilies.length && !(anchorActive && !anchorDate) ? <p className="order-5 text-secondary-text" role="status">
        {text(
          `No saved curve for: ${missingFamilies.map(({ family, view: itemView }) => {
            const itemName = STRATEGY_FAMILIES.find(entry => entry.key === family)!.en;
            return itemView.unavailable ? `${itemName} (${itemView.unavailable})` : itemName;
          }).join(', ')}. Rerun Auto Tune to refresh available strategies.`,
          `以下策略暂无已保存曲线：${missingFamilies.map(({ family, view: itemView }) => {
            const itemName = STRATEGY_FAMILIES.find(entry => entry.key === family)!.zh;
            return itemView.unavailable ? `${itemName}（${itemView.unavailable}）` : itemName;
          }).join('、')}。请重新运行 Auto Tune，刷新可用策略。`,
        )}
      </p> : null}
      <details className="order-6">
        <summary>
          {text('Executed trade details', '已成交交易明细')} ({periodMarks.length})
          {anchorActive && anchorDate ? text(` · holding since ${anchorDate}`, ` · 持仓自 ${anchorDate}`) : null}
        </summary>
        <div className="max-h-64 overflow-auto">
          {[
            { side: 'BUY' as const, marks: buyMarks },
            { side: 'SELL' as const, marks: sellMarks },
          ].map(group => group.marks.length ? (
            <div key={group.side} className="py-1">
              <p className="font-semibold" style={{ color: sideColor(group.side) }}>
                {group.side} ({group.marks.length})
              </p>
              <ul className="space-y-2 py-1">
                {group.marks.map((mark, index) => (
                  <li key={`${mark.date}-${index}`}>
                    {mark.date} · <span style={{ color: sideColor(mark.side) }}>{mark.side}</span> · @{price(mark.price)} · {formatTriggerText(mark)} · {mark.reason} · <span style={{ color: pnlColor(mark.pnlPct) }}>{signedPct(mark.pnlPct)}</span>
                  </li>
                ))}
              </ul>
            </div>
          ) : null)}
          {otherMarks.length ? (
            <ul className="space-y-2 py-2">
              {otherMarks.map((mark, index) => (
                <li key={`${mark.date}-${index}`}>
                  {mark.date} · {mark.side} · @{price(mark.price)} · {formatTriggerText(mark)} · {mark.reason} · <span style={{ color: pnlColor(mark.pnlPct) }}>{signedPct(mark.pnlPct)}</span>
                </li>
              ))}
            </ul>
          ) : null}
          {sellMarks.some(mark => mark.pnlPct != null) ? <p className="text-secondary-text">
            {text('Sell P/L is measured against the latest buy price, excluding fees.', '卖出盈亏相对最近一次买入价计算，不含费用。')}
          </p> : null}
        </div>
      </details>
    </div>
    {selectedFamily === 'macro_router' ? <MacroRouterPanel report={report.macroRouter} language={language} /> : null}
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
