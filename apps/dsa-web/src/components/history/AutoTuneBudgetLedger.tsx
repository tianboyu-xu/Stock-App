import type { AutoTuneDecision } from '../../api/stocks';

const reasons: Record<string, [string, string]> = {
  signal: ['信号', 'Signal'],
  no_cash: ['预算已用完', 'No cash available'],
  no_position: ['没有持仓可卖', 'No position to sell'],
  position_open: ['已有持仓（不加仓）', 'Position open (no pyramiding)'],
  trade_cooldown: ['交易冷却期', 'Trade cooldown'],
  entry_cooldown: ['买入间隔限制', 'Entry cooldown'],
  entry_filter: ['未通过入场过滤', 'Entry filter'],
  no_next_bar: ['窗口内无下一交易日', 'No next bar in window'],
  stop: ['止损', 'Stop loss'],
  trail: ['移动止盈', 'Trailing stop'],
  segment_end: ['窗口结束平仓', 'Window-end liquidation'],
};

export function AutoTuneBudgetLedger({ decisions, language }: {
  decisions?: AutoTuneDecision[];
  language: string;
}) {
  if (!decisions) return null;
  const zh = language === 'zh';
  const labels = zh
    ? ['信号日期 → 执行日期', '方向', '建议预算 %', '成交预算 %', '剩余现金 %', '结果']
    : ['Signal → execution date', 'Side', 'Suggested budget %', 'Executed budget %', 'Cash remaining %', 'Result'];
  return (
    <details className="mt-3 text-xs">
      <summary className="cursor-pointer font-medium">
        {zh ? '测试期预算与触发明细' : 'Test-window budget and trigger ledger'} ({decisions.length})
      </summary>
      <p className="my-2 text-secondary-text">
        {zh
          ? '起始现金为 100%；表中百分比均相对初始预算。按买入评分占满分比例分配当前权益的 25–100%，卖出全部持仓。不加仓、不借款、不做空。普通交易至少间隔 5 个交易日，买入还需满足所选间隔；止损与期末平仓除外。建议按信号收盘估算，成交包含费用并以次日开盘为准。'
          : 'Start with 100% cash; percentages below are relative to the initial budget. Buy allocation is 25–100% of current equity based on score / maximum score; sells close the whole position. One position, no borrowing or shorting. Ordinary trades are at least 5 trading days apart, with the selected entry interval also enforced; protective and window-end exits are exempt. Suggestions use the signal close; executions include costs at the next open.'}
      </p>
      <div className="max-h-72 overflow-auto">
        <table className="w-full text-left">
          <thead><tr>{labels.map(label => <th className="p-2" key={label}>{label}</th>)}</tr></thead>
          <tbody>{decisions.map((decision, index) => (
            <tr key={index} className="border-t border-border/30">
              <td className="p-2 whitespace-nowrap">{decision.signalDate}{decision.status === 'executed' ? ` → ${decision.date}` : ''}</td>
              <td className="p-2">{decision.side === 'buy' ? (zh ? '买入' : 'Buy') : (zh ? '卖出' : 'Sell')}</td>
              <td className="p-2 tabular-nums">{decision.suggestedBudgetPct.toFixed(2)}%</td>
              <td className="p-2 tabular-nums">{decision.executedBudgetPct.toFixed(2)}%</td>
              <td className="p-2 tabular-nums">{decision.cashAfterPct.toFixed(2)}%</td>
              <td className="p-2">{decision.status === 'executed' ? (zh ? '已成交' : 'Executed') : (zh ? '跳过' : 'Skipped')}
                {' · '}{reasons[decision.reason]?.[zh ? 0 : 1] ?? decision.reason}</td>
            </tr>
          ))}</tbody>
        </table>
      </div>
    </details>
  );
}
