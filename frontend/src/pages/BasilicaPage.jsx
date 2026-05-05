/**
 * QUAEST.TECH — The Basilica (Overview)
 * Dashboard overview with market indices, killer plays, momentum signals,
 * LT/Opt leaders, intel layers, and interactive RSI overview.
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Metric } from '../components/ui/Metric';
import { ScoreBar } from '../components/ui/ScoreBar';
import { Badge } from '../components/ui/Badge';
import { SvgBarChart } from '../components/charts/SvgBarChart';
import { fetchMarketIndices, fetchMomentumSignals, fetchKillerPlays, fetchBuyZone, sendKillerAlerts } from '../api/endpoints';
import { SystemHealthWidget } from '../components/ui/SystemHealthWidget';
import { fmtTS } from '../utils/formatters';
import styles from './BasilicaPage.module.css';

function MarketBar() {
  const [indices, setIndices] = useState(null);
  useEffect(() => { fetchMarketIndices().then(d => { if (Array.isArray(d)) setIndices(d); }); }, []);

  if (!indices) return <div className={styles.loading}>Loading global markets...</div>;

  return (
    <div>
      <h2 className={styles.sectionTitle}>Global Markets</h2>
      <div className={styles.indicesGrid}>
        {indices.map(idx => {
          const up = idx.change_pct != null && idx.change_pct >= 0;
          const dn = idx.change_pct != null && idx.change_pct < 0;
          return (
            <div key={idx.symbol} className={`${styles.indexCard} ${up ? styles.indexUp : dn ? styles.indexDown : ''}`}>
              <div className={styles.indexHeader}>
                <span style={{ fontSize: 14 }}>{idx.flag || '🌐'}</span>
                <span className={`${styles.indexStatus} ${idx.is_open ? styles.statusOpen : ''}`}>
                  {idx.is_open ? 'OPEN' : 'CLOSED'}
                </span>
              </div>
              <div className={styles.indexName}>{idx.name}</div>
              <div className={styles.indexPrice}>
                {idx.price != null ? idx.price.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—'}
              </div>
              <div className={styles.indexChange} style={{ color: up ? 'var(--color-success)' : dn ? 'var(--color-danger)' : 'var(--color-text-secondary)' }}>
                {idx.change_pct != null ? `${up ? '+' : ''}${idx.change_pct.toFixed(2)}%` : '—'}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function KillerPlaysWidget({ navigate }) {
  const [plays, setPlays] = useState(null);
  const [alertSent, setAlertSent] = useState(false);
  const [alertMsg, setAlertMsg] = useState('');

  useEffect(() => { fetchKillerPlays(8).then(d => { if (d) setPlays(d); }); }, []);

  const sendAlert = async () => {
    const r = await sendKillerAlerts();
    setAlertSent(true);
    setAlertMsg(r?.status === 'sent' ? '✓ Email sent' : r?.status === 'email_not_configured' ? 'Email not configured' : 'No plays found');
    setTimeout(() => setAlertSent(false), 4000);
  };

  if (!plays) return <div className={styles.loading}>Loading…</div>;

  const items = plays.killer_plays || plays.plays || [];
  if (!items.length) return <div className={styles.loading}>No high-conviction plays found this cycle.</div>;

  return (
    <div>
      <div className={styles.killerHeader}>
        <div>
          <h2 className={styles.sectionTitleLg} style={{ marginBottom: 2 }}>{'⚔️'} Killer Plays</h2>
          <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>
            Top options opportunities — click to generate play
          </div>
        </div>
        <button className={styles.alertBtn} onClick={sendAlert} disabled={alertSent}>
          {alertSent ? alertMsg : '📧 Send Alert'}
        </button>
      </div>
      <div className={styles.killerGrid}>
        {items.slice(0, 8).map((p, i) => {
          const combined = p.combined_score || Math.round((p.opt_score || 0) * 0.6 + (p.lt_score || 0) * 0.4);
          const dirColor = p.direction === 'bullish' ? 'var(--color-success)' : p.direction === 'bearish' ? 'var(--color-danger)' : 'var(--imperial-purple)';
          return (
            <div key={i} className={styles.killerCard} onClick={() => navigate('/pactum', { state: { ticker: p.ticker } })}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
                <div className={styles.killerTicker}>{p.ticker}</div>
                <div style={{ fontSize: 14, fontWeight: 800, fontFamily: 'var(--font-mono)', color: dirColor }}>{combined}</div>
              </div>
              <div className={styles.killerType}>
                <Badge color={dirColor}>
                  {p.direction_label || (p.direction === 'bullish' ? '▲ Bullish' : p.direction === 'bearish' ? '▼ Bearish' : '↔ Neutral')}
                </Badge>
              </div>
              <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
                <span style={{ fontSize: 9, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-mono)' }}>LT {p.lt_score}</span>
                <span style={{ fontSize: 9, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-mono)' }}>Opt {p.opt_score}</span>
              </div>
              {p.catalyst && <div className={styles.killerDetail}>{p.catalyst}</div>}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function BuyZoneWidget({ navigate }) {
  const [data, setData] = useState(null);

  useEffect(() => { fetchBuyZone(8).then(d => { if (d) setData(d); }); }, []);

  if (!data) return <div className={styles.loading}>Loading…</div>;

  const items = data.picks || [];
  if (!items.length) return <div className={styles.loading}>No buy zone picks this cycle.</div>;

  return (
    <div>
      <div className={styles.killerHeader}>
        <div>
          <h2 className={styles.sectionTitleLg} style={{ marginBottom: 2 }}>{'🟢'} Buy Zone</h2>
          <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>
            Strong fundamentals + not overbought — long-term holds
          </div>
        </div>
      </div>
      <div className={styles.killerGrid}>
        {items.slice(0, 8).map((p, i) => (
          <div key={i} className={styles.killerCard} onClick={() => navigate('/conviction', { state: { ticker: p.ticker } })}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 4 }}>
              <div className={styles.killerTicker}>{p.ticker}</div>
              <div style={{ fontSize: 14, fontWeight: 800, fontFamily: 'var(--font-mono)', color: 'var(--color-success)' }}>{p.lt_score}</div>
            </div>
            <div className={styles.killerType}>
              <Badge color="var(--color-success)">LT {p.lt_score} · RSI {p.rsi != null ? Math.round(p.rsi) : '—'}</Badge>
            </div>
            <div style={{ display: 'flex', gap: 6, marginTop: 4 }}>
              <span style={{ fontSize: 9, color: 'var(--color-text-tertiary)', fontFamily: 'var(--font-mono)' }}>${p.price}</span>
              {p.sector && <span style={{ fontSize: 9, color: 'var(--color-text-tertiary)' }}>{p.sector}</span>}
            </div>
            {p.catalyst && <div className={styles.killerDetail}>{p.catalyst}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Interactive RSI chart — click bars to navigate to ticker page */
