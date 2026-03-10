import { ScoreBar } from './ScoreBar';
import styles from './BreakdownPanel.module.css';

/**
 * Score component breakdown grid — shows each factor's contribution.
 * @param {Array} items - Array of { key, name, icon, points, max, pct }
 * @param {string} title
 * @param {string} accent - CSS color for header accent
 */
export function BreakdownPanel({ items, title, accent, className = '' }) {
  if (!items || !items.length) return null;

  return (
    <div className={`${styles.panel} ${className}`}>
      {title && (
        <div className={styles.header} style={accent ? { borderLeftColor: accent } : undefined}>
          {title}
        </div>
      )}
      <div className={styles.grid}>
        {items.map(item => (
          <div key={item.key} className={styles.row}>
            <div className={styles.meta}>
              {item.icon && <span className={styles.icon}>{item.icon}</span>}
              <span className={styles.name}>{item.name}</span>
            </div>
            <div className={styles.bar}>
              <ScoreBar score={item.points} max={item.max} height={4} />
            </div>
            <div className={styles.value}>
              {item.points?.toFixed?.(1) ?? item.points}/{item.max}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
