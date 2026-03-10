import styles from './LayerPill.module.css';

/**
 * Intel layer status pill (SEC/Sentiment/Whale).
 */
export function LayerPill({ name, icon, score, className = '' }) {
  const status = score == null ? 'inactive' : score > 0 ? 'positive' : score < 0 ? 'negative' : 'neutral';

  return (
    <span className={`${styles.pill} ${styles[status]} ${className}`}>
      {icon && <span className={styles.icon}>{icon}</span>}
      <span className={styles.name}>{name}</span>
      {score != null && (
        <span className={styles.score}>
          {score > 0 ? '+' : ''}{score}
        </span>
      )}
    </span>
  );
}
