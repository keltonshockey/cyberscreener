/**
 * QUAEST.TECH — The Archive (Research/Backtest Tab)
 * Model health, quintile analysis, layer attribution, earnings timing,
 * weight history, calibration, watchlist, intel.
 */

import { useState, useEffect, useCallback } from 'react';
import { Card } from '../components/ui/Card';
import { Metric } from '../components/ui/Metric';
import { Badge } from '../components/ui/Badge';
import { SvgBarChart } from '../components/charts/SvgBarChart';
import { SvgGroupedBarChart } from '../components/charts/SvgGroupedBarChart';
import { SvgHorizBarChart } from '../components/charts/SvgHorizBarChart';
import { SvgAreaChart } from '../components/charts/SvgAreaChart';
import { fetchBacktest, runCalibrate, fetchWeightsHistory } from '../api/endpoints';
import { useAuth } from '../auth/AuthContext';
import styles from './ArchivePage.module.css';

export function ArchivePage({ backtest: init, tz }) {
  const { isAdmin } = useAuth();
  const [period, setPeriod] = useState(30);
  const [data, setData] = useState(init);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(false);
  const [retries, setRetries] = useState(0);
  const [wtHist, setWtHist] = useState(null);
  const [calRunning, setCalRunning] = useState(false);
  const [calMsg, setCalMsg] = useState('');

  const MAX_RETRIES = 6; // ~3 minutes of polling (6 × 30s)

  const loadBT = useCallback(async (fwd, attempt = 0) => {
    setLoading(true);
    setError(false);
    const d = await fetchBacktest(60, fwd);
    if (d && d.status === 'computing') {
      setLoading(false);
      setRetries(attempt + 1);
      if (attempt < MAX_RETRIES) {
        setError('computing');
        setTimeout(() => loadBT(fwd, attempt + 1), 30000);
      } else {
        setError('timeout');
      }
      return;
    }
    if (d && d.status === 'error') {
      setError('failed');
      setLoading(false);
      return;
    }
    if (d) setData(d);
    else setError(true);
    setLoading(false);
  }, []);

  const loadWH = useCallback(async () => {
    const d = await fetchWeightsHistory(30);
    if (d) setWtHist(d);
  }, []);

  useEffect(() => {
    if (!data) loadBT(period, 0);
    loadWH();
  }, []);

  const handleCalibrate = async () => {
    setCalRunning(true);
    setCalMsg('Calibrating weights…');
    const d = await runCalibrate(false);
    setCalRunning(false);
    if (d && d.status === 'calibrated') {
      setCalMsg('✓ Weights updated');
      loadWH();
    } else {
      setCalMsg(d?.message || 'Insufficient data');
    }
  };

  const retryBtn = (
    <button onClick={() => { setRetries(0); loadBT(period, 0); }} style={{ padding: '6px 16px', borderRadius: 6, border: '1px solid var(--color-border)', background: 'var(--color-bg)', cursor: 'pointer', fontSize: 13, fontWeight: 600 }}>
      ↻ Retry
    </button>
  );

  if (loading) return <div className={styles.loading}>Running backtest…</div>;
  if (!data) return (
    <Card style={{ padding: 40, textAlign: 'center' }}>
      <div style={{ fontSize: 36, marginBottom: 12 }}>
        {error === 'computing' ? '⏳' : error ? '⚠️' : '📊'}
      </div>
      <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 8 }}>
        {error === 'computing' && 'Backtest computing in background…'}
        {error === 'timeout' && 'Still computing — taking longer than usual'}
        {error === 'failed' && 'Backtest computation failed'}
        {error === true && 'Backtest unavailable — server may be busy'}
        {!error && 'Loading backtest…'}
      </div>
      {error === 'computing' && (
        <div style={{ fontSize: 13, color: 'var(--color-text-secondary)', marginBottom: 12 }}>
          First run takes 60–90 seconds. Auto-refreshing… ({retries}/{MAX_RETRIES})
        </div>
      )}
      {(error === 'timeout' || error === 'failed' || error === true) && retryBtn}
    </Card>
  );

  const sd = data.score_vs_returns || {};
  const ld = data.layer_attribution || {};
  const ed = data.earnings_timing || {};
  const ltA = sd.lt_analysis || {};
  const optA = sd.opt_analysis || {};
  const ltCorr = ltA.correlation;
  const optCorr = optA.correlation;
  const qs = ltA.quintile_spread;
  const obs = ltA.data_points || 0;

  const modelHealth = (ltCorr > 0.15 && qs > 2) ? 'Strong' : (ltCorr > 0.05 || qs > 1) ? 'Moderate' : 'Weak';
  const modelCol = modelHealth === 'Strong' ? 'var(--color-success)' : modelHealth === 'Moderate' ? 'var(--color-warning)' : 'var(--color-danger)';

  // Quintile data
  const qc = [];
  if (ltA.status === 'ok' && ltA.quintiles) {
    Object.entries(ltA.quintiles).forEach(([l, s]) => {
      qc.push({ name: l, return: s.avg_return, winRate: s.win_rate, count: s.count });
    });
  }
  const q1ret = qc.find(q => q.name === 'Q1')?.return || 0;
  const q5ret = qc.find(q => q.name === 'Q5')?.return || 0;
  const spread = q5ret - q1ret;

  // Layer attribution
  const compLabels = { lt_rule_of_40: 'Rule of 40', lt_valuation: 'Valuation', lt_fcf_margin: 'FCF Margin', lt_trend: 'Trend', lt_earnings_quality: 'Earn. Quality', lt_discount_momentum: 'Disc. Mom.' };
  const lc = [];
  if (ld.lt_component_attribution) {
    Object.entries(ld.lt_component_attribution).forEach(([k, v]) => {
      if (v.correlation != null) lc.push({ name: compLabels[k] || k, alpha: v.correlation, alpha_pct: v.correlation * 100 });
    });
  }
  lc.sort((a, b) => b.alpha - a.alpha);

  // Earnings timing
  const ec = [];
  if (ed.forward_14d && ed.forward_30d) {
    Object.entries(ed.forward_14d).forEach(([label, v14]) => {
      const v30 = ed.forward_30d[label] || {};
      if ((v14.count || 0) > 0 || (v30.count || 0) > 0) {
        ec.push({ name: label, return14d: v14.avg_return || 0, return30d: v30.avg_return || 0, count: v14.count || 0 });
      }
    });
  }
  const bestWindow = ec.length > 0 ? ec.reduce((a, b) => a.return14d > b.return14d ? a : b).name : '—';

  // Weight history
  const WH = wtHist?.history || [];
  const ltHist = WH.filter(w => w.score_type === 'lt').slice(0, 10);

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Model health header */}
      <Card style={{ padding: 20 }}>
        <div className={styles.healthHeader}>
          <div>
            <h2 style={{ fontSize: 17, fontWeight: 700, margin: 0 }}>Model Health</h2>
            <p style={{ fontSize: 12, color: 'var(--color-text-secondary)', margin: '4px 0 0' }}>180-day lookback &middot; {obs} observations</p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
            <span className={styles.healthBadge} style={{ background: modelCol + '18', color: modelCol, border: `1px solid ${modelCol}40` }}>
              {modelHealth} Signal
            </span>
            {isAdmin && (
              <button className={styles.calibrateBtn} onClick={handleCalibrate} disabled={calRunning}>
                {calRunning ? 'Calibrating…' : '⚙ Auto-Calibrate'}
              </button>
            )}
            {calMsg && <span style={{ fontSize: 11, color: 'var(--color-text-secondary)' }}>{calMsg}</span>}
          </div>
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 12, marginTop: 16 }}>
          <Metric
            label="LT Correlation"
            value={ltCorr != null ? ltCorr.toFixed(3) : '—'}
            color={ltCorr > 0.15 ? 'var(--color-success)' : ltCorr > 0.05 ? 'var(--color-warning)' : 'var(--color-danger)'}
            sub={ltCorr > 0.15 ? 'Strong predictive' : ltCorr > 0.05 ? 'Moderate signal' : 'Weak signal'}
          />
          <Metric
            label={'Q5 − Q1 Spread'}
            value={spread != null ? spread.toFixed(1) + '%' : '—'}
            color={spread > 3 ? 'var(--color-success)' : spread > 1 ? 'var(--color-warning)' : 'var(--color-danger)'}
            sub={spread > 3 ? 'Top scores beat bottom >3%' : 'Moderate separation'}
          />
          <Metric
            label="Opt Correlation"
            value={optCorr != null ? optCorr.toFixed(3) : '—'}
            color={optCorr > 0.1 ? 'var(--color-success)' : 'var(--color-warning)'}
            sub={`Options vs ${period}d return`}
          />
          <Metric label="Best Window" value={bestWindow} color="var(--imperial-purple)" sub="Days-to-earnings timing" />
        </div>
      </Card>

      {/* Forward period selector */}
      <div className={styles.periodSelector}>
        <span style={{ fontSize: 12, color: 'var(--color-text-secondary)', fontWeight: 600 }}>Forward return window:</span>
        {[14, 30, 60].map(p => (
          <button
            key={p}
            onClick={() => { setPeriod(p); loadBT(p); }}
            className={`${styles.periodBtn} ${period === p ? styles.periodActive : ''}`}
          >
            {p}d
          </button>
        ))}
        <span style={{ fontSize: 11, color: 'var(--color-text-tertiary)', marginLeft: 'auto', fontFamily: 'var(--font-mono)' }}>{obs} observations</span>
      </div>

      {/* Quintile chart */}
      {qc.length > 0 && (
        <Card style={{ padding: 20 }}>
          <h2 className={styles.sectionTitle}>Quintile Analysis &mdash; Does score predict returns?</h2>
          <SvgGroupedBarChart
            data={qc}
            bars={[
              { key: 'return', name: `Avg ${period}d Return`, color: 'var(--imperial-purple)' },
              { key: 'winRate', name: 'Win Rate %', color: 'var(--color-success)' },
            ]}
            labelKey="name"
            height={240}
          />
        </Card>
      )}

      {/* Layer attribution */}
      {lc.length > 0 && (
        <Card style={{ padding: 20 }}>
          <h2 className={styles.sectionTitle}>Component Attribution &mdash; Which factors drive alpha?</h2>
          <SvgHorizBarChart data={lc} dataKey="alpha_pct" labelKey="name" height={180} />
        </Card>
      )}

      {/* Earnings timing */}
      {ec.length > 0 && (
        <Card style={{ padding: 20 }}>
          <h2 className={styles.sectionTitle}>Earnings Timing &mdash; When is entry optimal?</h2>
          <SvgGroupedBarChart
            data={ec}
            bars={[
              { key: 'return14d', name: '14d Return', color: 'var(--imperial-purple)' },
              { key: 'return30d', name: '30d Return', color: 'var(--color-success)' },
            ]}
            labelKey="name"
            height={220}
          />
        </Card>
      )}

      {/* Weight history */}
      {ltHist.length > 0 && (
        <Card style={{ padding: 20 }}>
          <h2 className={styles.sectionTitle}>Weight Calibration History</h2>
          <div style={{ overflowX: 'auto' }}>
            <table className={styles.whTable}>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Rule of 40</th>
                  <th>Valuation</th>
                  <th>FCF</th>
                  <th>Trend</th>
                  <th>Earnings Q</th>
                  <th>Disc. Mom</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {ltHist.map((w, i) => (
                  <tr key={i} style={{ background: i % 2 === 0 ? 'var(--color-bg)' : 'transparent' }}>
                    <td style={{ color: 'var(--color-text-tertiary)' }}>{w.timestamp?.slice(0, 10)}</td>
                    <td>{w.weights?.rule_of_40}</td>
                    <td>{w.weights?.valuation}</td>
                    <td>{w.weights?.fcf_margin}</td>
                    <td>{w.weights?.trend}</td>
                    <td>{w.weights?.earnings_quality}</td>
                    <td>{w.weights?.discount_momentum}</td>
                    <td><Badge color="var(--imperial-purple)" variant="soft">{w.source || 'manual'}</Badge></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Card>
      )}
    </div>
  );
}
