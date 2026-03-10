import { useState, useEffect } from 'react';
import { ChartTooltip } from './ChartTooltip';
import { fetchChart } from '../../api/endpoints';

/**
 * Price + SMA + RSI chart with signal markers.
 */
export function SvgPriceChart({ ticker, days = 90 }) {
  const [data, setData] = useState(null);
  const [tip, setTip] = useState(null);
  const [showSMA, setShowSMA] = useState({ s20: true, s50: true, s200: false });
  const [selDays, setSelDays] = useState(days);

  useEffect(() => {
    if (!ticker) return;
    setData(null);
    fetchChart(ticker, selDays).then(d => setData(d));
  }, [ticker, selDays]);

  if (!data) {
    return (
      <div style={{ height: 340, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-secondary)', fontSize: 12, background: 'var(--color-bg)', borderRadius: 12 }}>
        Loading chart...
      </div>
    );
  }

  const prices = data.prices || [];
  if (!prices.length) {
    return (
      <div style={{ height: 80, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--color-text-secondary)', fontSize: 12, background: 'var(--color-bg)', borderRadius: 12 }}>
        No price data
      </div>
    );
  }

  const n = prices.length;
  const sigs = data.signals || [];
  const PT = 2, PB = 72, RT = 78, RB = 100;
  const px = i => (i / (n - 1 || 1)) * 100;

  const closes = prices.map(p => p.close || 0);
  const validPrices = [
    ...closes,
    ...prices.map(p => p.sma20).filter(v => v != null),
    ...prices.map(p => p.sma50).filter(v => v != null),
    ...prices.map(p => p.sma200).filter(v => v != null),
  ];
  const pMin = Math.min(...validPrices) * 0.997;
  const pMax = Math.max(...validPrices) * 1.003;
  const pR = pMax - pMin || 1;
  const py = v => PB - ((v - pMin) / pR) * (PB - PT);
  const pyR = r => RB - (r / 100) * (RB - RT);

  const makePts = getV => {
    let d = '';
    prices.forEach((p, i) => {
      const v = getV(p);
      if (v != null) d += (d ? ' ' : '') + px(i) + ',' + py(v);
    });
    return d;
  };

  const rsiPts = prices.map((p, i) => p.rsi != null ? { x: px(i), y: pyR(p.rsi) } : null).filter(Boolean);
  const rsiLine = rsiPts.map(p => `${p.x},${p.y}`).join(' ');
  const rsiFill = rsiPts.length > 1
    ? `${rsiLine} ${rsiPts[rsiPts.length - 1].x},${RB} ${rsiPts[0].x},${RB}`
    : '';

  const priceLine = prices.map((p, i) => `${px(i)},${py(p.close || 0)}`).join(' ');
  const priceFill = `${priceLine} ${px(n - 1)},${PB} 0,${PB}`;

  const SC = {
    earnings: 'var(--color-warning)',
    insider_buy: 'var(--color-success)',
    insider_sell: 'var(--color-danger)',
    rsi_oversold: 'var(--color-success)',
    rsi_overbought: 'var(--color-danger)',
    sma_cross_bull: '#30d158',
    sma_cross_bear: 'var(--color-danger)',
  };
  const SI = { earnings: 'E', insider_buy: 'B', insider_sell: 'S', rsi_oversold: '◎', rsi_overbought: '◎', sma_cross_bull: '▲', sma_cross_bear: '▼' };

  const d2i = {};
  prices.forEach((p, i) => { d2i[p.date] = i; });
  const mappedSigs = sigs.map(s => {
    let idx = d2i[s.date];
    if (idx == null) {
      let best = 0, bd = Infinity;
      prices.forEach((p, i) => {
        const dd = Math.abs(new Date(p.date) - new Date(s.date));
        if (dd < bd) { bd = dd; best = i; }
      });
      idx = best;
    }
    return { ...s, idx, x: px(idx), color: SC[s.type] || 'var(--color-info)', icon: SI[s.type] || '•' };
  });

  const fmtD = d => d ? d.slice(5) : '';

  return (
    <div style={{ position: 'relative', width: '100%' }}>
      <ChartTooltip tip={tip} />

      {/* Day selector */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 8 }}>
        {[30, 60, 90, 180].map(d => (
          <button
            key={d}
            onClick={() => setSelDays(d)}
            style={{
              padding: '4px 10px', borderRadius: 6, fontSize: 10, fontWeight: 600,
              cursor: 'pointer', fontFamily: 'var(--font-mono)',
              background: selDays === d ? 'var(--imperial-purple-glow)' : 'var(--color-bg-card)',
              border: `1px solid ${selDays === d ? 'var(--imperial-purple)' : 'var(--color-border-subtle)'}`,
              color: selDays === d ? 'var(--imperial-purple)' : 'var(--color-text-secondary)',
            }}
          >
            {d}d
          </button>
        ))}
      </div>

      <svg width="100%" height={340} viewBox="0 0 100 115" preserveAspectRatio="none" style={{ overflow: 'visible', display: 'block' }}>
        {/* Grid lines */}
        {[0.25, 0.5, 0.75, 1].map(f => (
          <line key={`pg${f}`} x1={0} y1={PT + (PB - PT) * f} x2={100} y2={PT + (PB - PT) * f} stroke="var(--color-border-subtle)" strokeWidth={0.2} />
        ))}

        {/* RSI reference lines */}
        <line x1={0} y1={pyR(70)} x2={100} y2={pyR(70)} stroke="var(--color-danger)" strokeWidth={0.25} strokeDasharray="1.5,1" opacity={0.5} />
        <line x1={0} y1={pyR(30)} x2={100} y2={pyR(30)} stroke="var(--color-success)" strokeWidth={0.25} strokeDasharray="1.5,1" opacity={0.5} />
        <line x1={0} y1={pyR(50)} x2={100} y2={pyR(50)} stroke="var(--color-border-subtle)" strokeWidth={0.15} />

        {/* Signal vertical lines */}
        {mappedSigs.map((s, i) => (
          <line key={`svl${i}`} x1={s.x} y1={PT} x2={s.x} y2={RB} stroke={s.color} strokeWidth={0.35} strokeDasharray="1.2,1.2" opacity={0.6} />
        ))}

        {/* Price fill + line */}
        <polygon points={priceFill} fill="var(--imperial-purple)" opacity={0.06} />
        {showSMA.s200 && <polyline points={makePts(p => p.sma200)} fill="none" stroke="var(--imperial-purple-light)" strokeWidth={0.45} opacity={0.75} />}
        {showSMA.s50 && <polyline points={makePts(p => p.sma50)} fill="none" stroke="var(--color-warning)" strokeWidth={0.45} opacity={0.8} />}
        {showSMA.s20 && <polyline points={makePts(p => p.sma20)} fill="none" stroke="var(--color-success)" strokeWidth={0.45} opacity={0.8} />}
        <polyline points={priceLine} fill="none" stroke="var(--imperial-purple)" strokeWidth={0.65} />

        {/* Divider */}
        <line x1={0} y1={RT - 2} x2={100} y2={RT - 2} stroke="var(--color-border-subtle)" strokeWidth={0.3} />

        {/* RSI */}
        {rsiFill && <polygon points={rsiFill} fill="var(--color-warning)" opacity={0.1} />}
        {rsiLine && <polyline points={rsiLine} fill="none" stroke="var(--color-warning)" strokeWidth={0.55} />}

        {/* RSI labels */}
        <text x={1} y={RT + 0.5} fill="var(--color-text-secondary)" fontSize={2.2} dominantBaseline="hanging">RSI</text>
        <text x={99} y={pyR(70)} fill="var(--color-danger)" fontSize={2} textAnchor="end" dominantBaseline="middle">70</text>
        <text x={99} y={pyR(30)} fill="var(--color-success)" fontSize={2} textAnchor="end" dominantBaseline="middle">30</text>

        {/* RSI extreme circles */}
        {mappedSigs.filter(s => s.type === 'rsi_oversold' || s.type === 'rsi_overbought').map((s, i) => (
          <circle key={`sc${i}`} cx={s.x} cy={pyR(s.type === 'rsi_oversold' ? 28 : 72)} r={1.1} fill={s.color} opacity={0.9} />
        ))}

        {/* Signal icons */}
        {mappedSigs.filter(s => s.type !== 'rsi_oversold' && s.type !== 'rsi_overbought').map((s, i) => (
          <text key={`st${i}`} x={s.x} y={PB - 1} fill={s.color} fontSize={2.4} textAnchor="middle" fontFamily="var(--font-mono)" fontWeight="bold">
            {s.icon}
          </text>
        ))}

        {/* Y-axis labels */}
        <text x={1} y={PB} fill="var(--color-text-secondary)" fontSize={2}>${pMin.toFixed(0)}</text>
        <text x={1} y={PT + 2.5} fill="var(--color-text-secondary)" fontSize={2}>${pMax.toFixed(0)}</text>

        {/* X-axis labels */}
        <text x={1} y={104} fill="var(--color-text-secondary)" fontSize={2.2}>{fmtD(prices[0]?.date)}</text>
        {n > 2 && <text x={50} y={104} fill="var(--color-text-secondary)" fontSize={2.2} textAnchor="middle">{fmtD(prices[Math.floor(n / 2)]?.date)}</text>}
        <text x={99} y={104} fill="var(--color-text-secondary)" fontSize={2.2} textAnchor="end">{fmtD(prices[n - 1]?.date)}</text>

        {/* Hover strips */}
        {prices.map((p, i) => (
          <rect
            key={`hs${i}`}
            x={px(i) - 0.6}
            y={0}
            width={1.2}
            height={100}
            fill="transparent"
            onMouseEnter={e => {
              const r = e.target.getBoundingClientRect();
              const pr = e.target.closest('div').getBoundingClientRect();
              const parts = [p.date, `$${(p.close || 0).toFixed(2)}`];
              if (p.rsi != null) parts.push(`RSI ${p.rsi}`);
              if (showSMA.s20 && p.sma20) parts.push(`SMA20 $${p.sma20.toFixed(0)}`);
              if (showSMA.s50 && p.sma50) parts.push(`SMA50 $${p.sma50.toFixed(0)}`);
              setTip({ x: r.left - pr.left, y: r.top - pr.top, text: parts.join('  ') });
            }}
            onMouseLeave={() => setTip(null)}
          />
        ))}
      </svg>

      {/* Legend */}
      <div style={{ display: 'flex', gap: 10, marginTop: 6, flexWrap: 'wrap', alignItems: 'center' }}>
        <span style={{ fontSize: 10, color: 'var(--imperial-purple)', fontWeight: 600 }}>● Price</span>
        <span style={{ fontSize: 10, color: 'var(--color-success)', fontWeight: showSMA.s20 ? 700 : 400, cursor: 'pointer', opacity: showSMA.s20 ? 1 : 0.45 }} onClick={() => setShowSMA(s => ({ ...s, s20: !s.s20 }))}>● SMA20</span>
        <span style={{ fontSize: 10, color: 'var(--color-warning)', fontWeight: showSMA.s50 ? 700 : 400, cursor: 'pointer', opacity: showSMA.s50 ? 1 : 0.45 }} onClick={() => setShowSMA(s => ({ ...s, s50: !s.s50 }))}>● SMA50</span>
        <span style={{ fontSize: 10, color: 'var(--imperial-purple-light)', fontWeight: showSMA.s200 ? 700 : 400, cursor: 'pointer', opacity: showSMA.s200 ? 1 : 0.45 }} onClick={() => setShowSMA(s => ({ ...s, s200: !s.s200 }))}>● SMA200</span>
        <span style={{ fontSize: 10, color: 'var(--color-warning)', fontWeight: 600 }}>┄ RSI</span>
        <span style={{ flex: 1 }} />
        <span style={{ fontSize: 9, color: 'var(--color-warning)', fontFamily: 'var(--font-mono)' }}>E Earnings </span>
        <span style={{ fontSize: 9, color: 'var(--color-success)', fontFamily: 'var(--font-mono)' }}>B Buy </span>
        <span style={{ fontSize: 9, color: 'var(--color-danger)', fontFamily: 'var(--font-mono)' }}>S Sell </span>
        <span style={{ fontSize: 9, color: '#30d158', fontFamily: 'var(--font-mono)' }}>{'▲'} Bull </span>
        <span style={{ fontSize: 9, color: 'var(--color-danger)', fontFamily: 'var(--font-mono)' }}>{'▼'} Bear </span>
        <span style={{ fontSize: 9, color: 'var(--color-success)', fontFamily: 'var(--font-mono)' }}>{'◎'} OS/OB</span>
      </div>
    </div>
  );
}
