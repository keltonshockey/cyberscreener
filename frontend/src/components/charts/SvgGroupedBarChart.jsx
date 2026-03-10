import { useState } from 'react';
import { ChartTooltip } from './ChartTooltip';

/**
 * Grouped vertical bars (multi-series).
 */
export function SvgGroupedBarChart({ data, bars, labelKey, height = 220 }) {
  const [tip, setTip] = useState(null);
  if (!data || !data.length) return null;

  const mx = Math.max(...bars.flatMap(b => data.map(d => Math.abs(d[b.key] || 0))), 1);
  const gw = 100 / data.length;
  const bw = (gw * 0.7) / bars.length;

  return (
    <div style={{ position: 'relative', width: '100%', height }}>
      <ChartTooltip tip={tip} />
      <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ overflow: 'visible' }}>
        {[0, 25, 50, 75, 100].map(y => (
          <line key={y} x1={0} y1={y} x2={100} y2={y} stroke="var(--color-border-subtle)" strokeWidth={0.2} />
        ))}
        {data.flatMap((d, i) =>
          bars.map((b, j) => {
            const v = d[b.key] || 0;
            const bh = (Math.abs(v) / mx) * 90;
            return (
              <rect
                key={`${i}-${j}`}
                x={i * gw + gw * 0.15 + j * bw}
                y={100 - bh}
                width={bw * 0.9}
                height={Math.max(bh, 0.5)}
                fill={b.color}
                opacity={0.7}
                rx={0.5}
                onMouseEnter={e => {
                  const r = e.target.getBoundingClientRect();
                  const pr = e.target.closest('div').getBoundingClientRect();
                  setTip({
                    x: r.left - pr.left,
                    y: r.top - pr.top,
                    text: `${d[labelKey] || ''} ${b.name}: ${v.toFixed(1)}%`,
                  });
                }}
                onMouseLeave={() => setTip(null)}
              />
            );
          })
        )}
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-around', marginTop: 4 }}>
        {data.map((d, i) => (
          <div key={i} style={{ fontSize: 8, color: 'var(--color-text-secondary)', textAlign: 'center', flex: 1, fontFamily: 'var(--font-mono)' }}>
            {d[labelKey] || ''}
          </div>
        ))}
      </div>
      <div style={{ display: 'flex', gap: 12, marginTop: 4 }}>
        {bars.map(b => (
          <span key={b.key} style={{ fontSize: 10, color: b.color, fontWeight: 600 }}>
            {'● ' + b.name}
          </span>
        ))}
      </div>
    </div>
  );
}
