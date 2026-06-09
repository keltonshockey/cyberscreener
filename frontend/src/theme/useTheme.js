/**
 * QUAEST.TECH — theme control.
 * Dark "Imperial Twilight" is the hero (default). Light = museum daylight.
 * Persists to localStorage and reflects on <html data-theme>.
 */
import { useCallback, useEffect, useState } from 'react';

const KEY = 'quaest-theme';

function read() {
  try {
    // Deep-linkable override: ?theme=light|dark (also persists it).
    const q = new URLSearchParams(window.location.search).get('theme');
    if (q === 'light' || q === 'dark') {
      try { localStorage.setItem(KEY, q); } catch { /* ignore */ }
      return q;
    }
    return localStorage.getItem(KEY) === 'light' ? 'light' : 'dark';
  } catch { return 'dark'; }
}

function apply(theme) {
  const el = document.documentElement;
  if (theme === 'light') el.setAttribute('data-theme', 'light');
  else el.removeAttribute('data-theme');
}

export function useTheme() {
  const [theme, setTheme] = useState(read);

  useEffect(() => { apply(theme); }, [theme]);

  const toggle = useCallback(() => {
    setTheme(t => {
      const next = t === 'light' ? 'dark' : 'light';
      try { localStorage.setItem(KEY, next); } catch { /* ignore */ }
      return next;
    });
  }, []);

  return { theme, toggle };
}
