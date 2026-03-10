import { useState, useMemo } from 'react';
import { useAuth } from './AuthContext';
import { augurCreate } from '../api/endpoints';
import styles from './QuaestorCreator.module.css';

const VIRTUTES = [
  { key: 'prudentia', name: 'Prudentia', icon: '🛡️', desc: 'Caution — boosts Valuation & Earnings Quality' },
  { key: 'audacia', name: 'Audacia', icon: '⚔️', desc: 'Boldness — boosts Directional Conviction & Asymmetry' },
  { key: 'sapientia', name: 'Sapientia', icon: '📜', desc: 'Wisdom — boosts FCF Margin & Rule of 40' },
  { key: 'fortuna', name: 'Fortuna', icon: '🎲', desc: 'Momentum — boosts Discount Momentum & Trend' },
  { key: 'prospectus', name: 'Prospectus', icon: '👁', desc: 'Vision — boosts Earnings Catalyst & IV Context' },
  { key: 'liquiditas', name: 'Liquiditas', icon: '💧', desc: 'Liquidity — boosts Liquidity & Technical Setup' },
];

const POOL = 36;
const MIN = 1;
const MAX = 10;

/**
 * Quaestor character creation — 6 Virtutes sliders, 36-point pool.
 */
export function QuaestorCreator({ onCreated }) {
  const { refreshProfile } = useAuth();
  const [attrs, setAttrs] = useState(
    Object.fromEntries(VIRTUTES.map(v => [v.key, 6]))
  );
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  const total = useMemo(() => Object.values(attrs).reduce((s, v) => s + v, 0), [attrs]);
  const remaining = POOL - total;

  const dominantTrait = useMemo(() => {
    const entries = Object.entries(attrs);
    const maxVal = Math.max(...entries.map(([, v]) => v));
    const dominant = entries.find(([, v]) => v === maxVal);
    return VIRTUTES.find(v => v.key === dominant?.[0]);
  }, [attrs]);

  const handleSlider = (key, value) => {
    const newVal = Number(value);
    const otherTotal = total - attrs[key];
    if (otherTotal + newVal > POOL) return;
    setAttrs(prev => ({ ...prev, [key]: newVal }));
  };

  const handleSubmit = async () => {
    setError('');
    if (total !== POOL) {
      setError(`Must allocate exactly ${POOL} points (currently ${total})`);
      return;
    }
    setLoading(true);
    const result = await augurCreate(attrs);
    if (result && !result.error) {
      await refreshProfile();
      onCreated?.(result);
    } else {
      setError(result?.error || result?.detail || 'Failed to create character');
    }
    setLoading(false);
  };

  return (
    <div className={styles.container}>
      <div className={styles.card}>
        <div className={styles.header}>
          <h2 className={styles.title}>FORGE YOUR QUAESTOR</h2>
          <p className={styles.subtitle}>
            Distribute {POOL} points across your Virtutes. Your character's personality biases which signals you see most clearly.
          </p>
        </div>

        <div className={styles.pool}>
          <span className={styles.poolLabel}>POINT POOL</span>
          <span className={`${styles.poolValue} ${remaining < 0 ? styles.over : remaining === 0 ? styles.complete : ''}`}>
            {remaining} remaining
          </span>
        </div>

        <div className={styles.sliders}>
          {VIRTUTES.map(v => (
            <div key={v.key} className={styles.sliderRow}>
              <div className={styles.sliderMeta}>
                <span className={styles.sliderIcon}>{v.icon}</span>
                <div>
                  <div className={styles.sliderName}>{v.name}</div>
                  <div className={styles.sliderDesc}>{v.desc}</div>
                </div>
              </div>
              <div className={styles.sliderControl}>
                <input
                  type="range"
                  min={MIN}
                  max={MAX}
                  value={attrs[v.key]}
                  onChange={e => handleSlider(v.key, e.target.value)}
                  className={styles.slider}
                />
                <span className={styles.sliderValue}>{attrs[v.key]}</span>
              </div>
            </div>
          ))}
        </div>

        {dominantTrait && (
          <div className={styles.preview}>
            <span className={styles.previewIcon}>{dominantTrait.icon}</span>
            <span className={styles.previewText}>
              Dominant Trait: <strong>{dominantTrait.name}</strong>
            </span>
          </div>
        )}

        {error && <div className={styles.error}>{error}</div>}

        <button
          className={styles.button}
          onClick={handleSubmit}
          disabled={loading || remaining !== 0}
        >
          {loading ? 'Forging...' : 'Forge My Character'}
        </button>
      </div>
    </div>
  );
}
