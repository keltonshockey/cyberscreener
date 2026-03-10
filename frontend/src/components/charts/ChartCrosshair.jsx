/**
 * SVG crosshair overlay for charts.
 * Renders vertical + horizontal dashed lines at the cursor position.
 */
export function ChartCrosshair({ x, y, plotArea, visible }) {
  if (!visible || !plotArea) return null;
  const { left, right, top, bottom } = plotArea;

  return (
    <g className="chart-crosshair" pointerEvents="none">
      {/* Vertical line */}
      <line
        x1={x} y1={top} x2={x} y2={bottom}
        stroke="var(--color-text-tertiary)"
        strokeWidth={1}
        strokeDasharray="4 3"
        opacity={0.6}
      />
      {/* Horizontal line */}
      <line
        x1={left} y1={y} x2={right} y2={y}
        stroke="var(--color-text-tertiary)"
        strokeWidth={1}
        strokeDasharray="4 3"
        opacity={0.6}
      />
    </g>
  );
}
