/**
 * QUAEST.TECH — Interactive Price Chart
 * Replaces SvgPriceChart with TradingView lightweight-charts.
 * Features: zoom, pan, crosshair, SMA overlays, RSI pane, signal markers.
 */

import { useEffect, useRef, useState, useCallback } from 'react';
import { createChart, ColorType, LineStyle, CrosshairMode } from 'lightweight-charts';
import { fetchChart } from '../../api/endpoints';

const RANGE_OPTIONS = [
  { label: '1M', days: 30 },
  { label: '3M', days: 90 },
  { label: '6M', days: 180 },
  { label: '1Y', days: 365 },
];

const SIGNAL_MARKERS = {
  earnings: { shape: 'circle', color: '#ff9f0a', text: 'E' },
  insider_buy: { shape: 'arrowUp', color: '#30d158', text: 'B' },
  insider_sell: { shape: 'arrowDown', color: '#ff453a', text: 'S' },
  rsi_oversold: { shape: 'circle', color: '#30d158', text: '' },
  rsi_overbought: { shape: 'circle', color: '#ff453a', text: '' },
  sma_cross_bull: { shape: 'arrowUp', color: '#30d158', text: '' },
  sma_cross_bear: { shape: 'arrowDown', color: '#ff453a', text: '' },
};

function parseDate(dateStr) {
  // Convert 'YYYY-MM-DD' to { year, month, day } for lightweight-charts
  const [y, m, d] = dateStr.split('-').map(Number);
  return `${y}-${String(m).padStart(2, '0')}-${String(d).padStart(2, '0')}`;
}

