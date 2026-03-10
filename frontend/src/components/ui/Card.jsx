import styles from './Card.module.css';

/**
 * Marble-textured card with silver hairline border.
 * @param {'default'|'elevated'|'interactive'} variant
 */
export function Card({ children, variant = 'default', className = '', style = {}, ...rest }) {
  const cls = [styles.card, styles[variant], className].filter(Boolean).join(' ');
  return (
    <div className={cls} style={style} {...rest}>
      {children}
    </div>
  );
}
