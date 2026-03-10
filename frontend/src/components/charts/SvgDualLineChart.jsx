import { useState } from 'react';
import { ChartTooltip } from './ChartTooltip';

/**
 * Dual-line chart (solid + dashed) with independent Y-axes.
 */
export function SvgDualLineChart({ data, line1, line2, height = 200, xKey = 'date' }) {
  const [tip, setTip] = useState(null);
  if (!data || !data.length) return null;

  const n = data.length;
  const v1 = data.map(d => d[line1.key] || 0);
  const v2 = data.map(d => d[line2.key] || 0);
  const mn1 = Math.min(...v1), mx1 = Math.max(...v1), r1 = mx1 - mn1 || 1;
  const mn2 = Math.min(...v2), mx2 = Math.max(...v2), r2 = mx2 - mn2 || 1;
  const px = i => (i / (n - 1)) * 100;
  const py1 = v => 95 - ((v - mn1) / r1) * 85;
  const py2 = v => 95 - ((v - mn2) / r2) * 85;
  const pts1 = data.map((d, i) => `${px(i)},${py1(d[line1.key] || 0)}`).join(' ');
  const pts2 = data.map((d, i) => `${px(i)},${py2(d[line2.key] || 0)}`).join(' ');

  return (
    <div style={{ position: 'relative', width: '100%', height }}>
      <ChartTooltip tip={tip} />
      <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ overflow: 'visible' }}>
        {[0, 25, 50, 75, 100].map(y => (
          <line key={y} x1={0} y1={y} x2={100} y2={y} stroke="var(--color-border-subtle)" strokeWidth={0.2} />
        ))}
        <polyline points={pts1} fill="none" stroke={line1.color} strokeWidth={0.8} />
        <polyline points={pts2} fill="none" stroke={line2.color} strokeWidth={0.6} strokeDasharray="2,1.5" />
        {data.map((d, i) => (
          <rect
            key={i}
            x={px(i) - 0.8}
            y={0}
            width={1.6}
            height={100}
            fill="transparent"
            onMouseEnter={e => {
              const r = e.target.getBoundingClientRect();
              const pr = e.target.closest('div').getBoundingClientRect();
              setTip({
                x: r.left - pr.left,
                y: r.top - pr.top,
                text: `${d[xKey] || ''}  ${line1.name}: ${d[line1.key] || 0}  ${line2.name}: ${d[line2.key] || 0}`,
              });
            }}
            onMouseLeave={() => setTip(null)}
          />
        ))}
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 2 }}>
        {[data[0], data[Math.floor(n / 2)], data[n - 1]].filter(Boolean).map((d, i) => (
          <span key={i} style={{ fontSize: 9, color: 'var(--color-text-secondary)' }}>{d[xKey] || ''}</span>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 12, marginTop: 4 }}>
        <span style={{ fontSize: 10, color: line1.color, fontWeight: 600 }}>{'● ' + line1.name}</span>
        <span style={{ fontSize: 10, color: line2.color, fontWeight: 600 }}>{'┄ ' + line2.name}</span>
      </div>
    </div>
  );
}
