import styles from './Metric.module.css';

/**
 * Single metric display — label + large value + optional sub-text.
 */
export function Metric({ label, value, sub, color, className = '' }) {
  return (
    <div className={`${styles.metric} ${className}`}>
      <div className={styles.label}>{label}</div>
      <div className={styles.value} style={color ? { color } : undefined}>
        {value ?? '—'}
      </div>
      {sub && <div className={styles.sub}>{sub}</div>}
    </div>
  );
}
