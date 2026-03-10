/**
 * QUAEST.TECH — The Basilica (Overview)
 * Dashboard overview with market indices, killer plays, momentum signals,
 * LT/Opt leaders, intel layers, and RSI overview.
 */

import { useState, useEffect, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Metric } from '../components/ui/Metric';
import { ScoreBar } from '../components/ui/ScoreBar';
import { Badge } from '../components/ui/Badge';
import { SvgBarChart } from '../components/charts/SvgBarChart';
import { fetchMarketIndices, fetchMomentumSignals, fetchKillerPlays, sendKillerAlerts } from '../api/endpoints';
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

function KillerPlaysWidget({ onSelectPlay }) {
  const [plays, setPlays] = useState(null);
  const [alertSent, setAlertSent] = useState(false);
  const [alertMsg, setAlertMsg] = useState('');

  useEffect(() => { fetchKillerPlays(6).then(d => { if (d) setPlays(d); }); }, []);

  const sendAlert = async () => {
    const r = await sendKillerAlerts();
    setAlertSent(true);
    setAlertMsg(r?.status === 'sent' ? '✓ Email sent' : r?.status === 'email_not_configured' ? 'Email not configured' : 'No plays found');
    setTimeout(() => setAlertSent(false), 4000);
  };

  if (!plays) return <div className={styles.loading}>Loading killer plays...</div>;

  const items = plays.killer_plays || plays.plays || [];
  if (!items.length) return <div className={styles.loading}>No high-conviction plays found.</div>;

  return (
    <div>
      <div className={styles.killerHeader}>
        <h2 className={styles.sectionTitleLg}>{'⚔️'} Killer Plays</h2>
        <button className={styles.alertBtn} onClick={sendAlert} disabled={alertSent}>
          {alertSent ? alertMsg : '📧 Send Alert'}
        </button>
      </div>
      <div className={styles.killerGrid}>
        {items.slice(0, 6).map((p, i) => (
          <div key={i} className={styles.killerCard} onClick={() => onSelectPlay?.(p.ticker)}>
            <div className={styles.killerTicker}>{p.ticker}</div>
            <div className={styles.killerType}>
              <Badge color={p.direction === 'bullish' ? 'var(--color-success)' : 'var(--color-danger)'}>
                {p.direction === 'bullish' ? '▲' : '▼'} {p.strategy || p.direction}
              </Badge>
            </div>
            <div className={styles.killerDetail}>
              {p.strike && `$${p.strike}`} {p.expiry && `exp ${p.expiry}`}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function BasilicaPage({ stats, latest, tz }) {
  const navigate = useNavigate();
  const [momentum, setMomentum] = useState(null);
  const [momFilter, setMomFilter] = useState('all');

  useEffect(() => { fetchMomentumSignals(20).then(d => { if (d) setMomentum(d); }); }, []);

  const onSelectPlay = useCallback((ticker) => {
    navigate('/anvil', { state: { ticker } });
  }, [navigate]);

  if (!stats) return <div className={styles.loadingFull}>Loading...</div>;

  const res = latest?.results || [];
  const topLT = res.slice(0, 10);
  const topOpt = [...res].sort((a, b) => b.opt_score - a.opt_score).slice(0, 10);
  const rsiData = [...res].sort((a, b) => a.rsi - b.rsi);
  const momEvt = (momentum?.events || []).filter(e =>
    momFilter === 'all' || (momFilter === 'up' && e.impact === 'positive') || (momFilter === 'down' && e.impact === 'negative')
  );

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Intro banner */}
      <div className={styles.banner}>
        <strong>QUAEST</strong> scans <strong>{res.length} tickers</strong> across cyber, energy, defense, tech, health, financials, and more &mdash; every 30 minutes.{' '}
        <strong>LT Score</strong> = fundamentals. <strong>Opt Score</strong> = options opportunity.
      </div>

      {/* Market indices */}
      <Card style={{ padding: 16 }}><MarketBar /></Card>

      {/* Stats */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12 }}>
        <Metric label="Total Scans" value={stats.total_scans} />
        <Metric label="Universe" value={`${res.length} tickers`} />
        <Metric label="Records" value={(stats.total_score_records || 0).toLocaleString()} />
        <Metric label="Last Scan" value={stats.last_scan ? fmtTS(stats.last_scan, tz) : '—'} />
      </div>

      {/* Killer Plays */}
      <Card style={{ padding: 20 }}>
        <KillerPlaysWidget onSelectPlay={onSelectPlay} />
      </Card>

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
                <div key={i} className={styles.momRow} onClick={() => navigate('/conviction')} style={{ borderLeftColor: col + '30' }}>
                  <span className={styles.momTicker}>{e.ticker}</span>
                  <span className={styles.momText}>{e.signal_text}</span>
                  <span className={styles.momAge}>{age}</span>
                </div>
              );
            })}
          </div>
        )}
      </Card>

      {/* Leaders */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <Card style={{ padding: 20 }}>
          <h2 className={styles.sectionTitleLg}>Long-Term Leaders</h2>
          {topLT.map((r, i) => (
            <div key={r.ticker} className={styles.leaderRow}>
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
            <div key={r.ticker} className={styles.leaderRow}>
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

      {/* RSI Overview */}
      {rsiData.length > 0 && (
        <Card style={{ padding: 20 }}>
          <h2 className={styles.sectionTitleLg}>RSI Overview</h2>
          <SvgBarChart
            data={rsiData}
            dataKey="rsi"
            labelKey="ticker"
            height={220}
            colorFn={(d) => d.rsi < 30 ? 'var(--color-success)' : d.rsi > 70 ? 'var(--color-danger)' : 'var(--color-warning)'}
          />
        </Card>
      )}
    </div>
  );
}
