import { CartesianGrid, Legend, Line, LineChart, ReferenceDot, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import type { AllocationReport } from '../../api/stocks';

export function AutoTuneEconomicChart({ policy, language }: {
  policy: AllocationReport['policies'][number]; language: string;
}) {
  const zh = language === 'zh';
  const curve = policy.economicCurve;
  if (!curve?.length) return null;
  const annotations = policy.transitions.map(t => ({
    date: t.triggerDate, nav: t.portfolioBefore.nav,
    label: `${t.triggerDirection} ${t.requestedTargetExposure == null ? 'HOLD' : `${Math.round(t.requestedTargetExposure * 100)}%`}`,
    color: t.triggerDirection === 'SELL' ? '#f97316' : '#22c55e',
  })).concat(curve.flatMap((p, i) => p.cagrDeficit > 0 && (i === 0 || curve[i - 1].cagrDeficit === 0)
    ? [{ date: p.date, nav: p.strategyNav, label: zh ? '增长缺口开始' : 'CAGR deficit starts', color: '#ef4444' }] : []));
  return <div className="my-3" aria-label={zh ? '权益、标普与增长目标曲线' : 'NAV, S&P and growth target curves'}>
    <h4 className="font-medium">{zh ? '权益 / 标普500 / 增长目标' : 'NAV / S&P 500 / growth target'}</h4>
    <ResponsiveContainer width="100%" height={280}>
      <LineChart data={curve} margin={{ top: 22, right: 25, bottom: 10, left: 10 }}>
        <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
        <XAxis dataKey="date" minTickGap={65} tick={{ fontSize: 10 }} />
        <YAxis domain={['auto', 'auto']} tick={{ fontSize: 10 }} tickFormatter={v => Number(v).toFixed(2)} />
        <Tooltip formatter={v => typeof v === 'number' ? v.toFixed(4) : v} />
        <Legend />
        <Line type="linear" dataKey="strategyNav" name={zh ? '实际 NAV' : 'Actual NAV'} stroke="#38bdf8" dot={false} isAnimationActive={false} />
        <Line type="linear" dataKey="benchmarkNav" name="S&P 500 (SPY adjusted)" stroke="#a78bfa" dot={false} connectNulls={false} isAnimationActive={false} />
        {curve.some(p => p.buyHoldNav != null) && <Line type="linear" dataKey="buyHoldNav" name={zh ? '个股买入持有' : 'Stock Buy & Hold'} stroke="#fb923c" dot={false} isAnimationActive={false} />}
        {curve.some(p => p.cashNav != null) && <Line type="linear" dataKey="cashNav" name={zh ? '现金基准' : 'Cash benchmark'} stroke="#94a3b8" dot={false} isAnimationActive={false} />}
        <Line type="linear" dataKey="requiredNav" name={`${Math.round((policy.metrics.test.targetCagr ?? .3) * 100)}% CAGR ${zh ? '目标' : 'target'}`} stroke="#fbbf24" dot={false} strokeDasharray="5 4" isAnimationActive={false} />
        {annotations.map((a, i) => <ReferenceDot key={i} x={a.date} y={a.nav} r={3} fill={a.color} stroke={a.color} />)}
      </LineChart>
    </ResponsiveContainer>
    <details><summary>{zh ? '交易、缺口及机会事件' : 'Trades, deficits and opportunity events'}</summary>
      <ul>{annotations.map((a, i) => <li key={i}>{a.date} · {a.label}</li>)}</ul>
      <ul>{policy.transitions.filter(t => (t.relativeAlpha ?? 0) < 0 || (t.opportunityRegret ?? 0) > 0).map((t, i) =>
        <li key={i}>{t.nextTriggerDate} · {t.benchmarkRewardReason} · {t.opportunityReason}</li>)}</ul>
    </details>
  </div>;
}
