import { useState } from 'react';
import { useAuth } from './AuthContext';
import styles from './AuthPages.module.css';

/**
 * Roman-themed login page with Citizen's Oath acknowledgment.
 */
export function LoginPage({ onSwitchToRegister, onSuccess }) {
  const { login, loading } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!email || !password) {
      setError('All fields are required');
      return;
    }
    const result = await login(email, password);
    if (result.error) {
      setError(result.error);
    } else if (result.ok) {
      onSuccess?.(result);
    }
  };

  return (
    <div className={styles.container}>
      <div className={styles.card}>
        <div className={styles.header}>
          <h1 className={styles.title}>QUAEST</h1>
          <p className={styles.subtitle}>Enter the Senate</p>
        </div>

        <form className={styles.form} onSubmit={handleSubmit}>
          <div className={styles.field}>
            <label className={styles.label}>Email</label>
            <input
              className={styles.input}
              type="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="citizen@quaest.tech"
              autoComplete="email"
            />
          </div>

          <div className={styles.field}>
            <label className={styles.label}>Password</label>
            <input
              className={styles.input}
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              placeholder="••••••••"
              autoComplete="current-password"
            />
          </div>

          {error && <div className={styles.error}>{error}</div>}

          <button className={styles.button} type="submit" disabled={loading}>
            {loading ? 'Entering...' : 'Enter the Senate'}
          </button>
        </form>

        <div className={styles.footer}>
          <span className={styles.footerText}>No citizenship yet?</span>
          <button className={styles.link} onClick={onSwitchToRegister}>
            Claim Your Name
          </button>
        </div>
      </div>
    </div>
  );
}
