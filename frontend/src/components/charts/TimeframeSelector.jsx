import s from './TimeframeSelector.module.css';

/**
 * Shared timeframe selector — row of day-period buttons.
 * Used by all time-series charts.
 */
export function TimeframeSelector({ options = [30, 60, 90, 180], value, onChange }) {
  return (
    <div className={s.row}>
      {options.map(d => (
        <button
          key={d}
          className={`${s.btn} ${value === d ? s.active : ''}`}
          onClick={() => onChange(d)}
        >
          {d}d
        </button>
      ))}
    </div>
  );
}
