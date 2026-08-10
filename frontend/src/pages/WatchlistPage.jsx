/**
 * QUAEST.TECH - Valuation Watchlist (front page)
 * Monthly snapshot of the one evidence-backed signal: lt_valuation
 * (growth-adjusted EV/Revenue). The as-of month is the headline, the
 * survivorship caveat and horizon copy are first-class visible copy served
 * by the API (single source: api/core/watchlist_copy.py), and the table is
 * a plain ranked list - deliberately no intraday movement, no sparklines.
 * Imperial Twilight: gold hairlines, tabular figures, zero emoji.
 */

import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card } from '../components/ui/Card';
import { Scale } from '../components/ui/icons';
import { fetchValuationWatchlist } from '../api/endpoints';
import styles from './WatchlistPage.module.css';

function monthLabel(ym) {
  // "2026-07" -> "July 2026" (UTC-safe: no Date parsing of a bare month).
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June',
    'July', 'August', 'September', 'October', 'November', 'December'];
  const m = /^(\d{4})-(\d{2})$/.exec(ym || '');
  if (!m) return ym || '';
  const idx = parseInt(m[2], 10) - 1;
  return MONTHS[idx] ? `${MONTHS[idx]} ${m[1]}` : ym;
}

export function WatchlistPage() {
  const navigate = useNavigate();
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let live = true;
    fetchValuationWatchlist(25).then(d => {
      if (!live) return;
      if (d && Array.isArray(d.entries)) setData(d);
      else setFailed(true);
    });
    return () => { live = false; };
  }, []);

  const entries = data?.entries || [];

  return (
    <div className="fade-in">
      <h1 className={styles.title}>Valuation Watchlist</h1>
      <div className={styles.sub}>
        Growth-adjusted EV/Revenue - the one signal with pre-registered out-of-sample evidence
      </div>

      {data && (
        <div className={styles.asOf}>
          <Scale size={16} className={styles.asOfIcon} />
          <span className={styles.asOfMonth}>{monthLabel(data.snapshot_month)}</span>
          <span className={styles.asOfMeta}>
            snapshot - scan #{data.as_of_scan_id} - {data.as_of_utc} UTC
          </span>
        </div>
      )}

      {/* Registered copy, first-class and above the table - not a footnote. */}
      {data?.copy && (
        <Card className={styles.copyCard}>
          <div className={styles.horizon}>{data.copy.horizon}</div>
          <div className={styles.caveat}>{data.copy.caveat}</div>
        </Card>
      )}

      {!data && !failed && <div className={styles.state}>Loading the monthly snapshot...</div>}
      {failed && (
        <div className={styles.state}>
          The monthly snapshot is unavailable right now. It returns with the next completed scan month.
        </div>
      )}

      {entries.length > 0 && (
        <div className={styles.gridWrap}>
          <table className={styles.grid}>
            <thead>
              <tr>
                <th className={styles.rankCol}>Rank</th>
                <th className={styles.l}>Ticker</th>
                <th>Valuation</th>
                <th className={styles.l}>Sector</th>
              </tr>
            </thead>
            <tbody>
              {entries.map(e => (
                <tr key={e.ticker} onClick={() => navigate(`/ticker/${e.ticker}`)}>
                  <td className={`${styles.num} ${styles.rank}`}>{e.rank}</td>
                  <td className={styles.l}><span className={styles.tk}>{e.ticker}</span></td>
                  <td className={`${styles.num} ${styles.strong}`}>
                    {e.lt_valuation != null ? Math.round(e.lt_valuation) : '-'}
                  </td>
                  <td className={styles.l}>
                    {e.sector ? <span className={styles.sec}>{e.sector}</span> : '-'}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {data && entries.length === 0 && (
        <div className={styles.state}>No ranked names in this month's snapshot.</div>
      )}

      <div className={styles.foot}>
        Ranked by lt_valuation, descending - held still for the calendar month - Imperial Twilight, zero emoji
      </div>
    </div>
  );
}
