/**
 * QUAEST.TECH — The Basilica (Overview / front door)
 * Imperial Twilight rebuild: gold hairlines, tabular figures, Lucide icons,
 * hover-explain on every metric, zero emoji. Matches the Forum (Conviction)
 * page's visual bar. Market indices, killer plays, buy zone, score momentum,
 * LT/Opt leaders, intel layers, interactive RSI overview.
 */

import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Explain } from '../components/ui/Explain';
import { TierBadge } from '../components/ui/TierBadge';
import { SegmentedControl } from '../components/ui/SegmentedControl';
import { SystemHealthWidget } from '../components/ui/SystemHealthWidget';
import {
  Globe, Crosshair, Mail, Sprout, Flame, TrendingUp, TrendingDown,
  FileText, MessageSquare, Waves, Shield, Layers, DirectionIcon,
} from '../components/ui/icons';
import { fetchMarketIndices, fetchMomentumSignals, fetchKillerPlays, fetchBuyZone, sendKillerAlerts } from '../api/endpoints';
import { convictionScore } from '../utils/scoring';
import { fmtTS } from '../utils/formatters';
import styles from './BasilicaPage.module.css';

/** Compact metric tile with inline hover-explain. */
function StatTile({ label, term, title, body, value, sub, tone }) {
  return (
    <div className={styles.statTile}>
      <div className={styles.statLabel}>
        {label}
        <Explain term={term} title={title} body={body} />
      </div>
      <div className={`${styles.statValue} ${tone ? styles[tone] : ''}`}>{value ?? '—'}</div>
      {sub && <div className={styles.statSub}>{sub}</div>}
    </div>
  );
}

