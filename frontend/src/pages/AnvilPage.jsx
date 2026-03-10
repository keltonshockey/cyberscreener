/**
 * QUAEST.TECH — The Anvil (Options/Plays Tab)
 * Play generation, weight tuner, Reality Check, play history.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useLocation } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Metric } from '../components/ui/Metric';
import { Badge } from '../components/ui/Badge';
import { ScoreBar } from '../components/ui/ScoreBar';
import { generatePlays, fetchPlayStatus, fetchPlayHistory, fetchWeights, updateWeights, fetchInversePlays, analyzePlaysTicker } from '../api/endpoints';
import { getRC, rcVerdict, rcBreakdown } from '../utils/scoring';
import { fmtExpiry, fmtTimeOnly } from '../utils/formatters';
import { useAuth } from '../auth/AuthContext';
import styles from './AnvilPage.module.css';

const ANVIL_SORT_OPTIONS = [
  { key: 'opt_score', label: 'Opt Score', fn: (a, b) => b.opt_score - a.opt_score },
  { key: 'lt_score', label: 'LT Score', fn: (a, b) => b.lt_score - a.lt_score },
  { key: 'iv_high', label: 'IV Rank (High)', fn: (a, b) => (b.iv_30d || 0) - (a.iv_30d || 0) },
  { key: 'earnings', label: 'Earnings Soon', fn: (a, b) => (a.days_to_earnings || 999) - (b.days_to_earnings || 999) },
  { key: 'rsi_low', label: 'RSI (Oversold)', fn: (a, b) => (a.rsi || 50) - (b.rsi || 50) },
];

function MiniMetric({ label, value, color }) {
  return (
    <div className={styles.miniMetric}>
      <div className={styles.miniLabel}>{label}</div>
      <div className={styles.miniValue} style={color ? { color } : undefined}>{value}</div>
    </div>
  );
}

export function AnvilPage({ latest, defaultTicker, tz }) {
  const { isAdmin } = useAuth();
  const location = useLocation();
  const [sel, setSel] = useState(null);
  const [data, setData] = useState(null);
  const [msg, setMsg] = useState('');
  const [showW, setShowW] = useState(false);
  const [fetchedAt, setFetchedAt] = useState(null);
  const [tick, setTick] = useState(0);
  const [showHist, setShowHist] = useState(false);
  const [playHist, setPlayHist] = useState(null);
  const [histLoading, setHistLoading] = useState(false);
  const [ow, setOw] = useState({ earnings_catalyst: 25, iv_context: 20, directional: 20, technical: 15, liquidity: 10, asymmetry: 10 });
  const [anvilSort, setAnvilSort] = useState('opt_score');
  const [playSort, setPlaySort] = useState('rc');
  const [aiAnalysis, setAiAnalysis] = useState(null);
  const [aiLoading, setAiLoading] = useState(false);

  const poller = useRef(null);
  const timer = useRef(null);
  const autoRef = useRef(null);

  const results = latest?.results || [];
  const sortFn = ANVIL_SORT_OPTIONS.find(s => s.key === anvilSort)?.fn || ANVIL_SORT_OPTIONS[0].fn;
  const opts = [...results].sort(sortFn);
  const wt = Object.values(ow).reduce((a, b) => a + b, 0);

  // Handle incoming ticker from search bar
  useEffect(() => {
    if (location.state?.ticker && location.state.ticker !== sel) {
      loadPlays(location.state.ticker);
    }
  }, [location.state?.ticker]);

  useEffect(() => { fetchWeights().then(w => { if (w?.active_weights?.opt) setOw(w.active_weights.opt); }); }, []);
  useEffect(() => { if (defaultTicker && defaultTicker !== sel) loadPlays(defaultTicker); }, [defaultTicker]);
  useEffect(() => { const id = setInterval(() => setTick(n => n + 1), 20000); return () => clearInterval(id); }, []);
  useEffect(() => () => cleanup(), []);

  function cleanup() {
    if (poller.current) clearInterval(poller.current);
    if (timer.current) clearTimeout(timer.current);
    if (autoRef.current) { clearInterval(autoRef.current); autoRef.current = null; }
    poller.current = timer.current = null;
  }

  async function loadHistory() {
    if (playHist) return;
    setHistLoading(true);
    const d = await fetchPlayHistory(50);
    if (d) setPlayHist(d);
    setHistLoading(false);
  }

  async function loadPlays(t, force = false) {
    cleanup();
    setSel(t);
    if (!force) setData(null);
    setMsg('Starting...');
    const d = await generatePlays(t);
    if (!d) { setData({ ticker: t, plays: [], error: 'Could not reach API' }); return; }

    const gotData = (r) => {
      setData(r);
      setFetchedAt(Date.now());
      if (!r.error && r.plays?.length) {
        autoRef.current = setInterval(() => loadPlays(t, true), 120000);
      }
    };

    if (d.status === 'cached') { gotData(d.result); return; }
    setMsg(d.message || 'Working...');

    poller.current = setInterval(async () => {
      const s = await fetchPlayStatus(t);
      if (!s) return;
      if (s.status === 'done') {
        if (poller.current) clearInterval(poller.current);
        if (timer.current) clearTimeout(timer.current);
        poller.current = timer.current = null;
        gotData(s.result || { ticker: t, plays: [], error: 'No data' });
      } else if (s.status === 'running') setMsg(s.message || 'Working...');
    }, 2000);

    timer.current = setTimeout(() => {
      cleanup();
      setData(prev => prev || { ticker: t, plays: [], error: 'Timed out' });
    }, 45000);
  }

  // ── Render detail panel ──
  let detail;

  if (!sel) {
    const stats = playHist?.stats;
    const plays = playHist?.plays || [];
    detail = (
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Card style={{ padding: 40, textAlign: 'center' }}>
          <div style={{ fontSize: 32, marginBottom: 12, opacity: 0.5 }}>{'⚔️'}</div>
          <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>The Anvil</div>
          <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', maxWidth: 480, margin: '0 auto', lineHeight: 1.7 }}>
            Select a ticker to forge options plays. Each includes scoring breakdown, Reality Check, and risk/reward analysis.
          </div>
        </Card>

        {/* Play history toggle */}
        <Card style={{ padding: 20, cursor: 'pointer' }} onClick={() => { if (!showHist) loadHistory(); setShowHist(s => !s); }}>
          <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: showHist ? 14 : 0 }}>
            <h2 style={{ fontSize: 15, fontWeight: 700, margin: 0 }}>{'📈'} Play History</h2>
            <span style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>{showHist ? '▲ hide' : '▼ expand'}</span>
          </div>
          {showHist && (
            <div onClick={e => e.stopPropagation()}>
              {histLoading && <div className={styles.loading}>Loading play history...</div>}
              {!histLoading && plays.length === 0 && <div className={styles.loading}>No closed plays yet.</div>}
              {!histLoading && stats?.total_closed > 0 && (
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(4, 1fr)', gap: 10, marginBottom: 14 }}>
                  <Metric label="Closed" value={stats.total_closed} />
                  <Metric label="Win Rate" value={stats.win_rate != null ? stats.win_rate + '%' : '—'} color={stats.win_rate >= 55 ? 'var(--color-success)' : 'var(--color-warning)'} />
                  <Metric label="Avg P&L" value={stats.avg_pnl != null ? `${stats.avg_pnl > 0 ? '+' : ''}${stats.avg_pnl}%` : '—'} color={stats.avg_pnl > 0 ? 'var(--color-success)' : 'var(--color-danger)'} />
                  <Metric label="Best Play" value={stats.best_play?.ticker || '—'} sub={stats.best_play?.pnl_pct != null ? `${stats.best_play.pnl_pct > 0 ? '+' : ''}${stats.best_play.pnl_pct}%` : ''} />
                </div>
              )}
              {!histLoading && plays.length > 0 && (
                <div style={{ overflowX: 'auto' }}>
                  <table className={styles.histTable}>
                    <thead>
                      <tr>
                        {['Ticker', 'Strategy', 'Direction', 'Expiry', 'DTE', 'RC', 'Entry', 'P&L', 'Date'].map(h => (
                          <th key={h}>{h}</th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {plays.map((p, i) => {
                        const pnl = p.pnl_pct;
                        const pnlColor = pnl == null ? 'var(--color-text-tertiary)' : pnl > 0 ? 'var(--color-success)' : 'var(--color-danger)';
                        return (
                          <tr key={i} style={{ background: i % 2 === 0 ? 'var(--color-bg)' : 'transparent' }}>
                            <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{p.ticker}</td>
                            <td>{p.strategy || '—'}</td>
                            <td>{(p.direction || '').charAt(0).toUpperCase() + (p.direction || '').slice(1)}</td>
                            <td style={{ fontFamily: 'var(--font-mono)' }}>{fmtExpiry(p.expiry)}</td>
                            <td>{p.dte || '—'}</td>
                            <td style={{ fontWeight: 600, color: p.rc_score >= 70 ? 'var(--color-success)' : p.rc_score >= 50 ? 'var(--color-warning)' : 'var(--color-text-tertiary)' }}>{p.rc_score || '—'}</td>
                            <td style={{ fontFamily: 'var(--font-mono)' }}>${p.entry_price || '—'}</td>
                            <td style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', color: pnlColor }}>{pnl != null ? `${pnl > 0 ? '+' : ''}${pnl}%` : '—'}</td>
                            <td style={{ color: 'var(--color-text-tertiary)' }}>{p.outcome_date || p.generated_at?.slice(0, 10) || '—'}</td>
                          </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
              )}
            </div>
          )}
        </Card>

        {/* How scoring works */}
        <Card style={{ padding: 24 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>How Options Scoring Works</h3>
          <div style={{ fontSize: 12, color: 'var(--color-text-secondary)', lineHeight: 1.7, marginBottom: 12 }}>
            The Options Score (0&ndash;100) has six weighted components:
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
            {[
              { n: 'Earnings Catalyst', w: ow.earnings_catalyst, d: 'Proximity to earnings — #1 IV driver. Sweet spot: 5–14 days out.' },
              { n: 'IV Context', w: ow.iv_context, d: 'IV rank vs history. Low = cheap (buy). High = expensive (sell/spread).' },
              { n: 'Directional Conviction', w: ow.directional, d: 'RSI, SMA alignment, volume. Strong = clear call/put bias.' },
              { n: 'Technical Setup', w: ow.technical, d: 'BB squeeze + RSI extremes. Breakout or mean-reversion signals.' },
              { n: 'Liquidity', w: ow.liquidity, d: 'Market cap and options volume. Better liquidity = tighter fills.' },
              { n: 'Asymmetry', w: ow.asymmetry, d: 'Short squeeze, high beta, whale flow. Outsized move potential.' },
            ].map(c => (
              <div key={c.n} className={styles.componentCard}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 4 }}>
                  <span style={{ fontSize: 12, fontWeight: 700 }}>{c.n}</span>
                  <span className={styles.componentPts}>{c.w}pts</span>
                </div>
                <div style={{ fontSize: 11, color: 'var(--color-text-secondary)', lineHeight: 1.5 }}>{c.d}</div>
              </div>
            ))}
          </div>
        </Card>
      </div>
    );
  } else if (!data) {
    detail = (
      <Card style={{ padding: 40, textAlign: 'center' }}>
        <div className="pulse" style={{ fontSize: 24, marginBottom: 12 }}>{'⟳'}</div>
        <div style={{ fontSize: 14, color: 'var(--color-text-secondary)', fontWeight: 500, marginBottom: 8 }}>Forging plays for {sel}</div>
        <div style={{ fontSize: 12, color: 'var(--color-text-tertiary)' }}>{msg}</div>
      </Card>
    );
  } else if (data.error && (!data.plays || !data.plays.length)) {
    detail = (
      <Card style={{ padding: 24 }}>
        <h2 style={{ fontSize: 18, fontWeight: 700 }}>{sel}</h2>
        {data.price && <div style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-mono)', margin: '8px 0' }}>${data.price}</div>}
        <div className={styles.errorBanner}>{'⚠'} {data.error}</div>
      </Card>
    );
  } else {
    const p = data;
    const playsRC = (p.plays || []).map(pl => {
      const rc = getRC(pl);
      return { ...pl, _rc: rc, _verdict: rcVerdict(rc), _breakdown: rcBreakdown(pl) };
    });
    // Sort plays by user selection
    if (playSort === 'rc') playsRC.sort((a, b) => b._rc - a._rc);
    else if (playSort === 'rr') playsRC.sort((a, b) => (b.risk_reward_ratio || 0) - (a.risk_reward_ratio || 0));
    else if (playSort === 'gain') playsRC.sort((a, b) => {
      const gA = typeof a.max_gain === 'string' ? parseFloat(a.max_gain.replace(/[$,]/g, '')) || 999999 : a.max_gain;
      const gB = typeof b.max_gain === 'string' ? parseFloat(b.max_gain.replace(/[$,]/g, '')) || 999999 : b.max_gain;
      return gB - gA;
    });
    else if (playSort === 'volume') playsRC.sort((a, b) => (b.volume || 0) - (a.volume || 0));

    detail = (
      <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Header */}
        <Card style={{ padding: 20 }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 8 }}>
            <div>
              <h2 style={{ fontSize: 18, fontWeight: 700 }}>{p.ticker} Options Intelligence</h2>
              <p style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>{playsRC.length} play{playsRC.length !== 1 ? 's' : ''} &middot; sorted by reality check</p>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontSize: 26, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>${p.price}</div>
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, justifyContent: 'flex-end', marginTop: 4 }}>
                {fetchedAt && (
                  <span style={{ fontSize: 10, fontWeight: 600, color: (Date.now() - fetchedAt) < 30000 ? 'var(--color-success)' : (Date.now() - fetchedAt) < 90000 ? 'var(--color-warning)' : 'var(--color-danger)' }}>
                    {(Date.now() - fetchedAt) < 10000 ? '● Live' : (Date.now() - fetchedAt) < 60000 ? Math.round((Date.now() - fetchedAt) / 1000) + 's ago' : Math.round((Date.now() - fetchedAt) / 60000) + 'm ago'}
                  </span>
                )}
                <button className={styles.refreshBtn} onClick={e => { e.stopPropagation(); loadPlays(sel, true); }}>
                  {'🔄'} Refresh
                </button>
              </div>
            </div>
          </div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(100px, 1fr))', gap: 10, marginTop: 14 }}>
            <Metric label="RSI" value={p.rsi != null ? Math.round(p.rsi) : '—'} color={p.rsi < 30 ? 'var(--color-success)' : p.rsi > 70 ? 'var(--color-danger)' : 'var(--color-warning)'} sub={p.rsi < 30 ? 'Oversold' : p.rsi > 70 ? 'Overbought' : 'Neutral'} />
            <Metric label="IV 30d" value={p.iv_30d != null ? p.iv_30d + '%' : '—'} color={p.iv_30d > 50 ? 'var(--color-danger)' : 'var(--color-warning)'} />
            <Metric label="Earnings" value={p.days_to_earnings != null ? p.days_to_earnings + 'd' : '—'} color={p.days_to_earnings != null && p.days_to_earnings <= 14 ? 'var(--color-success)' : 'var(--color-text-secondary)'} />
            <Metric label="Beta" value={p.beta != null ? Number(p.beta).toFixed(1) : '—'} />
            <Metric label="Vol Ratio" value={p.vol_ratio != null ? p.vol_ratio + 'x' : '—'} />
          </div>
        </Card>

        {/* Play sort controls */}
        {playsRC.length > 1 && (
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '0 4px' }}>
            <span style={{ fontSize: 11, color: 'var(--color-text-secondary)', fontWeight: 600 }}>
              {playsRC.length} plays — sort by:
            </span>
            {[
              { key: 'rc', label: 'Reality Check' },
              { key: 'rr', label: 'R/R Ratio' },
              { key: 'gain', label: 'Max Gain' },
              { key: 'volume', label: 'Volume' },
            ].map(s => (
              <button
                key={s.key}
                onClick={() => setPlaySort(s.key)}
                style={{
                  padding: '3px 8px', borderRadius: 4, fontSize: 10, fontWeight: 600,
                  cursor: 'pointer', border: 'none',
                  background: playSort === s.key ? 'var(--imperial-purple-glow)' : 'transparent',
                  color: playSort === s.key ? 'var(--imperial-purple)' : 'var(--color-text-tertiary)',
                }}
              >
                {s.label}
              </button>
            ))}
          </div>
        )}

        {/* Play cards */}
        {playsRC.length > 0 ? playsRC.map((pl, i) => {
          const dC = pl.direction?.includes('Bullish') ? 'var(--color-success)' : pl.direction?.includes('Bearish') ? 'var(--color-danger)' : 'var(--imperial-purple)';
          const rcScore = pl._rc;
          const verdict = pl._verdict;

          return (
            <Card key={i} style={{ borderLeft: `3px solid ${dC}`, padding: 0, overflow: 'hidden' }}>
              {/* Play header */}
              <div className={styles.playHeader}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                  <span style={{ fontSize: 20 }}>{pl.emoji}</span>
                  <div>
                    <div style={{ fontSize: 15, fontWeight: 700 }}>{pl.strategy}</div>
                    <Badge color={dC}>{pl.direction}</Badge>
                  </div>
                </div>
                <div style={{ textAlign: 'right' }}>
                  <div style={{ fontSize: 14, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>{pl.action}</div>
                  <div style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>Exp: {fmtExpiry(pl.expiry)} ({pl.dte}d)</div>
                </div>
              </div>

              {/* RC score bar with breakdown tooltip */}
              <div className={styles.rcBar} style={{ background: verdict.color + '08', borderBottom: `1px solid ${verdict.color}20`, position: 'relative' }}>
                <div className={styles.rcBadge} style={{ background: verdict.color + '15', color: verdict.color }}>{rcScore}</div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ fontSize: 12, fontWeight: 700, color: verdict.color }}>{verdict.label}</div>
                    <div style={{ fontSize: 10, color: 'var(--color-text-secondary)' }}>Reality Check</div>
                  </div>
                  {/* RC component mini-bars */}
                  {pl._breakdown && pl._breakdown.length > 0 && (
                    <div style={{ display: 'flex', gap: 2, marginTop: 6 }}>
                      {pl._breakdown.map((comp, ci) => (
                        <div key={ci} title={`${comp.name}: ${comp.points}/${comp.max} — ${comp.detail}`}
                          style={{ flex: comp.max, height: 4, borderRadius: 2, background: 'var(--color-bg)', overflow: 'hidden' }}>
                          <div style={{
                            width: `${comp.max > 0 ? (comp.points / comp.max) * 100 : 0}%`,
                            height: '100%', borderRadius: 2,
                            background: comp.pct >= 70 ? 'var(--color-success)' : comp.pct >= 40 ? 'var(--color-warning)' : 'var(--color-danger)',
                          }} />
                        </div>
                      ))}
                    </div>
                  )}
                </div>
                {/* R/R ratio badge */}
                {pl.risk_reward_ratio > 0 && (
                  <div style={{ fontSize: 11, fontWeight: 600, color: pl.risk_reward_ratio >= 2 ? 'var(--color-success)' : pl.risk_reward_ratio >= 1 ? 'var(--color-warning)' : 'var(--color-text-tertiary)', fontFamily: 'var(--font-mono)' }}>
                    {pl.risk_reward_ratio.toFixed(1)}:1 R/R
                  </div>
                )}
              </div>

              {/* Metrics grid */}
              <div className={styles.playMetrics}>
                <MiniMetric label="Entry" value={`$${pl.entry_price}`} />
                <MiniMetric label="Breakeven" value={typeof pl.breakeven === 'number' ? `$${pl.breakeven}` : pl.breakeven} />
                <MiniMetric label="To BE" value={`${pl.pct_to_breakeven}%`} color={Math.abs(pl.pct_to_breakeven) < 5 ? 'var(--color-success)' : 'var(--color-warning)'} />
                <MiniMetric label="Max Loss" value={`$${Number(pl.max_loss).toLocaleString()}`} color="var(--color-danger)" />
                <MiniMetric label="Max Gain" value={pl.max_gain} color="var(--color-success)" />
                {pl.bid != null && <MiniMetric label="Bid/Ask" value={`$${pl.bid} / $${pl.ask}`} />}
                {pl.bid_ask_spread_pct != null && <MiniMetric label="Spread" value={`${pl.bid_ask_spread_pct}%`} color={pl.bid_ask_spread_pct < 5 ? 'var(--color-success)' : pl.bid_ask_spread_pct < 15 ? 'var(--color-warning)' : 'var(--color-danger)'} />}
                <MiniMetric label="IV" value={`${pl.iv}%`} color={pl.iv > 60 ? 'var(--color-danger)' : 'var(--color-warning)'} />
                <MiniMetric label="Volume" value={Number(pl.volume).toLocaleString()} />
                <MiniMetric label="Open Int" value={Number(pl.open_interest).toLocaleString()} />
              </div>

              {/* Rationale */}
              <div className={styles.rationale}>
                <div className={styles.sectionLabel}>Rationale</div>
                <div style={{ fontSize: 12, color: 'var(--color-text)', lineHeight: 1.6 }}>{pl.rationale}</div>
              </div>

              {/* Risk notes */}
              <div className={styles.riskNotes}>{'⚠'} {pl.risk_notes}</div>
            </Card>
          );
        }) : (
          <Card style={{ padding: 24, textAlign: 'center' }}>
            <div style={{ fontSize: 13, color: 'var(--color-text-secondary)' }}>No plays — no earnings catalyst, low IV, or insufficient directional bias.</div>
          </Card>
        )}

        {/* AI Analysis Panel */}
        {playsRC.length > 0 && (
          <Card style={{ padding: 20 }}>
            {!aiAnalysis && !aiLoading && (
              <button
                onClick={async () => {
                  setAiLoading(true);
                  setAiAnalysis(null);
                  const result = await analyzePlaysTicker(sel);
                  setAiAnalysis(result);
                  setAiLoading(false);
                }}
                style={{
                  width: '100%', padding: '12px 16px', borderRadius: 8,
                  background: 'var(--imperial-purple-glow)', border: '1px solid var(--imperial-purple)',
                  color: 'var(--imperial-purple)', cursor: 'pointer', fontSize: 13,
                  fontWeight: 700, fontFamily: 'inherit',
                  display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 8,
                }}
              >
                {'🧠'} Analyze with AI
              </button>
            )}
            {aiLoading && (
              <div style={{ textAlign: 'center', padding: 16 }}>
                <div className="pulse" style={{ fontSize: 18, marginBottom: 8 }}>{'🧠'}</div>
                <div style={{ fontSize: 12, color: 'var(--color-text-secondary)' }}>Analyzing plays with Claude...</div>
              </div>
            )}
            {aiAnalysis && !aiAnalysis.error && (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 14 }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
                  <h3 style={{ fontSize: 14, fontWeight: 700, margin: 0 }}>{'🧠'} AI Analysis</h3>
                  {aiAnalysis.cached && <Badge color="var(--color-text-tertiary)">cached</Badge>}
                </div>

                {/* Market context */}
                {aiAnalysis.context && (
                  <div style={{ fontSize: 12, color: 'var(--color-text)', lineHeight: 1.6, padding: '10px 14px', background: 'var(--color-bg)', borderRadius: 8, borderLeft: '3px solid var(--imperial-purple)' }}>
                    {aiAnalysis.context}
                  </div>
                )}

                {/* Per-play ratings */}
                {aiAnalysis.plays?.length > 0 && (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                    {aiAnalysis.plays.map((ap, i) => (
                      <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '8px 12px', background: 'var(--color-bg)', borderRadius: 6 }}>
                        <div style={{
                          width: 28, height: 28, borderRadius: '50%', display: 'flex', alignItems: 'center', justifyContent: 'center',
                          fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-mono)',
                          background: ap.confidence >= 4 ? 'var(--color-success-bg)' : ap.confidence >= 3 ? 'var(--color-warning-bg)' : 'var(--color-bg)',
                          color: ap.confidence >= 4 ? 'var(--color-success)' : ap.confidence >= 3 ? 'var(--color-warning)' : 'var(--color-text-tertiary)',
                          border: `1px solid ${ap.confidence >= 4 ? 'var(--color-success)' : ap.confidence >= 3 ? 'var(--color-warning)' : 'var(--color-border-subtle)'}`,
                        }}>
                          {ap.confidence}
                        </div>
                        <div style={{ flex: 1 }}>
                          <div style={{ fontSize: 11, fontWeight: 700 }}>{ap.strategy}</div>
                          <div style={{ fontSize: 10, color: 'var(--color-text-secondary)', lineHeight: 1.4 }}>{ap.risk}</div>
                        </div>
                        <Badge color={ap.take_it ? 'var(--color-success)' : 'var(--color-danger)'}>
                          {ap.take_it ? 'TAKE' : 'SKIP'}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}

                {/* Top pick */}
                {aiAnalysis.top_pick && (
                  <div style={{ padding: '10px 14px', background: 'var(--color-success-bg)', borderRadius: 8, borderLeft: '3px solid var(--color-success)' }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-success)', marginBottom: 4 }}>TOP PICK</div>
                    <div style={{ fontSize: 12, color: 'var(--color-text)', lineHeight: 1.5 }}>{aiAnalysis.top_pick}</div>
                  </div>
                )}

                {/* Blind spot */}
                {aiAnalysis.blind_spot && (
                  <div style={{ padding: '10px 14px', background: 'var(--color-warning-bg)', borderRadius: 8, borderLeft: '3px solid var(--color-warning)' }}>
                    <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--color-warning)', marginBottom: 4 }}>{'⚠'} BLIND SPOT</div>
                    <div style={{ fontSize: 12, color: 'var(--color-text)', lineHeight: 1.5 }}>{aiAnalysis.blind_spot}</div>
                  </div>
                )}

                <button
                  onClick={() => setAiAnalysis(null)}
                  style={{ fontSize: 10, color: 'var(--color-text-tertiary)', background: 'none', border: 'none', cursor: 'pointer', textAlign: 'right' }}
                >
                  Dismiss
                </button>
              </div>
            )}
            {aiAnalysis?.error && (
              <div style={{ padding: 12, fontSize: 12, color: 'var(--color-text-secondary)' }}>
                {'⚠'} {aiAnalysis.error}
              </div>
            )}
          </Card>
        )}
      </div>
    );
  }

  return (
    <div className={`fade-in ${styles.layout}`}>
      {/* ── Sidebar ── */}
      <div className={styles.sidebar}>
        {/* Weight tuner toggle */}
        <button className={`${styles.tunerBtn} ${showW ? styles.tunerActive : ''}`} onClick={() => setShowW(!showW)}>
          {'⚙'} Weight Tuner <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)' }}>{showW ? '▼' : '▶'}</span>
        </button>

        {showW && (
          <Card style={{ padding: 16 }}>
            <div className={styles.sectionLabel}>Opt Score Weights</div>
            <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginBottom: 12 }}>Adjust factor contributions. Total &asymp; 100.</div>
            {[
              ['Earnings', ow.earnings_catalyst, v => setOw(p => ({ ...p, earnings_catalyst: v }))],
              ['IV Context', ow.iv_context, v => setOw(p => ({ ...p, iv_context: v }))],
              ['Directional', ow.directional, v => setOw(p => ({ ...p, directional: v }))],
              ['Technical', ow.technical, v => setOw(p => ({ ...p, technical: v }))],
              ['Liquidity', ow.liquidity, v => setOw(p => ({ ...p, liquidity: v }))],
              ['Asymmetry', ow.asymmetry, v => setOw(p => ({ ...p, asymmetry: v }))],
            ].map(([l, v, fn]) => (
              <div key={l} className={styles.sliderRow}>
                <span className={styles.sliderLabel}>{l}</span>
                <input type="range" min={0} max={40} step={1} value={v} onChange={e => fn(parseInt(e.target.value))} style={{ flex: 1 }} />
                <span className={styles.sliderVal}>{v}</span>
              </div>
            ))}
            <div className={styles.tunerFooter}>
              <span style={{ color: wt === 100 ? 'var(--color-success)' : wt > 100 ? 'var(--color-danger)' : 'var(--color-warning)' }}>
                Total: {wt}/100
              </span>
              <div style={{ display: 'flex', gap: 6 }}>
                <button className={styles.tunerAction} onClick={() => setOw({ earnings_catalyst: 25, iv_context: 20, directional: 20, technical: 15, liquidity: 10, asymmetry: 10 })}>Reset</button>
                <button className={styles.tunerApply} onClick={() => updateWeights({ opt: ow })}>Apply</button>
              </div>
            </div>
          </Card>
        )}

        {/* Sort + Ticker list */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '4px 0', marginBottom: 4 }}>
          <span style={{ fontSize: 10, color: 'var(--color-text-tertiary)' }}>Sort:</span>
          <select
            value={anvilSort}
            onChange={e => setAnvilSort(e.target.value)}
            style={{
              flex: 1, background: 'var(--color-bg)', border: '1px solid var(--color-border-subtle)',
              borderRadius: 6, color: 'var(--color-text)', fontSize: 10, padding: '4px 8px',
              fontFamily: 'var(--font-mono)', cursor: 'pointer', outline: 'none',
            }}
          >
            {ANVIL_SORT_OPTIONS.map(s => (
              <option key={s.key} value={s.key}>{s.label}</option>
            ))}
          </select>
        </div>
        <Card style={{ padding: 12, maxHeight: showW ? '40vh' : '60vh', overflowY: 'auto' }}>
          <div className={styles.sectionLabel} style={{ padding: '4px 8px', marginBottom: 4 }}>{opts.length} tickers</div>
          {opts.map(r => (
            <div
              key={r.ticker}
              onClick={() => loadPlays(r.ticker)}
              className={`${styles.tickerRow} ${sel === r.ticker ? styles.tickerSelected : ''}`}
            >
              <span className={styles.tickerSymbol}>{r.ticker}</span>
              <span className={styles.tickerPrice}>${r.price}</span>
              <Badge color={r.opt_score >= 40 ? 'var(--color-success)' : r.opt_score >= 25 ? 'var(--color-warning)' : 'var(--color-text-tertiary)'}>
                {r.opt_score}
              </Badge>
            </div>
          ))}
        </Card>
      </div>

      {/* ── Detail ── */}
      <div style={{ flex: 1, minWidth: 0 }}>{detail}</div>
    </div>
  );
}