function RSIChart({ data, navigate }) {
  const [hoveredTicker, setHoveredTicker] = useState(null);

  if (!data || !data.length) return null;

  // Filter to only show tickers with valid RSI and sort by RSI
  const sorted = [...data].filter(d => d.rsi != null && !isNaN(d.rsi)).sort((a, b) => a.rsi - b.rsi);
  const oversold = sorted.filter(d => d.rsi < 30).length;
  const overbought = sorted.filter(d => d.rsi > 70).length;

  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 12 }}>
        <div>
          <h2 className={styles.sectionTitleLg} style={{ marginBottom: 2 }}>RSI Overview</h2>
          <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>
            Click any bar to view ticker details. {oversold > 0 && <span style={{ color: 'var(--color-success)' }}>{oversold} oversold</span>}
            {oversold > 0 && overbought > 0 && ' · '}
            {overbought > 0 && <span style={{ color: 'var(--color-danger)' }}>{overbought} overbought</span>}
          </div>
        </div>
        {hoveredTicker && (
          <div style={{ fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--imperial-purple)' }}>
            {hoveredTicker.ticker}: RSI {Math.round(hoveredTicker.rsi)}
          </div>
        )}
      </div>
      <div style={{ position: 'relative', width: '100%', height: 350 }}>
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ overflow: 'visible' }}>
          {/* RSI zone lines */}
          <line x1={0} y1={70} x2={100} y2={70} stroke="var(--color-success)" strokeWidth={0.2} strokeDasharray="1,1" />
          <line x1={0} y1={30} x2={100} y2={30} stroke="var(--color-danger)" strokeWidth={0.2} strokeDasharray="1,1" />
          {[0, 25, 50, 75, 100].map(y => (
            <line key={y} x1={0} y1={y} x2={100} y2={y} stroke="var(--color-border-subtle)" strokeWidth={0.2} />
          ))}
          {sorted.map((d, i) => {
            const w = 100 / sorted.length;
            const rsi = d.rsi || 50;
            const barH = (rsi / 100) * 95;
            const c = rsi < 30 ? 'var(--color-success)' : rsi > 70 ? 'var(--color-danger)' : 'var(--color-warning)';
            return (
              <rect
                key={i}
                x={i * w + w * 0.08}
                y={100 - barH}
                width={w * 0.84}
                height={Math.max(barH, 0.5)}
                fill={c}
                opacity={hoveredTicker?.ticker === d.ticker ? 1 : 0.7}
                rx={0.5}
                style={{ cursor: 'pointer', transition: 'opacity 0.15s' }}
                onMouseEnter={() => setHoveredTicker(d)}
                onMouseLeave={() => setHoveredTicker(null)}
                onClick={() => navigate(`/ticker/${d.ticker}`)}
              />
            );
          })}
        </svg>
        {/* Y-axis labels */}
        <div style={{ position: 'absolute', left: -24, top: 0, bottom: 0, display: 'flex', flexDirection: 'column', justifyContent: 'space-between', pointerEvents: 'none' }}>
          {[100, 70, 50, 30, 0].map(v => (
            <span key={v} style={{ fontSize: 8, color: v === 30 ? 'var(--color-success)' : v === 70 ? 'var(--color-danger)' : 'var(--color-text-tertiary)', fontFamily: 'var(--font-mono)' }}>{v}</span>
          ))}
        </div>
      </div>
      {/* Ticker labels for oversold/overbought extremes */}
      <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 6, padding: '0 2px' }}>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {sorted.filter(d => d.rsi < 30).slice(0, 5).map(d => (
            <span key={d.ticker} onClick={() => navigate(`/ticker/${d.ticker}`)}
              style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--color-success)', cursor: 'pointer', fontWeight: 700 }}>
              {d.ticker}
            </span>
          ))}
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {sorted.filter(d => d.rsi > 70).slice(-5).map(d => (
            <span key={d.ticker} onClick={() => navigate(`/ticker/${d.ticker}`)}
              style={{ fontSize: 9, fontFamily: 'var(--font-mono)', color: 'var(--color-danger)', cursor: 'pointer', fontWeight: 700 }}>
              {d.ticker}
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}

export function BasilicaPage({ stats, latest, tz }) {
  const navigate = useNavigate();
  const [momentum, setMomentum] = useState(null);
  const [momFilter, setMomFilter] = useState('all');

  useEffect(() => { fetchMomentumSignals(20).then(d => { if (d) setMomentum(d); }); }, []);

  if (!stats && !latest) return <div className={styles.loadingFull}>Loading...</div>;

  const res = latest?.results || [];
  const topLT = res.slice(0, 10);
  const topOpt = [...res].sort((a, b) => b.opt_score - a.opt_score).slice(0, 10);
  const momEvt = (momentum?.events || []).filter(e =>
    momFilter === 'all' || (momFilter === 'up' && e.impact === 'positive') || (momFilter === 'down' && e.impact === 'negative')
  );

  // Compute aggregate metrics
  const avgLT = res.length > 0 ? (res.reduce((sum, r) => sum + (r.lt_score || 0), 0) / res.length).toFixed(1) : '—';
  const avgOpt = res.length > 0 ? (res.reduce((sum, r) => sum + (r.opt_score || 0), 0) / res.length).toFixed(1) : '—';
  const oversold = res.filter(r => r.rsi != null && r.rsi < 30).length;
  const earningsSoon = res.filter(r => r.days_to_earnings != null && r.days_to_earnings <= 14).length;

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Intro banner */}
      <div className={styles.banner}>
        <strong>QUAEST</strong> scans <strong>{res.length} tickers</strong> across cyber, energy, defense, tech, health, financials, and more &mdash; every 30 minutes.{' '}
        <strong>LT Score</strong> = fundamentals. <strong>Opt Score</strong> = options opportunity.
      </div>

      {/* Market indices */}
      <Card style={{ padding: 16 }}><MarketBar /></Card>

      {/* Stats — improved with actionable metrics */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))', gap: 12 }}>
        <Metric label="Universe" value={`${res.length} tickers`} />
        <Metric label="Avg LT Score" value={avgLT} color={Number(avgLT) >= 45 ? 'var(--color-success)' : 'var(--color-warning)'} />
        <Metric label="Avg Opt Score" value={avgOpt} color={Number(avgOpt) >= 35 ? 'var(--color-success)' : 'var(--color-warning)'} />
        <Metric label="Oversold" value={oversold} color={oversold > 0 ? 'var(--color-success)' : 'var(--color-text-secondary)'} sub="RSI < 30" />
        <Metric label="Earnings Soon" value={earningsSoon} color={earningsSoon > 0 ? 'var(--imperial-purple)' : 'var(--color-text-secondary)'} sub="Within 14d" />
        <Metric label="Last Scan" value={stats?.last_scan ? fmtTS(stats.last_scan, tz) : '—'} />
      </div>

      {/* System Health */}
      <SystemHealthWidget />

      {/* Killer Plays + Buy Zone — side by side */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 16 }}>
        <Card style={{ padding: 20 }}>
          <KillerPlaysWidget navigate={navigate} />
        </Card>
        <Card style={{ padding: 20 }}>
          <BuyZoneWidget navigate={navigate} />
        </Card>
      </div>

      {/* Score Momentum */}
      <Card style={{ padding: 20 }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 8, marginBottom: momEvt.length > 0 ? 14 : 8 }}>
          <h2 className={styles.sectionTitleLg}>{'🔥'} Score Momentum</h2>
          <div style={{ display: 'flex', gap: 4 }}>
            {[['all', 'All'], ['up', '📈 Gainers'], ['down', '📉 Losers']].map(([k, l]) => (
              <button key={k} onClick={() => setMomFilter(k)} className={`${styles.filterBtn} ${momFilter === k ? styles.filterActive : ''}`}>
                {l}
              </button>
            ))}
          </div>
        </div>
        {momEvt.length === 0 ? (
          <div className={styles.emptyMsg}>No significant score changes yet.</div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {momEvt.slice(0, 10).map((e, i) => {
              const up = e.impact === 'positive';
              const col = up ? 'var(--color-success)' : 'var(--color-danger)';
              const ageMs = e.scan_ts ? Date.now() - new Date(e.scan_ts.includes('T') ? e.scan_ts : e.scan_ts.replace(' ', 'T') + 'Z') : 0;
              const age = ageMs > 0 ? (ageMs < 3600000 ? Math.round(ageMs / 60000) + 'm' : Math.round(ageMs / 3600000) + 'h') + ' ago' : '';
              return (
                <div key={i} className={styles.momRow} onClick={() => navigate(`/ticker/${e.ticker}`)} style={{ borderLeftColor: col + '30' }}>
                  <span className={styles.momTicker}>{e.ticker}</span>
                  <span className={styles.momText}>{e.signal_text}</span>
                  <span className={styles.momAge}>{age}</span>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* Leaders — now clickable to ticker page */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Card style={{ padding: 20 }}>
          <h2 className={styles.sectionTitleLg}>Long-Term Leaders</h2>
          {topLT.map((r, i) => (
            <div key={r.ticker} className={styles.leaderRow} onClick={() => navigate(`/ticker/${r.ticker}`)} style={{ cursor: 'pointer', borderRadius: 6, padding: '5px 4px' }}>
              <span className={styles.leaderRank}>{i + 1}</span>
              <span className={styles.leaderTicker}>{r.ticker}</span>
              <ScoreBar score={r.lt_score} showLabel />
              <span className={styles.leaderPrice}>${r.price}</span>
            </div>
          ))}
        </Card>
        <Card style={{ padding: 20 }}>
          <h2 className={styles.sectionTitleLg}>Options Leaders</h2>
          {topOpt.map((r, i) => (
            <div key={r.ticker} className={styles.leaderRow} onClick={() => navigate(`/ticker/${r.ticker}`)} style={{ cursor: 'pointer', borderRadius: 6, padding: '5px 4px' }}>
              <span className={styles.leaderRank}>{i + 1}</span>
              <span className={styles.leaderTicker}>{r.ticker}</span>
              <ScoreBar score={r.opt_score} showLabel />
              <span className={styles.leaderPrice}>RSI {r.rsi != null ? Math.round(r.rsi) : '—'}</span>
            </div>
          ))}
        </Card>
      </div>

      {/* Intel Layers */}
      <Card style={{ padding: 20 }}>
        <h2 className={styles.sectionTitleLg}>Intelligence Layers</h2>
        <div className={styles.intelGrid}>
          {[
            { i: '📋', n: 'SEC Filings', d: 'Insider transactions, analyst ratings, holdings' },
            { i: '💬', n: 'Sentiment', d: 'Social sentiment + analyst consensus' },
            { i: '🐋', n: 'Whale Flow', d: 'Unusual options activity, block trades' },
            { i: '🛡', n: 'Threat Intel', d: 'Live breach news, service outages, macro regime' },
          ].map(l => (
            <div key={l.n} className={styles.intelCard}>
              <div className={styles.intelHeader}>
                <span style={{ fontSize: 16 }}>{l.i}</span>
                <span className={styles.intelName}>{l.n}</span>
                <Badge color="var(--color-success)" variant="soft">Live</Badge>
              </div>
              <div className={styles.intelDesc}>{l.d}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* RSI Overview — interactive, larger */}
      {res.length > 0 && (
        <Card style={{ padding: '20px 20px 20px 44px' }}>
          <RSIChart data={res} navigate={navigate} />
        </Card>
      )}
    </div>
  );
}
