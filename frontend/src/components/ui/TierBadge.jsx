/**
 * QUAEST.TECH — conviction TierBadge.
 * High (gold) / Solid (tyrian) / Watch (muted) — the 3-step seal.
 */
import styles from './TierBadge.module.css';

export function tierFor(score) {
  if (score >= 75) return 'high';
  if (score >= 65) return 'solid';
  return 'watch';
}

const LABEL = { high: 'High', solid: 'Solid', watch: 'Watch' };

export function TierBadge({ score, tier }) {
  const t = tier || tierFor(score);
  return (
    <span className={`${styles.tier} ${styles[t]}`}>
      {LABEL[t]}{score != null && <> · {Math.round(score)}</>}
    </span>
  );
}
