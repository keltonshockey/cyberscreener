import styles from './Footer.module.css';

export function Footer() {
  return (
    <footer className={styles.footer}>
      <div className={styles.edictum}>
        <span className={styles.label}>EDICTUM</span>
        <span className={styles.text}>
          Quaest.tech is a historical simulation tool. Not a Broker-Dealer or Investment Advisor. Past performance does not guarantee future results. CAVEAT EMPTOR.
        </span>
      </div>
      <div className={styles.meta}>
        <span>QUAEST v4.0</span>
        <span>&middot;</span>
        <span>quaest.tech</span>
      </div>
    </footer>
  );
}
