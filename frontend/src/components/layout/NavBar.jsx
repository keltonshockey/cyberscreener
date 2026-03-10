import { NavLink } from 'react-router-dom';
import { useAuth } from '../../auth/AuthContext';
import styles from './NavBar.module.css';

const NAV_ITEMS = [
  { to: '/', label: 'Basilica', icon: '🏛️' },
  { to: '/conviction', label: 'Conviction', icon: '📜' },
  { to: '/anvil', label: 'Anvil', icon: '⚔️' },
  { to: '/archive', label: 'Archive', icon: '📚' },
  { to: '/world', label: 'World', icon: '🗺️' },
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
            {item.label}
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
