/**
 * QUAEST.TECH — Interactive Score History Chart
 * Replaces SvgAreaChart with TradingView lightweight-charts for score timelines.
 * Features: zoom, pan, crosshair, multi-line with fills.
 */

import { useEffect, useRef } from 'react';
import { createChart, ColorType, LineStyle, CrosshairMode } from 'lightweight-charts';

function parseDate(dateStr) {
  if (!dateStr) return null;
  // Handle various date formats
  const d = dateStr.includes('T') ? dateStr.split('T')[0] : dateStr;
  const parts = d.split('-');
  if (parts.length === 3) return d;
  // Try MM/DD format
  return dateStr;
}

export function InteractiveScoreChart({ data, lines, height = 280, xKey = 'date' }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);

  useEffect(() => {
    if (!data?.length || !lines?.length || !containerRef.current) return;

    const container = containerRef.current;

    // Clean up
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
    }

    const cs = getComputedStyle(document.documentElement);
    const textColor = cs.getPropertyValue('--color-text-secondary').trim() || '#8888aa';
    const borderColor = cs.getPropertyValue('--color-border-subtle').trim() || '#2a2a3e';
    const purpleColor = cs.getPropertyValue('--imperial-purple').trim() || '#7c5cfc';

    const chart = createChart(container, {
      width: container.clientWidth,
      height: height,
      layout: {
        background: { type: ColorType.Solid, color: 'transparent' },
        textColor: textColor,
        fontFamily: "'JetBrains Mono', 'SF Mono', monospace",
        fontSize: 11,
      },
      grid: {
        vertLines: { color: borderColor, style: LineStyle.Dotted },
        horzLines: { color: borderColor, style: LineStyle.Dotted },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: purpleColor, width: 1, style: LineStyle.Dashed, labelBackgroundColor: purpleColor },
        horzLine: { color: purpleColor, width: 1, style: LineStyle.Dashed, labelBackgroundColor: purpleColor },
      },
      rightPriceScale: {
        borderColor: borderColor,
        scaleMargins: { top: 0.05, bottom: 0.05 },
      },
      timeScale: {
        borderColor: borderColor,
        timeVisible: false,
        rightOffset: 3,
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      handleScale: { mouseWheel: true, pinch: true },
    });

    chartRef.current = chart;

    // Add each line series
    lines.forEach((line, idx) => {
      // Resolve CSS variable colors to actual hex
      let color = line.color;
      if (color.startsWith('var(')) {
        const varName = color.match(/var\((.*?)\)/)?.[1];
        if (varName) {
          color = cs.getPropertyValue(varName).trim() || '#7c5cfc';
        }
      }

      const lineData = data
        .filter(d => d[xKey] && d[line.key] != null)
        .map(d => ({
          time: parseDate(d[xKey]),
          value: d[line.key] || 0,
        }));

      if (lineData.length === 0) return;

      // Area series with fill
      const series = chart.addAreaSeries({
        lineColor: color,
        topColor: color + '30',
        bottomColor: color + '05',
        lineWidth: 2,
        crosshairMarkerVisible: true,
        crosshairMarkerRadius: 3,
        crosshairMarkerBorderColor: color,
        crosshairMarkerBackgroundColor: '#fff',
        priceLineVisible: false,
        lastValueVisible: idx === 0, // Only show last value for first line
      });

      series.setData(lineData);
    });

    chart.timeScale().fitContent();

    // Resize observer
    const resizeObserver = new ResizeObserver(entries => {
      for (const entry of entries) {
        chart.applyOptions({ width: entry.contentRect.width });
      }
    });
    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      if (chartRef.current) {
        chartRef.current.remove();
        chartRef.current = null;
      }
    };
  }, [data, lines, height, xKey]);

  if (!data?.length) return null;

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <div ref={containerRef} style={{ width: '100%', borderRadius: 8, overflow: 'hidden' }} />
      <div style={{ display: 'flex', gap: 12, marginTop: 6, alignItems: 'center' }}>
        {lines.map(l => {
          let color = l.color;
          if (color.startsWith('var(')) {
            const cs = getComputedStyle(document.documentElement);
            const varName = color.match(/var\((.*?)\)/)?.[1];
            if (varName) color = cs.getPropertyValue(varName).trim() || color;
          }
          return (
            <span key={l.key} style={{ fontSize: 10, color: color, fontWeight: 600 }}>
              {'● ' + l.name}
            </span>
          );
        })}
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 9, color: 'var(--color-text-tertiary)' }}>Scroll to zoom · Drag to pan</span>
      </div>
    </div>
  );
}
