import { useAuth } from '../../auth/AuthContext';
import { SearchBar } from './SearchBar';
import styles from './Header.module.css';

export function Header({ onAuthClick, latest }) {
  const { user, profile, logout } = useAuth();

  return (
    <header className={styles.header}>
      <div className={styles.brand}>
        <h1 className={styles.wordmark}>QUAEST</h1>
        <span className={styles.tagline}>Ancient Intelligence. Modern Gains.</span>
      </div>

      {/* Global ticker search */}
      <SearchBar results={latest?.results || []} />

      <div className={styles.actions}>
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
            {'⚔️'} Sign In
          </button>
        )}
      </div>
    </header>
  );
}
