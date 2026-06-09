/**
 * QUAEST.TECH — Sparkline.
 * Renders a tiny polyline from a numeric series. Color follows polarity.
 * On the Forum grid we feed it [sma_200, sma_50, sma_20, price] — a genuine
 * long → short moving-average → current-price slope (the "50-day trend").
 */
export function Sparkline({ points, color = 'var(--ink-mut)', width = 74, height = 20, strokeWidth = 1.5 }) {
  const vals = (points || []).filter(v => typeof v === 'number' && isFinite(v));
  if (vals.length < 2) return <svg width={width} height={height} aria-hidden="true" />;

  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const pad = 2;
  const stepX = (width - pad * 2) / (vals.length - 1);

  const coords = vals.map((v, i) => {
    const x = pad + i * stepX;
    const y = pad + (1 - (v - min) / span) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} fill="none"
      stroke={color} strokeWidth={strokeWidth} strokeLinejoin="round" strokeLinecap="round"
      style={{ verticalAlign: 'middle' }} aria-hidden="true">
      <polyline points={coords} />
    </svg>
  );
}
