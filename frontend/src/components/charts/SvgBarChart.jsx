import { useState } from 'react';
import { ChartTooltip } from './ChartTooltip';

/**
 * Vertical bar chart with hover tooltips.
 */
export function SvgBarChart({ data, dataKey, labelKey, height = 220, colorFn }) {
  const [tip, setTip] = useState(null);
  if (!data || !data.length) return null;

  const mx = Math.max(...data.map(d => Math.abs(d[dataKey] || 0)), 1);
  const w = 100 / data.length;
  const hasNeg = data.some(d => (d[dataKey] || 0) < 0);
  const baseY = hasNeg ? 50 : 100;

  return (
    <div style={{ position: 'relative', width: '100%', height }}>
      <ChartTooltip tip={tip} />
      <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ overflow: 'visible' }}>
        {[0, 25, 50, 75, 100].map(y => (
          <line key={y} x1={0} y1={y} x2={100} y2={y} stroke="var(--color-border-subtle)" strokeWidth={0.3} />
        ))}
        {data.map((d, i) => {
          const v = d[dataKey] || 0;
          const pct = Math.abs(v) / mx;
          const c = colorFn ? colorFn(d, v) : v >= 0 ? 'var(--color-success)' : 'var(--color-danger)';
          const bh = pct * (hasNeg ? 48 : 95);
          const by = v >= 0 ? baseY - bh : baseY;

          return (
            <rect
              key={i}
              x={i * w + w * 0.1}
              y={by}
              width={w * 0.8}
              height={Math.max(bh, 0.5)}
              fill={c}
              opacity={0.75}
              rx={0.8}
              onMouseEnter={e => {
                const r = e.target.getBoundingClientRect();
                const pr = e.target.closest('div').getBoundingClientRect();
                setTip({
                  x: r.left - pr.left,
                  y: r.top - pr.top,
                  text: `${d[labelKey] || ''}: ${typeof v === 'number' ? v.toFixed(1) : v}`,
                });
              }}
              onMouseLeave={() => setTip(null)}
            />
          );
        })}
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-around', marginTop: 4 }}>
        {data.map((d, i) => (
          <div
            key={i}
            style={{
              fontSize: 8,
              color: 'var(--color-text-secondary)',
              textAlign: 'center',
              flex: 1,
              overflow: 'hidden',
              whiteSpace: 'nowrap',
              transform: 'rotate(-35deg)',
              transformOrigin: 'top center',
              fontFamily: 'var(--font-mono)',
            }}
          >
            {d[labelKey] || ''}
          </div>
        ))}
      </div>
    </div>
  );
}
