/**
 * QUAEST.TECH — filter Chip (multi-select, with count).
 * Sectors are first-class chips, not a dropdown (§4).
 */
import styles from './Chip.module.css';

export function Chip({ label, count, active, onClick, muted }) {
  return (
    <button
      className={`${styles.chip} ${active ? styles.on : ''} ${muted ? styles.muted : ''}`}
      onClick={onClick}
      aria-pressed={!!active}
    >
      {label}
      {count != null && <span className={styles.ct}>{count}</span>}
    </button>
  );
}
