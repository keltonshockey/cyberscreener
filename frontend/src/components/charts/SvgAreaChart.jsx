import { useState } from 'react';
import { ChartTooltip } from './ChartTooltip';

/**
 * Multi-line area chart with fill.
 */
export function SvgAreaChart({ data, lines, height = 260, xKey = 'date' }) {
  const [tip, setTip] = useState(null);
  if (!data || !data.length) return null;

  const n = data.length;
  const allV = lines.flatMap(l => data.map(d => d[l.key] || 0));
  const mn = Math.min(...allV);
  const mx = Math.max(...allV);
  const rng = mx - mn || 1;
  const px = i => (i / (n - 1)) * 100;
  const py = v => 100 - ((v - mn) / rng) * 90 - 5;

  return (
    <div style={{ position: 'relative', width: '100%', height }}>
      <ChartTooltip tip={tip} />
      <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ overflow: 'visible' }}>
        {[0, 25, 50, 75, 100].map(y => (
          <line key={y} x1={0} y1={y} x2={100} y2={y} stroke="var(--color-border-subtle)" strokeWidth={0.2} />
        ))}
        {lines.map(l => {
          const pts = data.map((d, i) => `${px(i)},${py(d[l.key] || 0)}`).join(' ');
          return (
            <g key={l.key}>
              <polygon points={`${pts} 100,100 0,100`} fill={l.color} opacity={0.08} />
              <polyline points={pts} fill="none" stroke={l.color} strokeWidth={0.8} />
            </g>
          );
        })}
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
                text: `${d[xKey] || ''}  ${lines.map(l => `${l.name}: ${d[l.key] || 0}`).join('  ')}`,
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
        {lines.map(l => (
          <span key={l.key} style={{ fontSize: 10, color: l.color, fontWeight: 600 }}>
            {'● ' + l.name}
          </span>
        ))}
      </div>
    </div>
  );
}