export function InteractivePriceChart({ ticker, days = 90, height = 420 }) {
  const containerRef = useRef(null);
  const chartRef = useRef(null);
  const seriesRef = useRef({});
  const [selDays, setSelDays] = useState(days);
  const [data, setData] = useState(null);
  const [showSMA, setShowSMA] = useState({ s20: true, s50: true, s200: false });
  const [chartMode, setChartMode] = useState('line'); // 'line' or 'candle'

  // Fetch data
  useEffect(() => {
    if (!ticker) return;
    setData(null);
    fetchChart(ticker, selDays).then(d => setData(d));
  }, [ticker, selDays]);

  // Build/update chart
  useEffect(() => {
    if (!data?.prices?.length || !containerRef.current) return;

    const prices = data.prices;
    const container = containerRef.current;

    // Clean up existing chart
    if (chartRef.current) {
      chartRef.current.remove();
      chartRef.current = null;
      seriesRef.current = {};
    }

    // Get CSS variables from the document
    const cs = getComputedStyle(document.documentElement);
    const bgColor = cs.getPropertyValue('--color-bg-card').trim() || '#1c1c2e';
    const textColor = cs.getPropertyValue('--color-text-secondary').trim() || '#8888aa';
    const borderColor = cs.getPropertyValue('--color-border-subtle').trim() || '#2a2a3e';
    const purpleColor = cs.getPropertyValue('--imperial-purple').trim() || '#7c5cfc';

    const chart = createChart(container, {
      width: container.clientWidth,
      height: height - 50, // Leave room for controls
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
        scaleMargins: { top: 0.05, bottom: 0.25 }, // Leave room for RSI
      },
      timeScale: {
        borderColor: borderColor,
        timeVisible: false,
        rightOffset: 5,
        barSpacing: Math.max(4, Math.min(12, container.clientWidth / prices.length)),
      },
      handleScroll: { mouseWheel: true, pressedMouseMove: true },
      handleScale: { mouseWheel: true, pinch: true },
    });

    chartRef.current = chart;

    // ── Main price series ──
    const priceData = prices.map(p => ({
      time: parseDate(p.date),
      value: p.close || 0,
    }));

    const priceSeries = chart.addLineSeries({
      color: purpleColor,
      lineWidth: 2,
      crosshairMarkerVisible: true,
      crosshairMarkerRadius: 4,
      crosshairMarkerBorderColor: purpleColor,
      crosshairMarkerBackgroundColor: '#fff',
      priceLineVisible: true,
      lastValueVisible: true,
    });
    priceSeries.setData(priceData);
    seriesRef.current.price = priceSeries;

    // ── SMA overlays ──
    const smaConfigs = [
      { key: 's20', field: 'sma20', color: '#30d158', label: 'SMA 20', visible: showSMA.s20 },
      { key: 's50', field: 'sma50', color: '#ff9f0a', label: 'SMA 50', visible: showSMA.s50 },
      { key: 's200', field: 'sma200', color: '#af52de', label: 'SMA 200', visible: showSMA.s200 },
    ];

    smaConfigs.forEach(({ key, field, color, visible }) => {
      const smaData = prices
        .filter(p => p[field] != null)
        .map(p => ({ time: parseDate(p.date), value: p[field] }));

      if (smaData.length > 0) {
        const series = chart.addLineSeries({
          color: color,
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          crosshairMarkerVisible: false,
          priceLineVisible: false,
          lastValueVisible: false,
          visible: visible,
        });
        series.setData(smaData);
        seriesRef.current[key] = series;
      }
    });

    // ── RSI as histogram at bottom ──
    const rsiData = prices
      .filter(p => p.rsi != null)
      .map(p => ({
        time: parseDate(p.date),
        value: p.rsi,
        color: p.rsi < 30 ? '#30d15880' : p.rsi > 70 ? '#ff453a80' : '#ff9f0a40',
      }));

    if (rsiData.length > 0) {
      const rsiSeries = chart.addHistogramSeries({
        priceFormat: { type: 'price', precision: 0, minMove: 1 },
        priceScaleId: 'rsi',
        scaleMargins: { top: 0.8, bottom: 0 },
      });
      rsiSeries.setData(rsiData);
      seriesRef.current.rsi = rsiSeries;

      chart.priceScale('rsi').applyOptions({
        scaleMargins: { top: 0.8, bottom: 0 },
        drawTicks: false,
        borderVisible: false,
      });
    }

    // ── Signal markers ──
    const signals = data.signals || [];
    const markers = signals
      .map(s => {
        const cfg = SIGNAL_MARKERS[s.type];
        if (!cfg) return null;
        // Find closest price date
        const matchDate = prices.find(p => p.date === s.date)?.date
          || prices.reduce((best, p) => {
            const diff = Math.abs(new Date(p.date) - new Date(s.date));
            return diff < best.diff ? { date: p.date, diff } : best;
          }, { date: prices[0]?.date, diff: Infinity }).date;

        if (!matchDate) return null;

        return {
          time: parseDate(matchDate),
          position: cfg.shape === 'arrowDown' ? 'aboveBar' : 'belowBar',
          color: cfg.color,
          shape: cfg.shape,
          text: cfg.text,
          size: 1,
        };
      })
      .filter(Boolean)
      .sort((a, b) => a.time.localeCompare(b.time));

    if (markers.length > 0) {
      priceSeries.setMarkers(markers);
    }

    // ── Fit content ──
    chart.timeScale().fitContent();

    // ── Resize observer ──
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
        seriesRef.current = {};
      }
    };
  }, [data, height]); // Intentionally exclude showSMA to avoid full rebuild

  // Toggle SMA visibility without rebuilding chart
  useEffect(() => {
    Object.entries(showSMA).forEach(([key, visible]) => {
      if (seriesRef.current[key]) {
        seriesRef.current[key].applyOptions({ visible });
      }
    });
  }, [showSMA]);

  if (!data) {
    return (
      <div style={{ height, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-secondary)', fontSize: 12, background: 'var(--color-bg)', borderRadius: 12 }}>
        Loading chart...
      </div>
    );
  }

  if (!data.prices?.length) {
    return (
      <div style={{ height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-secondary)', fontSize: 12, background: 'var(--color-bg)', borderRadius: 12 }}>
        No price data
      </div>
    );
  }

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      {/* Controls bar */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 8, alignItems: 'center', flexWrap: 'wrap' }}>
        {/* Time range selector */}
        {RANGE_OPTIONS.map(r => (
          <button
            key={r.days}
            onClick={() => setSelDays(r.days)}
            style={{
              padding: '4px 10px', borderRadius: 6, fontSize: 10, fontWeight: 600,
              cursor: 'pointer', fontFamily: 'var(--font-mono)',
              background: selDays === r.days ? 'var(--imperial-purple-glow)' : 'var(--color-bg-card)',
              border: `1px solid ${selDays === r.days ? 'var(--imperial-purple)' : 'var(--color-border-subtle)'}`,
              color: selDays === r.days ? 'var(--imperial-purple)' : 'var(--color-text-secondary)',
            }}
          >
            {r.label}
          </button>
        ))}

        <span style={{ flex: 1 }} />

        {/* SMA toggles */}
        {[
          { key: 's20', label: 'SMA20', color: '#30d158' },
          { key: 's50', label: 'SMA50', color: '#ff9f0a' },
          { key: 's200', label: 'SMA200', color: '#af52de' },
        ].map(s => (
          <button
            key={s.key}
            onClick={() => setShowSMA(prev => ({ ...prev, [s.key]: !prev[s.key] }))}
            style={{
              padding: '3px 8px', borderRadius: 4, fontSize: 9, fontWeight: 600,
              cursor: 'pointer', border: 'none',
              background: showSMA[s.key] ? s.color + '20' : 'transparent',
              color: showSMA[s.key] ? s.color : 'var(--color-text-tertiary)',
              opacity: showSMA[s.key] ? 1 : 0.5,
            }}
          >
            {s.label}
          </button>
        ))}
      </div>

      {/* Chart container */}
      <div ref={containerRef} style={{ width: '100%', borderRadius: 8, overflow: 'hidden' }} />

      {/* Legend */}
      <div style={{ display: 'flex', gap: 10, marginTop: 6, flexWrap: 'wrap', alignItems: 'center', fontSize: 9 }}>
        <span style={{ color: 'var(--imperial-purple)', fontWeight: 600 }}>● Price</span>
        <span style={{ color: '#ff9f0a', fontWeight: 600 }}>▮ RSI</span>
        <span style={{ flex: 1 }} />
        <span style={{ color: '#ff9f0a', fontFamily: 'var(--font-mono)' }}>E Earnings</span>
        <span style={{ color: '#30d158', fontFamily: 'var(--font-mono)' }}>B Buy</span>
        <span style={{ color: '#ff453a', fontFamily: 'var(--font-mono)' }}>S Sell</span>
        <span style={{ color: 'var(--color-text-tertiary)' }}>Scroll to zoom · Drag to pan</span>
      </div>
    </div>
  );
}
