/**
 * QUAEST.TECH — Ticker Summary Page
 * Combined view of LT score, Options score, key metrics, score history,
 * and quick access to play generation for any ticker.
 */

import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Metric } from '../components/ui/Metric';
import { ScoreBar } from '../components/ui/ScoreBar';
import { Badge } from '../components/ui/Badge';
import { Explain } from '../components/ui/Explain';
import { Scale, Scroll, Ruler, Zap, LineChart, Activity, Landmark } from '../components/ui/icons';
import { SvgBarChart } from '../components/charts/SvgBarChart';
import { fetchScoreHistory, fetchSignals, fetchChart, fetchNarrative } from '../api/endpoints';
import { ltBreakdown, optBreakdown } from '../utils/scoring';
import { fmtTS, fmtDateOnly } from '../utils/formatters';
import styles from './TickerPage.module.css';

function ScoreBreakdownCard({ title, term, Icon, score, breakdown }) {
  if (!breakdown || !breakdown.length) return null;
  const color = score >= 60 ? 'var(--color-success)' : score >= 35 ? 'var(--color-warning)' : 'var(--color-danger)';
  return (
    <Card style={{ padding: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, margin: 0, display: 'inline-flex', alignItems: 'center', gap: 8 }}>{Icon && <Icon size={15} />} {title}{term && <Explain term={term} />}</h3>
        <div style={{ fontSize: 22, fontWeight: 800, fontFamily: 'var(--font-mono)', color }}>{Math.round(score)}</div>
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {breakdown.map((comp, i) => {
          const pct = comp.max > 0 ? (comp.points / comp.max) * 100 : 0;
          const barColor = pct >= 70 ? 'var(--color-success)' : pct >= 40 ? 'var(--color-warning)' : 'var(--color-danger)';
          return (
            <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <div style={{ minWidth: 90 }}>
                <span style={{ fontSize: 11, fontWeight: 600, display: 'inline-flex', alignItems: 'center', gap: 5 }}>{comp.Icon && <comp.Icon size={12} />} {comp.name}</span>
              </div>
              <div style={{ flex: 1, height: 8, borderRadius: 4, background: 'var(--color-border-subtle)', overflow: 'hidden' }}>
                <div style={{ width: `${pct}%`, height: '100%', borderRadius: 4, background: barColor, transition: 'width 0.3s' }} />
              </div>
              <span style={{ fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-mono)', color: barColor, minWidth: 40, textAlign: 'right' }}>
                {comp.points}/{comp.max}
              </span>
            </div>
          );
        })}
      </div>
    </Card>
  );
}

function MiniChart({ data, dataKey, labelKey, height, title }) {
  if (!data || !data.length) return null;
  return (
    <Card style={{ padding: 20 }}>
      <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>{title}</h3>
      <SvgBarChart data={data} dataKey={dataKey} labelKey={labelKey} height={height} />
    </Card>
  );
}

function StorySection({ title, term, Icon, text, generatedAt, tz }) {
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        {Icon && <Icon size={13} />}
        <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 0.4, textTransform: 'uppercase', color: 'var(--color-text-secondary)' }}>{title}</span>
        {term && <Explain term={term} />}
      </div>
      <p style={{ fontSize: 13, lineHeight: 1.6, margin: 0, color: 'var(--color-text-primary)' }}>
        {text || <span style={{ color: 'var(--color-text-tertiary)' }}>No story yet.</span>}
      </p>
      {generatedAt && (
        <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 6 }}>
          as of {fmtDateOnly(generatedAt, tz)}
        </div>
      )}
    </div>
  );
}

