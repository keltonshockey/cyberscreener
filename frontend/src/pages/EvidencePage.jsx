/**
 * QUAEST.TECH - Evidence (SESSION-V3B-EVIDENCE)
 *
 * The system telling the truth about itself: the pre-registered forward-test
 * gate verdict and the weekly IC report, served verbatim from artifacts mill
 * delivers - including, as of this writing, a FAIL. The page is designed to
 * state that plainly; a scoring site that hides its own scoreboard is not
 * worth trusting.
 */

import { useState, useEffect } from 'react';
import { Card } from '../components/ui/Card';
import { Metric } from '../components/ui/Metric';
import { Badge } from '../components/ui/Badge';
import { Scale, FileText } from '../components/ui/icons';
import { fetchEvidenceLatest, fetchEvidenceHistory } from '../api/endpoints';
import styles from './EvidencePage.module.css';

const VERDICT_STYLE = {
  PASS: { color: 'var(--color-success)', word: 'PASS' },
  FAIL: { color: 'var(--color-danger)', word: 'FAIL' },
  NO_VERDICT: { color: 'var(--color-warning)', word: 'NO VERDICT' },
  UNKNOWN: { color: 'var(--color-text-tertiary)', word: 'UNKNOWN' },
};

const VERDICT_SUB = {
  PASS: 'The pre-registered pass bar was met at full statistical power.',
  FAIL: 'The pre-registered fail rule triggered: stop new feature work, re-architect signals. This page reports it because that is the deal.',
  NO_VERDICT: 'Not enough decided plays yet for either the pass bar or the fail rule. The test keeps running.',
  UNKNOWN: 'The latest gate artifact could not be parsed. The raw report is shown below, unedited.',
};

function fmt(v, digits = 3) {
  if (v === null || v === undefined) return '-';
  return typeof v === 'number' ? v.toFixed(digits) : String(v);
}

