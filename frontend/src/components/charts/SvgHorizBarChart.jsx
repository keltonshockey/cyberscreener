import { useState } from 'react';
import { ChartTooltip } from './ChartTooltip';

/**
 * Horizontal bar chart with labels and values.
 */
export function SvgHorizBarChart({ data, dataKey, labelKey, height = 180 }) {
  const [tip, setTip] = useState(null);
  if (!data || !data.length) return null;

  const mx = Math.max(...data.map(d => Math.abs(d[dataKey] || 0)), 1);
  const h = 100 / data.length;

  return (
    <div style={{ position: 'relative', width: '100%', height }}>
      <ChartTooltip tip={tip} />
      <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ overflow: 'visible' }}>
        {data.map((d, i) => {
          const v = d[dataKey] || 0;
          const w = (Math.abs(v) / mx) * 60;
          const c = v >= 0 ? 'var(--color-success)' : 'var(--color-danger)';
          const by = i * h + h * 0.15;
          const bh = h * 0.7;

          return (
            <g key={i}>
              <text x={2} y={by + bh / 2 + 1} fill="var(--color-text-secondary)" fontSize={3.5} dominantBaseline="middle">
                {d[labelKey] || ''}
              </text>
              <rect
                x={35}
                y={by}
                width={Math.max(w, 0.5)}
                height={bh}
                fill={c}
                opacity={0.7}
                rx={0.5}
                onMouseEnter={e => {
                  const r = e.target.getBoundingClientRect();
                  const pr = e.target.closest('div').getBoundingClientRect();
                  setTip({
                    x: r.left - pr.left + r.width,
                    y: r.top - pr.top,
                    text: `${d[labelKey] || ''}: ${v > 0 ? '+' : ''}${v.toFixed(1)}%`,
                  });
                }}
                onMouseLeave={() => setTip(null)}
              />
              <text
                x={36 + Math.max(w, 1)}
                y={by + bh / 2 + 1}
                fill={c}
                fontSize={3}
                dominantBaseline="middle"
                fontFamily="var(--font-mono)"
              >
                {(v > 0 ? '+' : '') + v.toFixed(1) + '%'}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}