function StoryPanel({ narrative, tz }) {
  // Nothing fetched yet (initial mount) — render nothing rather than a flash.
  if (!narrative) return null;

  // 202 from the API: the mill pipeline hasn't drafted this ticker yet.
  if (narrative.status === 'generating') {
    return (
      <Card style={{ padding: 20 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, margin: '0 0 10px', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <Scroll size={15} /> Story
        </h3>
        <p style={{ fontSize: 12, color: 'var(--color-text-tertiary)', margin: 0 }}>
          Generating narrative… check back shortly.
        </p>
      </Card>
    );
  }

  const sources = narrative.sources || [];
  const lowConfidence = narrative.confidence && narrative.confidence !== 'ok';
  const fresh = !narrative.stale;
  const dotColor = fresh ? 'var(--color-success)' : 'var(--color-warning)';

  return (
    <Card style={{ padding: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, margin: 0, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <Scroll size={15} /> Story
        </h3>
        <span
          title={fresh ? 'Fresh' : 'Stale — refresh pending'}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 10, fontWeight: 600, color: 'var(--color-text-tertiary)' }}
        >
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: dotColor, display: 'inline-block' }} />
          {fresh ? 'Fresh' : 'Stale'}
        </span>
      </div>

      {lowConfidence && (
        <div style={{ fontSize: 11, color: 'var(--color-warning)', marginBottom: 12, padding: '6px 10px', borderRadius: 6, background: 'var(--color-bg)', borderLeft: '3px solid var(--color-warning)' }}>
          Low-confidence note — grounded on system signals only; external claims were withheld.
        </div>
      )}

      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        <StorySection title="Long-term" term="lt_score" Icon={Ruler} text={narrative.lt_story} generatedAt={narrative.lt_generated_at} tz={tz} />
        <StorySection title="Short-term" term="opt_score" Icon={Zap} text={narrative.st_story} generatedAt={narrative.st_generated_at} tz={tz} />
      </div>

      {sources.length > 0 && (
        <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--color-border-subtle)' }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.4, textTransform: 'uppercase', color: 'var(--color-text-tertiary)', marginBottom: 6 }}>Sources</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {sources.map((s, i) => (
              <a
                key={i}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ fontSize: 11, color: 'var(--imperial-purple-light, var(--imperial-purple))', textDecoration: 'none' }}
              >
                {s.title || s.url}
              </a>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

export function TickerPage({ latest, tz }) {
  const { symbol } = useParams();
  const navigate = useNavigate();
  const ticker = symbol?.toUpperCase();

  const [history, setHistory] = useState(null);
  const [signals, setSignals] = useState(null);
  const [chart, setChart] = useState(null);
  const [narrative, setNarrative] = useState(null);

  // Find this ticker in latest scores
  const res = latest?.results || [];
  const row = res.find(r => r.ticker === ticker);

  useEffect(() => {
    if (!ticker) return;
    fetchScoreHistory(ticker, 90).then(d => { if (d) setHistory(d); });
    fetchSignals(ticker, 20).then(d => { if (d) setSignals(d); });
    fetchChart(ticker, 90).then(d => { if (d) setChart(d); });
    // Story panel — single fetch per load (no polling storm). On 202 the API
    // returns { status: "generating" }; we render a quiet placeholder and it
    // resolves on the next visit once mill has drafted it.
    setNarrative(null);
    fetchNarrative(ticker).then(d => { if (d) setNarrative(d); });
  }, [ticker]);

  if (!ticker) {
    return <Card style={{ padding: 40, textAlign: 'center' }}>No ticker specified.</Card>;
  }

  // Score breakdowns from the latest row
  const ltBd = ltBreakdown(row);
  const optBd = optBreakdown(row);

  // Score history for chart
  const histPoints = (history?.history || []).slice(-30).map(h => ({
    date: h.timestamp?.slice(5, 10) || '',
    lt_score: h.lt_score || 0,
    opt_score: h.opt_score || 0,
  }));

  // Price chart data
  const pricePoints = (chart?.prices || []).slice(-60).map(p => ({
    date: p.date?.slice(5) || '',
    price: p.close || p.close_price || 0,
    rsi: p.rsi || 50,
  }));

  // Key metrics
  const price = row?.price;
  const ltScore = row?.lt_score ?? '—';
  const optScore = row?.opt_score ?? '—';
  const rsi = row?.rsi;
  const ivRank = row?.iv_rank ?? row?.iv_30d;
  const dte = row?.days_to_earnings;
  const sector = row?.sector;
  const beta = row?.beta;
  const pctFrom52w = row?.pct_from_52w_high;
  const bbWidth = row?.bb_width;
  const volRatio = row?.vol_ratio;

  // Recent signals
  const sigList = signals?.signals || signals?.results || [];

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
      {/* Header */}
      <Card style={{ padding: 20 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 4 }}>
              <h1 style={{ fontSize: 24, fontWeight: 800, fontFamily: 'var(--font-mono)', margin: 0 }}>{ticker}</h1>
              {sector && <Badge color="var(--imperial-purple)">{sector}</Badge>}
            </div>
            {price != null && (
              <div style={{ fontSize: 28, fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
                ${typeof price === 'number' ? price.toLocaleString('en-US', { maximumFractionDigits: 2 }) : price}
              </div>
            )}
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <button
              onClick={() => navigate('/pactum', { state: { ticker } })}
              className={styles.actionBtn}
            >
              <Zap size={14} style={{ verticalAlign: '-2px' }} /> View Plays
            </button>
            <button
              onClick={() => navigate('/conviction')}
              className={styles.actionBtnSecondary}
            >
              <Scroll size={14} style={{ verticalAlign: '-2px' }} /> Conviction
            </button>
          </div>
        </div>

        {/* Score summary */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 12, marginTop: 16 }}>
          <Metric label={<>LT Score <Explain term="lt_score" /></>} value={ltScore} color={ltScore >= 60 ? 'var(--color-success)' : ltScore >= 35 ? 'var(--color-warning)' : typeof ltScore === 'number' ? 'var(--color-danger)' : undefined} />
          <Metric label={<>Opt Score <Explain term="opt_score" /></>} value={optScore} color={optScore >= 50 ? 'var(--color-success)' : optScore >= 30 ? 'var(--color-warning)' : typeof optScore === 'number' ? 'var(--color-danger)' : undefined} />
          <Metric label={<>RSI <Explain term="rsi" /></>} value={rsi != null ? Math.round(rsi) : '—'} color={rsi < 30 ? 'var(--color-success)' : rsi > 70 ? 'var(--color-danger)' : 'var(--color-warning)'} sub={rsi < 30 ? 'Oversold' : rsi > 70 ? 'Overbought' : 'Neutral'} />
          <Metric label={<>IV Rank <Explain term="iv_rank" /></>} value={ivRank != null ? `${Math.round(ivRank)}%` : '—'} color={ivRank > 60 ? 'var(--color-danger)' : ivRank > 30 ? 'var(--color-warning)' : 'var(--color-success)'} />
          <Metric label="Earnings" value={dte != null ? `${dte}d` : '—'} color={dte != null && dte <= 14 ? 'var(--color-success)' : 'var(--color-text-secondary)'} />
          <Metric label="Beta" value={beta != null ? Number(beta).toFixed(1) : '—'} />
          {pctFrom52w != null && <Metric label="From 52w High" value={`${pctFrom52w > 0 ? '+' : ''}${Number(pctFrom52w).toFixed(1)}%`} color={pctFrom52w > -10 ? 'var(--color-success)' : 'var(--color-warning)'} />}
          {volRatio != null && <Metric label="Vol Ratio" value={`${volRatio}x`} color={volRatio > 1.5 ? 'var(--color-success)' : 'var(--color-text-secondary)'} />}
        </div>
      </Card>

      {/* Story panel — LT + ST narrative (read-only; from narratives.db) */}
      <StoryPanel narrative={narrative} tz={tz} />

      {/* Score breakdowns side by side */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
        <ScoreBreakdownCard title="Long-Term Score" term="lt_score" Icon={Ruler} score={row?.lt_score || 0} breakdown={ltBd} />
        <ScoreBreakdownCard title="Options Score" term="opt_score" Icon={Zap} score={row?.opt_score || 0} breakdown={optBd} />
      </div>

      {/* Price chart */}
      {pricePoints.length > 0 && (
        <Card style={{ padding: 20 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, display: 'inline-flex', alignItems: 'center', gap: 8 }}><LineChart size={15} /> Price History (90d)</h3>
          <SvgBarChart
            data={pricePoints}
            dataKey="price"
            labelKey="date"
            height={200}
            colorFn={(d) => 'var(--imperial-purple)'}
          />
        </Card>
      )}

      {/* Score history */}
      {histPoints.length > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
          <Card style={{ padding: 20 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>LT Score Trend</h3>
            <SvgBarChart
              data={histPoints}
              dataKey="lt_score"
              labelKey="date"
              height={160}
              colorFn={(d) => d.lt_score >= 60 ? 'var(--color-success)' : d.lt_score >= 35 ? 'var(--color-warning)' : 'var(--color-danger)'}
            />
          </Card>
          <Card style={{ padding: 20 }}>
            <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12 }}>Opt Score Trend</h3>
            <SvgBarChart
              data={histPoints}
              dataKey="opt_score"
              labelKey="date"
              height={160}
              colorFn={(d) => d.opt_score >= 50 ? 'var(--color-success)' : d.opt_score >= 30 ? 'var(--color-warning)' : 'var(--color-danger)'}
            />
          </Card>
        </div>
      )}

      {/* Recent signals */}
      {sigList.length > 0 && (
        <Card style={{ padding: 20 }}>
          <h3 style={{ fontSize: 14, fontWeight: 700, marginBottom: 12, display: 'inline-flex', alignItems: 'center', gap: 8 }}><Activity size={15} /> Recent Signals</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {sigList.slice(0, 10).map((s, i) => {
              const col = s.impact === 'positive' ? 'var(--color-success)' : s.impact === 'negative' ? 'var(--color-danger)' : 'var(--color-text-secondary)';
              return (
                <div key={i} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderRadius: 6, borderLeft: `3px solid ${col}30`, background: i % 2 === 0 ? 'var(--color-bg)' : 'transparent' }}>
                  <span style={{ fontSize: 11, fontWeight: 600, color: col, minWidth: 50 }}>{s.signal_type || s.type || ''}</span>
                  <span style={{ flex: 1, fontSize: 11, color: 'var(--color-text-secondary)' }}>{s.signal_text || s.text || ''}</span>
                  <span style={{ fontSize: 9, color: 'var(--color-text-tertiary)', whiteSpace: 'nowrap' }}>{s.scan_ts?.slice(5, 16) || ''}</span>
                </div>
              );
            })}
          </div>
        </Card>
      )}

      {/* Quick nav */}
      <div style={{ display: 'flex', justifyContent: 'center', gap: 12, padding: '8px 0' }}>
        <button onClick={() => navigate('/')} className={styles.navLink}><Landmark size={13} style={{ verticalAlign: '-2px' }} /> Basilica</button>
        <button onClick={() => navigate('/pactum', { state: { ticker } })} className={styles.navLink}><Zap size={13} style={{ verticalAlign: '-2px' }} /> Forge Plays</button>
        <button onClick={() => navigate('/conviction')} className={styles.navLink}><Scroll size={13} style={{ verticalAlign: '-2px' }} /> Conviction</button>
      </div>
    </div>
  );
}
