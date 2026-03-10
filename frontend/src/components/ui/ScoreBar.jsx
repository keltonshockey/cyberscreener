import styles from './ScoreBar.module.css';

/**
 * Horizontal score bar (0-100) with color gradient.
 */
export function ScoreBar({ score, max = 100, height = 6, showLabel = false, className = '' }) {
  const pct = max > 0 ? Math.min((score / max) * 100, 100) : 0;

  const barColor =
    pct >= 70 ? 'var(--color-success)'
    : pct >= 40 ? 'var(--color-warning)'
    : 'var(--color-danger)';

  return (
    <div className={`${styles.container} ${className}`}>
      <div className={styles.track} style={{ height }}>
        <div
          className={`${styles.fill} fill-bar`}
          style={{ width: `${pct}%`, backgroundColor: barColor, height }}
        />
      </div>
      {showLabel && (
        <span className={styles.label} style={{ color: barColor }}>
          {Math.round(score)}
        </span>
      )}
    </div>
  );
}
