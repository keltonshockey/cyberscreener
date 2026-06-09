/**
 * QUAEST.TECH — SegmentedControl
 * The two-stack spine: switch products (Long-term value | Tactical options),
 * not blend them. options = [{ value, label, Icon }].
 */
import styles from './SegmentedControl.module.css';

export function SegmentedControl({ options, value, onChange }) {
  return (
    <div className={styles.seg} role="tablist">
      {options.map(opt => {
        const on = opt.value === value;
        const Icon = opt.Icon;
        return (
          <button
            key={opt.value}
            role="tab"
            aria-selected={on}
            className={on ? styles.on : ''}
            onClick={() => onChange(opt.value)}
          >
            {Icon && <Icon size={13} />}
            {opt.label}
          </button>
        );
      })}
    </div>
  );
}
