import { useState, useCallback } from 'react';
import { useChartDimensions } from '../../hooks/useChartDimensions';
import { ChartTooltip } from './ChartTooltip';
import { ChartCrosshair } from './ChartCrosshair';
import s from './ChartContainer.module.css';

/**
 * Universal chart wrapper that provides:
 *  - Pixel-accurate dimensions via ResizeObserver
 *  - Crosshair state management
 *  - Tooltip state management
 *  - Standard plot area margins
 *
 * Usage:
 *   <ChartContainer height={320} marginLeft={50}>
 *     {({ width, height, plotArea, crosshair }) => (
 *       <g> ... your SVG content ... </g>
 *     )}
 *   </ChartContainer>
 */
export function ChartContainer({
  height = 300,
  marginTop = 10,
  marginRight = 20,
  marginBottom = 35,
  marginLeft = 50,
  children,
  className,
}) {
  const { ref, width } = useChartDimensions(height);
  const [crosshair, setCrosshair] = useState({ x: 0, y: 0, visible: false });
  const [tip, setTip] = useState(null);

  const plotArea = {
    left: marginLeft,
    right: Math.max(width - marginRight, marginLeft + 1),
    top: marginTop,
    bottom: Math.max(height - marginBottom, marginTop + 1),
    get width() { return this.right - this.left; },
    get height() { return this.bottom - this.top; },
  };

  const handleMouseMove = useCallback((e) => {
    const svg = e.currentTarget;
    const rect = svg.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    setCrosshair({ x, y, visible: true });
  }, []);

  const handleMouseLeave = useCallback(() => {
    setCrosshair({ x: 0, y: 0, visible: false });
    setTip(null);
  }, []);

  if (!width) {
    return <div ref={ref} className={`${s.container} ${className || ''}`} style={{ height }} />;
  }

  return (
    <div ref={ref} className={`${s.container} ${className || ''}`} style={{ height }}>
      <ChartTooltip tip={tip} containerWidth={width} />
      <svg
        width="100%"
        height={height}
        viewBox={`0 0 ${width} ${height}`}
        className={s.svg}
        onMouseMove={handleMouseMove}
        onMouseLeave={handleMouseLeave}
      >
        {children({ width, height, plotArea, crosshair, setCrosshair, setTip })}
        <ChartCrosshair
          x={crosshair.x}
          y={crosshair.y}
          plotArea={plotArea}
          visible={crosshair.visible}
        />
      </svg>
    </div>
  );
}
