import { useAuth } from '../../auth/AuthContext';
import { SearchBar } from './SearchBar';
import { useTheme } from '../../theme/useTheme';
import { Sun, Moon, Scale } from '../ui/icons';
import styles from './Header.module.css';

export function Header({ onAuthClick, latest }) {
  const { user, profile, logout } = useAuth();
  const { theme, toggle } = useTheme();

  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <h1 className={styles.wordmark}>QUAEST</h1>
        <span className={styles.tagline}>Ancient Intelligence. Modern Gains.</span>
      </div>

      {/* Global ticker search */}
      <SearchBar results={latest?.results || []} />

      <div className={styles.actions}>
        <button
          className={styles.themeBtn}
          onClick={toggle}
          title={theme === 'light' ? 'Switch to dark (Imperial Twilight)' : 'Switch to light (museum daylight)'}
          aria-label="Toggle theme"
        >
          {theme === 'light' ? <Moon size={16} /> : <Sun size={16} />}
        </button>
        {user ? (
          <div className={styles.userInfo}>
            <div className={styles.avatar}>
              {(user.augur_name || 'Q')[0].toUpperCase()}
            </div>
            <div className={styles.userMeta}>
              <span className={styles.userName}>{user.augur_name}</span>
              {profile && <span className={styles.userTitle}>{profile.title || 'Novice Quaestor'}</span>}
            </div>
            <button className={styles.logoutBtn} onClick={logout}>Logout</button>
          </div>
        ) : (
          <button className={styles.signInBtn} onClick={onAuthClick}>
            <Scale size={14} style={{ verticalAlign: '-2px', marginRight: 6 }} />Sign In
          </button>
        )}
      </div>
    </header>
  );
}