export function EvidencePage() {
  const [data, setData] = useState(null);
  const [history, setHistory] = useState(null);
  const [failed, setFailed] = useState(false);
  const [showGateRaw, setShowGateRaw] = useState(false);
  const [showIcRaw, setShowIcRaw] = useState(false);

  useEffect(() => {
    fetchEvidenceLatest().then(d => (d ? setData(d) : setFailed(true))).catch(() => setFailed(true));
    fetchEvidenceHistory().then(h => { if (h) setHistory(h); }).catch(() => {});
  }, []);

  if (failed) return <div className={styles.loading}>Evidence unavailable - the server did not answer.</div>;
  if (!data) return <div className={styles.loading}>Loading evidence...</div>;

  if (data.status === 'no_artifacts_yet') {
    return (
      <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
        <Card style={{ padding: 28 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
            <Scale size={18} />
            <h2 style={{ fontSize: 17, fontWeight: 700, margin: 0 }}>Evidence</h2>
          </div>
          <p className={styles.explainer}>
            No evidence artifacts have been delivered yet. When the weekly gate read and
            IC report land, they appear here verbatim - pass or fail.
          </p>
        </Card>
        <ExplainerCard />
      </div>
    );
  }

  const gate = data.gate;
  const ic = data.ic;
  const stale = data.stale || {};
  const verdict = gate ? gate.verdict : 'UNKNOWN';
  const vs = VERDICT_STYLE[verdict] || VERDICT_STYLE.UNKNOWN;
  const hm = gate?.headline_metrics || {};

  return (
    <div className="fade-in" style={{ display: 'flex', flexDirection: 'column', gap: 20 }}>
      {/* Verdict headline */}
      <Card style={{ padding: 24 }}>
        <div className={styles.verdictBlock}>
          <div className={styles.verdictMeta}>
            <Scale size={15} />
            <span>PRE-REGISTERED FORWARD TEST - GATE READ</span>
            {gate && <span>{gate.date}</span>}
            {stale.is_stale && <span className={styles.staleBadge}>STALE</span>}
          </div>
          <div className={styles.verdictWord} style={{ color: vs.color }}>{vs.word}</div>
          <div className={styles.verdictSub}>{VERDICT_SUB[verdict] || VERDICT_SUB.UNKNOWN}</div>
        </div>
        {gate && (
          <div className={styles.metricsGrid}>
            <Metric
              label="Decided plays (conviction >= 65)"
              value={hm.n_decided ?? '-'}
              sub="cohort C, the gating cohort"
            />
            <Metric
              label="Win rate"
              value={hm.win_rate != null ? (hm.win_rate * 100).toFixed(1) + '%' : '-'}
              color={hm.win_rate != null ? (hm.win_rate >= 0.55 ? 'var(--color-success)' : hm.win_rate < 0.5 ? 'var(--color-danger)' : 'var(--color-warning)') : undefined}
              sub="pass bar 55% - fail rule under 50%"
            />
            <Metric
              label="Expectancy"
              value={fmt(hm.expectancy)}
              sub="mean realized return per play"
            />
            <Metric
              label="Artifact age"
              value={stale.gate_days != null ? stale.gate_days + 'd' : '-'}
              color={stale.is_stale ? 'var(--color-warning)' : undefined}
              sub="from the date in the filename"
            />
          </div>
        )}
        {gate?.raw_md && (
          <div style={{ marginTop: 16 }}>
            <button className={styles.rawToggle} onClick={() => setShowGateRaw(s => !s)}>
              <FileText size={12} style={{ verticalAlign: '-2px' }} /> {showGateRaw ? 'Hide' : 'Show'} raw gate read
            </button>
            {showGateRaw && <pre className={styles.rawMd}>{gate.raw_md}</pre>}
          </div>
        )}
      </Card>

      {/* IC report */}
      <Card style={{ padding: 20 }}>
        <h2 className={styles.sectionTitle}>Weekly IC report - is any component predictive?</h2>
        {!ic && (
          <p className={styles.explainer}>No IC report delivered yet.</p>
        )}
        {ic && (
          <>
            <div className={styles.verdictMeta} style={{ marginBottom: 12 }}>
              <span>{ic.date}</span>
              {stale.ic_days != null && <span>{stale.ic_days}d old</span>}
              {ic.hypotheses != null && <span>{ic.hypotheses} hypotheses tested</span>}
            </div>
            <div className={styles.metricsGrid} style={{ marginTop: 0, marginBottom: 16 }}>
              <Metric
                label="Supported"
                value={ic.supported ?? '-'}
                color={ic.supported === 0 ? 'var(--color-danger)' : 'var(--color-success)'}
                sub={ic.hypotheses != null ? `of ${ic.hypotheses} hypotheses` : undefined}
              />
              <Metric label="Noise" value={ic.noise ?? '-'} sub="bar not cleared" />
              <Metric label="Insufficient" value={ic.insufficient ?? '-'} sub="too little data to judge" />
            </div>
            {ic.delta_paragraph && (
              <div className={styles.delta}>{ic.delta_paragraph}</div>
            )}
            {ic.table && ic.table.length > 0 && (
              <div style={{ overflowX: 'auto', marginTop: 16 }}>
                <table className={styles.icTable}>
                  <thead>
                    <tr>
                      <th>Series</th><th>Horizon</th><th>Mean IC</th><th>t_adj</th>
                      <th>H1</th><th>H2</th><th>Same sign</th><th>Days</th><th>Verdict</th>
                    </tr>
                  </thead>
                  <tbody>
                    {ic.table.map((r, i) => (
                      <tr key={i} style={{ background: i % 2 === 0 ? 'var(--color-bg)' : 'transparent' }}>
                        <td>{r.series}</td>
                        <td>{r.horizon}d</td>
                        <td>{fmt(r.mean_ic, 4)}</td>
                        <td>{fmt(r.t_adj, 2)}</td>
                        <td>{fmt(r.ic_h1, 4)}</td>
                        <td>{fmt(r.ic_h2, 4)}</td>
                        <td>{r.same_sign ? 'yes' : 'no'}</td>
                        <td>{r.n_days ?? '-'}</td>
                        <td>
                          <Badge
                            color={r.verdict === 'SUPPORTED' ? 'var(--color-success)' : r.verdict === 'INSUFFICIENT' ? 'var(--color-warning)' : 'var(--color-text-tertiary)'}
                            variant="soft"
                          >
                            {r.verdict}
                          </Badge>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            {ic.raw_md && (
              <div style={{ marginTop: 14 }}>
                <button className={styles.rawToggle} onClick={() => setShowIcRaw(s => !s)}>
                  <FileText size={12} style={{ verticalAlign: '-2px' }} /> {showIcRaw ? 'Hide' : 'Show'} raw IC report
                </button>
                {showIcRaw && <pre className={styles.rawMd}>{ic.raw_md}</pre>}
              </div>
            )}
          </>
        )}
      </Card>

      {/* History */}
      <Card style={{ padding: 20 }}>
        <h2 className={styles.sectionTitle}>Delivered artifacts</h2>
        {!history || history.status === 'no_artifacts_yet' ? (
          <p className={styles.explainer}>Nothing delivered yet.</p>
        ) : (
          <div className={styles.historyList}>
            {[...(history.gate_reads || []), ...(history.ic_reports || [])].map((e, i) => (
              <div key={i} className={styles.historyRow}>
                <span className={styles.historyFile}>{e.file}</span>
                <span className={styles.historyDate}>{e.date}</span>
              </div>
            ))}
          </div>
        )}
      </Card>

      <ExplainerCard />
    </div>
  );
}

function ExplainerCard() {
  return (
    <Card style={{ padding: 20 }}>
      <h2 className={styles.sectionTitle}>Why this page exists</h2>
      <p className={styles.explainer}>
        A <strong>pre-registered forward test</strong> works like a clinical trial for a
        scoring system: the pass bar, the fail rule, the cohort definitions and the
        sample sizes were all written down and committed <strong>before</strong> the
        first play was scored, so the system cannot move the goalposts after seeing
        the results. Every week the test is read mechanically - no judgment calls -
        and the verdict lands here exactly as generated, along with the IC report
        that asks whether any individual score component actually predicts forward
        returns. The site publishes its own failures for the same reason it
        pre-registered the test: a track record you can only see when it is
        flattering is not a track record. If the verdict above says FAIL, that is
        the system working - the measurement is honest even when the signal is not
        yet good.
      </p>
    </Card>
  );
}
