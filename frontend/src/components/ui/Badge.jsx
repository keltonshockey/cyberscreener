import styles from './Badge.module.css';

/**
 * Inline badge component.
 * @param {string} color - CSS color value
 * @param {'filled'|'outline'|'soft'} variant
 */
export function Badge({ children, color, variant = 'soft', className = '', style = {} }) {
  const cls = [styles.badge, styles[variant], className].filter(Boolean).join(' ');
  const customStyle = color
    ? variant === 'filled'
      ? { backgroundColor: color, color: '#fff', ...style }
      : variant === 'outline'
      ? { borderColor: color, color, ...style }
      : { backgroundColor: color + '18', color, ...style }
    : style;

  return <span className={cls} style={customStyle}>{children}</span>;
}
