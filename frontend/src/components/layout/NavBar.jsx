import { NavLink } from 'react-router-dom';
import { useAuth } from '../../auth/AuthContext';
import styles from './NavBar.module.css';

const NAV_ITEMS = [
  { to: '/', label: 'Basilica', sub: 'Dashboard', icon: '🏛️' },
  { to: '/conviction', label: 'Conviction', sub: 'Rankings', icon: '📜' },
  { to: '/pactum', label: 'Pactum', sub: 'Options Plays', icon: '⚖️' },
  { to: '/archive', label: 'Archive', sub: 'Backtest', icon: '📚' },
  { to: '/world', label: 'World', sub: '3D City', icon: '🗺️' },
];

export function NavBar({ onRunScan, scanRunning }) {
  const { isAdmin } = useAuth();

  return (
    <nav className={styles.nav}>
      <div className={styles.links}>
        {NAV_ITEMS.map(item => (
          <NavLink
            key={item.to}
            to={item.to}
            end={item.to === '/'}
            className={({ isActive }) => `${styles.link} ${isActive ? styles.active : ''}`}
          >
            <span className={styles.icon}>{item.icon}</span>
            <span className={styles.labelGroup}>
              {item.label}
              <span className={styles.sub}>{item.sub}</span>
            </span>
          </NavLink>
        ))}
      </div>

      {isAdmin && (
        <button
          className={styles.scanBtn}
          onClick={onRunScan}
          disabled={scanRunning}
        >
          {scanRunning ? '⟳ Scanning...' : '▶ Run Scan'}
        </button>
      )}
    </nav>
  );
}
