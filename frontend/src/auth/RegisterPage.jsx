import { useState } from 'react';
import { useAuth } from './AuthContext';
import styles from './AuthPages.module.css';

/**
 * Registration page with Citizen's Oath.
 */
export function RegisterPage({ onSwitchToLogin, onSuccess }) {
  const { register, loading } = useAuth();
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [augurName, setAugurName] = useState('');
  const [oathAccepted, setOathAccepted] = useState(false);
  const [error, setError] = useState('');

  const handleSubmit = async (e) => {
    e.preventDefault();
    setError('');
    if (!email || !password || !augurName) {
      setError('All fields are required');
      return;
    }
    if (password.length < 6) {
      setError('Password must be at least 6 characters');
      return;
    }
    if (!oathAccepted) {
      setError('You must accept the Citizen\'s Oath');
      return;
    }
    const result = await register(email, password, augurName);
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
          <p className={styles.subtitle}>Claim Your Name</p>
        </div>

        <form className={styles.form} onSubmit={handleSubmit}>
          <div className={styles.field}>
            <label className={styles.label}>Quaestor Name</label>
            <input
              className={styles.input}
              type="text"
              value={augurName}
              onChange={e => setAugurName(e.target.value)}
              placeholder="Marcus Aurelius"
              autoComplete="username"
            />
          </div>

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
              placeholder="Min. 6 characters"
              autoComplete="new-password"
            />
          </div>

          {/* Citizen's Oath */}
          <div className={styles.oath}>
            <div className={styles.oathTitle}>CITIZEN'S OATH</div>
            <div className={styles.oathText}>
              <p><strong>I. The Past is Stone.</strong> Historical data cannot be altered.</p>
              <p><strong>II. The Forge is a Mirror.</strong> Backtests reflect the past, not the future.</p>
              <p><strong>III. No Gold Changes Hands.</strong> This is simulation, not financial advice.</p>
              <p><strong>IV. Sovereignty of Risk.</strong> I alone bear responsibility for my decisions.</p>
            </div>
            <label className={styles.oathCheck}>
              <input
                type="checkbox"
                checked={oathAccepted}
                onChange={e => setOathAccepted(e.target.checked)}
              />
              <span>I accept the Citizen's Oath</span>
            </label>
          </div>

          {error && <div className={styles.error}>{error}</div>}

          <button className={styles.button} type="submit" disabled={loading || !oathAccepted}>
            {loading ? 'Forging Identity...' : 'Forge My Identity'}
          </button>
        </form>

        <div className={styles.footer}>
          <span className={styles.footerText}>Already a citizen?</span>
          <button className={styles.link} onClick={onSwitchToLogin}>
            Enter the Senate
          </button>
        </div>
      </div>
    </div>
  );
}
