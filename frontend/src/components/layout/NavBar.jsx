import { NavLink } from 'react-router-dom';
import { useAuth } from '../../auth/AuthContext';
import { Landmark, Scroll, Zap, Library, Globe, Play, RefreshCw } from '../ui/icons';
import styles from './NavBar.module.css';

const NAV_ITEMS = [
  { to: '/', label: 'Basilica', sub: 'today', Icon: Landmark },
  { to: '/conviction', label: 'Forum', sub: 'long-term value', Icon: Scroll },
  { to: '/pactum', label: 'Pactum', sub: 'tactical options', Icon: Zap },
  { to: '/archive', label: 'Archive', sub: 'backtest', Icon: Library },
  { to: '/world', label: 'World', sub: 'the city', Icon: Globe },
];

export function NavBar({ onRunScan, scanRunning }) {
  const { isAdmin } = useAuth();

  return (
    <nav className={styles.nav}>
      <div className={styles.links}>
        {NAV_ITEMS.map(({ to, label, sub, Icon }) => (
          <NavLink
            key={to}
            to={to}
            end={to === '/'}
            className={({ isActive }) => `${styles.link} ${isActive ? styles.active : ''}`}
          >
            <Icon size={15} className={styles.icon} />
            <span className={styles.labelGroup}>
              {label}
              <span className={styles.sub}>{sub}</span>
            </span>
          </NavLink>
        ))}
      </div>

      {isAdmin && (
        <button className={styles.scanBtn} onClick={onRunScan} disabled={scanRunning}>
          {scanRunning
            ? <><RefreshCw size={13} className={styles.spin} /> Scanning…</>
            : <><Play size={13} /> Run Scan</>}
        </button>
      )}
    </nav>
  );
}
