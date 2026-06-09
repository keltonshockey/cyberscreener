/**
 * QUAEST.TECH — Stat tile (detail card scores).
 * Big tabular value + a gold-to-verd fill bar + inline hover-explain.
 * Matches ui-mockup.html .score.
 */
import { Explain } from './Explain';
import styles from './Stat.module.css';

export function Stat({ label, term, value, pct, max = 100, accent }) {
  const width = pct != null ? pct : (typeof value === 'number' ? (value / max) * 100 : 0);
  return (
    <div className={styles.score}>
      <div className={styles.k}>
        {label}
        {term && <Explain term={term} />}
      </div>
      <div className={styles.v}>{value}</div>
      <div className={styles.bar}>
        <i style={{ width: `${Math.max(0, Math.min(100, width))}%`, background: accent }} />
      </div>
    </div>
  );
}