function MarketBar() {
  const [indices, setIndices] = useState(null);
  useEffect(() => { fetchMarketIndices().then(d => { if (Array.isArray(d)) setIndices(d); }); }, []);

  if (!indices) return <div className={styles.loading}>Loading global markets…</div>;

  return (
    <div>
      <h2 className={styles.sectionTitle}>
        <Globe size={14} /> Global markets
      </h2>
      <div className={styles.indicesGrid}>
        {indices.map(idx => {
          const up = idx.change_pct != null && idx.change_pct >= 0;
          const dn = idx.change_pct != null && idx.change_pct < 0;
          return (
            <div key={idx.symbol} className={`${styles.indexCard} ${up ? styles.indexUp : dn ? styles.indexDown : ''}`}>
              <div className={styles.indexHeader}>
                <span className={`${styles.indexStatus} ${idx.is_open ? styles.statusOpen : ''}`}>
                  {idx.is_open ? 'OPEN' : 'CLOSED'}
                </span>
              </div>
              <div className={styles.indexName}>{idx.name}</div>
              <div className={styles.indexPrice}>
                {idx.price != null ? idx.price.toLocaleString('en-US', { maximumFractionDigits: 2 }) : '—'}
              </div>
              <div className={`${styles.indexChange} ${up ? styles.up : dn ? styles.dn : ''}`}>
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
    setAlertMsg(r?.status === 'sent' ? 'Email sent' : r?.status === 'email_not_configured' ? 'Email not configured' : 'No plays found');
    setTimeout(() => setAlertSent(false), 4000);
  };

  if (!plays) return <div className={styles.loading}>Loading…</div>;

  const items = plays.killer_plays || plays.plays || [];
  if (!items.length) return <div className={styles.loading}>No high-conviction plays found this cycle.</div>;

  return (
    <div>
      <div className={styles.widgetHeader}>
        <div>
          <h2 className={styles.sectionTitle}>
            <Crosshair size={14} /> Killer plays
            <Explain term="conviction" />
          </h2>
          <div className={styles.widgetSub}>Top options opportunities — click to forge a play</div>
        </div>
        <button className={styles.ghostBtn} onClick={sendAlert} disabled={alertSent}>
          <Mail size={13} /> {alertSent ? alertMsg : 'Send alert'}
        </button>
      </div>
      <div className={styles.playGrid}>
        {items.slice(0, 8).map((p, i) => {
          const combined = p.combined_score || Math.round(convictionScore(p));
          return (
            <div key={i} className={styles.playCard} onClick={() => navigate('/pactum', { state: { ticker: p.ticker } })}>
              <div className={styles.playTop}>
                <span className={styles.playTicker}>{p.ticker}</span>
                <TierBadge score={combined} />
              </div>
              <div className={`${styles.lean} ${styles[`lean_${p.direction || 'neutral'}`]}`}>
                <DirectionIcon dir={p.direction} size={12} />
                {p.direction_label || (p.direction === 'bullish' ? 'Bullish' : p.direction === 'bearish' ? 'Bearish' : 'Neutral')}
              </div>
              <div className={styles.playStats}>
                <span>LT {p.lt_score}</span>
                <span>Opt {p.opt_score}</span>
              </div>
              {p.catalyst && <div className={styles.playDetail}>{p.catalyst}</div>}
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
      <div className={styles.widgetHeader}>
        <div>
          <h2 className={styles.sectionTitle}>
            <Sprout size={14} /> Buy zone
            <Explain term="lt_score" />
          </h2>
          <div className={styles.widgetSub}>Strong fundamentals, not overbought — long-term holds</div>
        </div>
      </div>
      <div className={styles.playGrid}>
        {items.slice(0, 8).map((p, i) => (
          <div key={i} className={styles.playCard} onClick={() => navigate('/conviction', { state: { ticker: p.ticker } })}>
            <div className={styles.playTop}>
              <span className={styles.playTicker}>{p.ticker}</span>
              <span className={`${styles.scorePill} ${styles.up}`}>{p.lt_score}</span>
            </div>
            <div className={styles.playStats}>
              <span>RSI {p.rsi != null ? Math.round(p.rsi) : '—'}</span>
              <span>${p.price}</span>
            </div>
            {p.sector && <div className={styles.playDetail}>{p.sector}</div>}
            {p.catalyst && <div className={styles.playDetail}>{p.catalyst}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}

const MOM_FILTERS = [
  { value: 'all', label: 'All' },
  { value: 'up', label: 'Gainers', Icon: TrendingUp },
  { value: 'down', label: 'Losers', Icon: TrendingDown },
];

function MomentumWidget({ navigate }) {
  const [momentum, setMomentum] = useState(null);
  const [filter, setFilter] = useState('all');
  useEffect(() => { fetchMomentumSignals(20).then(d => { if (d) setMomentum(d); }); }, []);

  const events = (momentum?.events || []).filter(e =>
    filter === 'all' || (filter === 'up' && e.impact === 'positive') || (filter === 'down' && e.impact === 'negative')
  );

  return (
    <Card>
      <div className={styles.widgetHeader}>
        <h2 className={styles.sectionTitle}>
          <Flame size={14} /> Score momentum
          <Explain title="Score momentum" body="Recent meaningful changes in a ticker's LT or Opt score since the last scans." />
        </h2>
        <SegmentedControl options={MOM_FILTERS} value={filter} onChange={setFilter} />
      </div>
      {events.length === 0 ? (
        <div className={styles.empty}>No significant score changes yet.</div>
      ) : (
        <div className={styles.momList}>
          {events.slice(0, 10).map((e, i) => {
            const up = e.impact === 'positive';
            const ageMs = e.scan_ts ? Date.now() - new Date(e.scan_ts.includes('T') ? e.scan_ts : e.scan_ts.replace(' ', 'T') + 'Z') : 0;
            const age = ageMs > 0 ? (ageMs < 3600000 ? Math.round(ageMs / 60000) + 'm' : Math.round(ageMs / 3600000) + 'h') + ' ago' : '';
            return (
              <div key={i} className={`${styles.momRow} ${up ? styles.momUp : styles.momDn}`} onClick={() => navigate(`/ticker/${e.ticker}`)}>
                <span className={styles.momIcon}>{up ? <TrendingUp size={14} /> : <TrendingDown size={14} />}</span>
                <span className={styles.momTicker}>{e.ticker}</span>
                <span className={styles.momText}>{e.signal_text}</span>
                <span className={styles.momAge}>{age}</span>
              </div>
            );
          })}
        </div>
      )}
    </Card>
  );
}

const INTEL_LAYERS = [
  { Icon: FileText, term: 'sec', n: 'SEC filings', d: 'Insider transactions, analyst ratings, holdings' },
  { Icon: MessageSquare, term: 'sentiment', n: 'Sentiment', d: 'Social sentiment + analyst consensus' },
  { Icon: Waves, term: 'whale', n: 'Whale flow', d: 'Unusual options activity, block trades' },
  { Icon: Shield, title: 'Threat intel', body: 'Live breach news, service outages and macro-regime context folded into scoring.', n: 'Threat intel', d: 'Live breach news, service outages, macro regime' },
];

/** Interactive RSI chart — click bars to navigate to ticker page */
function RSIChart({ data, navigate }) {
  const [hovered, setHovered] = useState(null);
  if (!data || !data.length) return null;

  const sorted = [...data].filter(d => d.rsi != null && !isNaN(d.rsi)).sort((a, b) => a.rsi - b.rsi);
  const oversold = sorted.filter(d => d.rsi < 30).length;
  const overbought = sorted.filter(d => d.rsi > 70).length;

  return (
    <div>
      <div className={styles.widgetHeader}>
        <div>
          <h2 className={styles.sectionTitle}>
            RSI overview
            <Explain term="rsi" />
          </h2>
          <div className={styles.widgetSub}>
            Click any bar for ticker detail.{' '}
            {oversold > 0 && <span className={styles.up}>{oversold} oversold</span>}
            {oversold > 0 && overbought > 0 && ' · '}
            {overbought > 0 && <span className={styles.dn}>{overbought} overbought</span>}
          </div>
        </div>
        {hovered && (
          <div className={styles.rsiHover}>{hovered.ticker} · RSI {Math.round(hovered.rsi)}</div>
        )}
      </div>
      <div className={styles.rsiWrap}>
        <svg width="100%" height="100%" viewBox="0 0 100 100" preserveAspectRatio="none" style={{ overflow: 'visible' }}>
          <line x1={0} y1={70} x2={100} y2={70} stroke="var(--loss)" strokeWidth={0.2} strokeDasharray="1,1" />
          <line x1={0} y1={30} x2={100} y2={30} stroke="var(--gain)" strokeWidth={0.2} strokeDasharray="1,1" />
          {[0, 25, 50, 75, 100].map(y => (
            <line key={y} x1={0} y1={y} x2={100} y2={y} stroke="var(--line-soft)" strokeWidth={0.2} />
          ))}
          {sorted.map((d, i) => {
            const w = 100 / sorted.length;
            const rsi = d.rsi || 50;
            const barH = (rsi / 100) * 95;
            const c = rsi < 30 ? 'var(--gain)' : rsi > 70 ? 'var(--loss)' : 'var(--gold)';
            return (
              <rect key={i} x={i * w + w * 0.08} y={100 - barH} width={w * 0.84} height={Math.max(barH, 0.5)}
                fill={c} opacity={hovered?.ticker === d.ticker ? 1 : 0.72} rx={0.5}
                style={{ cursor: 'pointer', transition: 'opacity 0.15s' }}
                onMouseEnter={() => setHovered(d)} onMouseLeave={() => setHovered(null)}
                onClick={() => navigate(`/ticker/${d.ticker}`)} />
            );
          })}
        </svg>
        <div className={styles.rsiAxis}>
          {[100, 70, 50, 30, 0].map(v => (
            <span key={v} className={v === 30 ? styles.up : v === 70 ? styles.dn : ''}>{v}</span>
          ))}
        </div>
      </div>
      <div className={styles.rsiTags}>
        <div className={styles.rsiTagGroup}>
          {sorted.filter(d => d.rsi < 30).slice(0, 5).map(d => (
            <span key={d.ticker} className={`${styles.rsiTag} ${styles.up}`} onClick={() => navigate(`/ticker/${d.ticker}`)}>{d.ticker}</span>
          ))}
        </div>
        <div className={styles.rsiTagGroup}>
          {sorted.filter(d => d.rsi > 70).slice(-5).map(d => (
            <span key={d.ticker} className={`${styles.rsiTag} ${styles.dn}`} onClick={() => navigate(`/ticker/${d.ticker}`)}>{d.ticker}</span>
          ))}
        </div>
      </div>
    </div>
  );
}

function LeaderCard({ title, term, rows, metric, navigate }) {
  return (
    <Card>
      <h2 className={styles.sectionTitle}>{title}<Explain term={term} /></h2>
      <div className={styles.leaderList}>
        {rows.map((r, i) => {
          const score = metric === 'opt' ? r.opt_score : r.lt_score;
          const pct = Math.max(0, Math.min(100, score));
          return (
            <div key={r.ticker} className={styles.leaderRow} onClick={() => navigate(`/ticker/${r.ticker}`)}>
              <span className={styles.leaderRank}>{i + 1}</span>
              <span className={styles.leaderTicker}>{r.ticker}</span>
              <div className={styles.leaderBar}>
                <i style={{ width: `${pct}%` }} />
              </div>
              <span className={styles.leaderScore}>{Math.round(score)}</span>
              <span className={styles.leaderSide}>
                {metric === 'opt' ? `RSI ${r.rsi != null ? Math.round(r.rsi) : '—'}` : `$${r.price}`}
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

export function BasilicaPage({ stats, latest, tz }) {
  const navigate = useNavigate();

  if (!stats && !latest) return <div className={styles.loadingFull}>Loading…</div>;

  const res = latest?.results || [];
  const topLT = [...res].sort((a, b) => b.lt_score - a.lt_score).slice(0, 10);
  const topOpt = [...res].sort((a, b) => b.opt_score - a.opt_score).slice(0, 10);

  const avgLT = res.length > 0 ? (res.reduce((s, r) => s + (r.lt_score || 0), 0) / res.length).toFixed(1) : '—';
  const avgOpt = res.length > 0 ? (res.reduce((s, r) => s + (r.opt_score || 0), 0) / res.length).toFixed(1) : '—';
  const oversold = res.filter(r => r.rsi != null && r.rsi < 30).length;
  const earningsSoon = res.filter(r => r.days_to_earnings != null && r.days_to_earnings <= 14).length;

  return (
    <div className="fade-in">
      <h1 className={styles.title}>Basilica — today</h1>
      <div className={styles.sub}>
        {res.length} tickers scanned across cyber, energy, defense, tech, health & financials · every 30 minutes
      </div>

      {/* Aggregate stats */}
      <div className={styles.statRow}>
        <StatTile label="Universe" title="Universe" body="Total tickers scored in the most recent scan cycle." value={`${res.length}`} sub="tickers" />
        <StatTile label="Avg LT" term="lt_score" value={avgLT} tone={Number(avgLT) >= 45 ? 'up' : 'gold'} sub="fundamentals" />
        <StatTile label="Avg Opt" term="opt_score" value={avgOpt} tone={Number(avgOpt) >= 35 ? 'up' : 'gold'} sub="opportunity" />
        <StatTile label="Oversold" term="rsi" value={oversold} tone={oversold > 0 ? 'up' : undefined} sub="RSI < 30" />
        <StatTile label="Earnings soon" title="Earnings soon" body="Names reporting within 14 days — potential options catalysts." value={earningsSoon} tone={earningsSoon > 0 ? 'tyrian' : undefined} sub="within 14d" />
        <StatTile label="Last scan" title="Last scan" body="When the scanner last refreshed the board." value={stats?.last_scan ? fmtTS(stats.last_scan, tz) : '—'} />
      </div>

      {/* System health */}
      <div className={styles.block}><SystemHealthWidget /></div>

      {/* Market indices */}
      <Card className={styles.block}><MarketBar /></Card>

      {/* Killer plays + buy zone */}
      <div className={`${styles.twoCol} ${styles.block}`}>
        <Card><KillerPlaysWidget navigate={navigate} /></Card>
        <Card><BuyZoneWidget navigate={navigate} /></Card>
      </div>

      {/* Score momentum */}
      <div className={styles.block}><MomentumWidget navigate={navigate} /></div>

      {/* Leaders */}
      <div className={`${styles.twoCol} ${styles.block}`}>
        <LeaderCard title="Long-term leaders" term="lt_score" rows={topLT} metric="lt" navigate={navigate} />
        <LeaderCard title="Options leaders" term="opt_score" rows={topOpt} metric="opt" navigate={navigate} />
      </div>

      {/* Intel layers */}
      <Card className={styles.block}>
        <h2 className={styles.sectionTitle}><Layers size={14} /> Intelligence layers</h2>
        <div className={styles.intelGrid}>
          {INTEL_LAYERS.map(l => (
            <div key={l.n} className={styles.intelCard}>
              <div className={styles.intelHeader}>
                <span className={styles.intelIcon}><l.Icon size={15} /></span>
                <span className={styles.intelName}>{l.n}<Explain term={l.term} title={l.title} body={l.body} /></span>
                <span className={styles.liveDot}>Live</span>
              </div>
              <div className={styles.intelDesc}>{l.d}</div>
            </div>
          ))}
        </div>
      </Card>

      {/* RSI overview */}
      {res.length > 0 && (
        <Card className={`${styles.block} ${styles.rsiCard}`}>
          <RSIChart data={res} navigate={navigate} />
        </Card>
      )}

      <div className={styles.foot}>
        Imperial Twilight · gold hairlines · tabular figures · hover any metric to explain · zero emoji
      </div>
    </div>
  );
}
