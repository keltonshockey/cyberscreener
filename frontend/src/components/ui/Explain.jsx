/**
 * QUAEST.TECH — universal hover-explain (§6).
 * Glance gives the value; hover/focus opens a frosted popover: plain-language
 * definition + why it matters + how it's computed. Optional onDeepDive
 * (click) for the deep dive (Ticker page / RC breakdown).
 *
 * Usage:
 *   <Explain term="sma" />                       // info icon trigger
 *   <Explain term="lt_score">LT value</Explain>  // wrap a label
 *   <Explain title="…" body="…" />               // ad-hoc copy
 */
import { Info, ChevronRight } from './icons';
import { getTerm } from '../../utils/glossary';
import styles from './Explain.module.css';

export function Explain({ term, title, body, why, how, children, align = 'left', size = 12, onDeepDive }) {
  const t = term ? getTerm(term) : null;
  const heading = title || t?.title;
  const def = body || t?.def;
  const whyText = why || t?.why;
  const howText = how || t?.how;
  if (!heading && !def) return children || null;

  return (
    <span className={styles.wrap} tabIndex={0}>
      {children ? (
        <span className={styles.term}>{children}</span>
      ) : (
        <Info size={size} className={styles.icon} />
      )}
      <span className={`${styles.tip} ${align === 'right' ? styles.right : ''}`} role="tooltip">
        {heading && <b className={styles.h}>{heading}</b>}
        {def && <span className={styles.def}>{def}</span>}
        {whyText && <span className={styles.line}><em>Why</em> {whyText}</span>}
        {howText && <span className={styles.line}><em>How</em> {howText}</span>}
        {onDeepDive && (
          <button className={styles.deep} onClick={(e) => { e.stopPropagation(); onDeepDive(); }}>
            Open deep dive <ChevronRight size={12} style={{ verticalAlign: '-2px' }} />
          </button>
        )}
      </span>
    </span>
  );
}
