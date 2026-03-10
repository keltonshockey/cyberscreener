/**
 * QUAEST.TECH — Global Search Bar
 * Fuzzy ticker search across the full universe + watchlist.
 * Keyboard shortcut: / or Cmd+K to focus.
 */

import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';

export function SearchBar({ results = [] }) {
  const [query, setQuery] = useState('');
  const [isOpen, setIsOpen] = useState(false);
  const [selectedIdx, setSelectedIdx] = useState(0);
  const inputRef = useRef(null);
  const navigate = useNavigate();

  // Build searchable index from latest results
  const tickers = results.map(r => ({
    ticker: r.ticker,
    price: r.price,
    lt_score: r.lt_score,
    opt_score: r.opt_score,
    sector: r.sector || '',
    subsector: r.subsector || '',
  }));

  // Filter by query
  const filtered = query.length > 0
    ? tickers.filter(t =>
        t.ticker.toLowerCase().includes(query.toLowerCase()) ||
        t.sector.toLowerCase().includes(query.toLowerCase()) ||
        t.subsector.toLowerCase().includes(query.toLowerCase())
      ).slice(0, 12)
    : [];

  // Keyboard shortcut: / or Cmd+K to focus
  useEffect(() => {
    const handleKey = (e) => {
      if ((e.key === '/' && !e.ctrlKey && !e.metaKey && document.activeElement.tagName !== 'INPUT' && document.activeElement.tagName !== 'TEXTAREA') ||
          ((e.metaKey || e.ctrlKey) && e.key === 'k')) {
        e.preventDefault();
        inputRef.current?.focus();
        setIsOpen(true);
      }
      if (e.key === 'Escape') {
        setIsOpen(false);
        setQuery('');
        inputRef.current?.blur();
      }
    };
    document.addEventListener('keydown', handleKey);
    return () => document.removeEventListener('keydown', handleKey);
  }, []);

  // Navigate on selection
  const handleSelect = useCallback((ticker) => {
    setQuery('');
    setIsOpen(false);
    inputRef.current?.blur();
    // Navigate to conviction with the ticker selected
    navigate('/conviction', { state: { ticker } });
  }, [navigate]);

  const handleAnvilSelect = useCallback((ticker) => {
    setQuery('');
    setIsOpen(false);
    inputRef.current?.blur();
    navigate('/anvil', { state: { ticker } });
  }, [navigate]);

  // Keyboard navigation in results
  const handleKeyDown = (e) => {
    if (e.key === 'ArrowDown') {
      e.preventDefault();
      setSelectedIdx(i => Math.min(i + 1, filtered.length - 1));
    } else if (e.key === 'ArrowUp') {
      e.preventDefault();
      setSelectedIdx(i => Math.max(i - 1, 0));
    } else if (e.key === 'Enter' && filtered[selectedIdx]) {
      handleSelect(filtered[selectedIdx].ticker);
    }
  };

  return (
    <div style={{ position: 'relative', flex: '0 1 320px' }}>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        background: 'var(--color-bg)', border: '1px solid var(--color-border-subtle)',
        borderRadius: 8, padding: '6px 12px',
      }}>
        <span style={{ fontSize: 13, opacity: 0.5 }}>{'🔍'}</span>
        <input
          ref={inputRef}
          type="text"
          value={query}
          onChange={e => { setQuery(e.target.value); setSelectedIdx(0); setIsOpen(true); }}
          onFocus={() => setIsOpen(true)}
          onBlur={() => setTimeout(() => setIsOpen(false), 200)}
          onKeyDown={handleKeyDown}
          placeholder="Search tickers... (/ or Cmd+K)"
          style={{
            flex: 1, border: 'none', background: 'transparent', outline: 'none',
            color: 'var(--color-text)', fontSize: 12, fontFamily: 'var(--font-mono)',
          }}
        />
        {query && (
          <button
            onClick={() => { setQuery(''); inputRef.current?.focus(); }}
            style={{ border: 'none', background: 'none', color: 'var(--color-text-tertiary)', cursor: 'pointer', fontSize: 12 }}
          >
            {'✕'}
          </button>
        )}
      </div>

      {/* Results dropdown */}
      {isOpen && filtered.length > 0 && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, right: 0, marginTop: 4,
          background: 'var(--color-bg-card)', border: '1px solid var(--color-border-subtle)',
          borderRadius: 10, boxShadow: '0 8px 32px rgba(0,0,0,0.5)', zIndex: 1000,
          maxHeight: 360, overflowY: 'auto',
        }}>
          {filtered.map((t, i) => (
            <div
              key={t.ticker}
              onMouseDown={e => { e.preventDefault(); handleSelect(t.ticker); }}
              onMouseEnter={() => setSelectedIdx(i)}
              style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px',
                cursor: 'pointer', borderBottom: '1px solid var(--color-border-subtle)',
                background: i === selectedIdx ? 'var(--imperial-purple-glow)' : 'transparent',
              }}
            >
              <span style={{ fontWeight: 700, fontFamily: 'var(--font-mono)', fontSize: 13, minWidth: 60 }}>
                {t.ticker}
              </span>
              <span style={{ fontSize: 11, color: 'var(--color-text-secondary)', flex: 1 }}>
                {t.sector}{t.subsector ? ` / ${t.subsector}` : ''}
              </span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--color-text-secondary)' }}>
                ${t.price}
              </span>
              <span style={{
                fontSize: 10, fontWeight: 600, padding: '2px 6px', borderRadius: 4,
                background: t.lt_score >= 50 ? 'var(--color-success-bg)' : 'var(--color-bg)',
                color: t.lt_score >= 50 ? 'var(--color-success)' : 'var(--color-text-tertiary)',
              }}>
                LT {t.lt_score}
              </span>
              <span style={{
                fontSize: 10, fontWeight: 600, padding: '2px 6px', borderRadius: 4,
                background: t.opt_score >= 40 ? 'var(--imperial-purple-glow)' : 'var(--color-bg)',
                color: t.opt_score >= 40 ? 'var(--imperial-purple)' : 'var(--color-text-tertiary)',
              }}>
                Opt {t.opt_score}
              </span>
              <button
                onMouseDown={e => { e.preventDefault(); e.stopPropagation(); handleAnvilSelect(t.ticker); }}
                style={{
                  border: 'none', background: 'none', cursor: 'pointer',
                  fontSize: 11, color: 'var(--color-text-tertiary)', padding: '2px 4px',
                }}
                title="Open in Anvil"
              >
                {'⚔️'}
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
