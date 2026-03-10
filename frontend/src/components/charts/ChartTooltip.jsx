/**
 * Shared tooltip component for SVG charts.
 */
export function ChartTooltip({ tip }) {
  if (!tip) return null;
  return (
    <div
      className="svgtip"
      style={{ left: tip.x, top: Math.max(0, tip.y - 36) }}
    >
      {tip.text}
    </div>
  );
}
