/**
 * QUAEST.TECH -- ExperimentalBanner (single source of truth, SESSION-V3C)
 *
 * Gate-verdict banner for every demoted play/conviction surface (D2,
 * 2026-08-10). Rendered on the /experimental index, each demoted page, and
 * around the killer-plays / buy-zone widgets on Basilica.
 *
 * Content strategy is progressive enhancement with NO hard dependency on the
 * /evidence/latest endpoint (owned by a sibling session): we try one fetch,
 * and if it returns parseable JSON carrying gate.verdict we render the live
 * verdict + read date. Any failure -- network error, 404, SPA-shell HTML,
 * missing fields -- falls back SILENTLY to the static pre-registered text.
 * No console output, no error UI, ever.
 */
import { useState, useEffect } from 'react';
import { AlertTriangle } from './ui/icons';

// Static registered fallback -- shipped verbatim from the 2026-08-02 gate read.
export const GATE_FALLBACK_TEXT =
  'Pre-registered forward test result: FAIL (2026-08-02 read, cohort C n=179 decided, win rate 22.4%). These surfaces are experimental telemetry, not recommendations.';

// Module-level cache: at most ONE fetch per page load no matter how many
// banners mount (index page + widgets can show several at once).
let _gatePromise = null;

function loadGate() {
  if (!_gatePromise) {
    _gatePromise = (async () => {
      try {
        const res = await fetch('/evidence/latest', { headers: { Accept: 'application/json' } });
        if (!res.ok) return null;
        // In prod an unknown path returns the SPA shell (HTML, status 200);
        // the content-type check plus the json() try/catch keeps that silent.
        const ct = res.headers.get('content-type') || '';
        if (!ct.includes('json')) return null;
        const data = await res.json();
        const verdict = data && data.gate && data.gate.verdict;
        if (typeof verdict === 'string' && verdict.trim()) return data.gate;
        return null;
      } catch {
        return null; // silent by design -- fallback text covers it
      }
    })();
  }
  return _gatePromise;
}

/** Test/dev hook: forget the cached fetch so the next mount retries. */
export function _clearGateCache() { _gatePromise = null; }

function gateDate(gate) {
  const d = gate.read_date || gate.date || gate.as_of || gate.evaluated_at || null;
  return typeof d === 'string' && d.trim() ? d : null;
}

const wrapStyle = {
  display: 'flex',
  alignItems: 'flex-start',
  gap: 10,
  padding: '10px 14px',
  border: '1px solid var(--color-warning, #b58a3c)',
  borderLeft: '3px solid var(--color-warning, #b58a3c)',
  borderRadius: 'var(--radius-md, 6px)',
  background: 'var(--color-warning-bg, rgba(181, 138, 60, 0.08))',
  color: 'var(--color-text-secondary)',
  fontSize: 12,
  lineHeight: 1.55,
};

export function ExperimentalBanner({ style }) {
  const [gate, setGate] = useState(null);

  useEffect(() => {
    let on = true;
    loadGate().then(g => { if (on && g) setGate(g); });
    return () => { on = false; };
  }, []);

  // Fallback renders immediately; a live verdict upgrades it in place.
  let text = GATE_FALLBACK_TEXT;
  if (gate) {
    const date = gateDate(gate);
    text =
      `Pre-registered gate verdict: ${String(gate.verdict).toUpperCase()}` +
      (date ? ` (${date} read)` : '') +
      '. These surfaces are experimental telemetry, not recommendations.';
  }

  return (
    <div style={{ ...wrapStyle, ...style }} role="note" aria-label="Experimental gate verdict">
      <AlertTriangle size={15} style={{ flexShrink: 0, marginTop: 1, color: 'var(--color-warning, #b58a3c)' }} />
      <div>
        <span style={{ fontWeight: 700, letterSpacing: '0.08em', color: 'var(--color-warning, #b58a3c)', marginRight: 8 }}>
          EXPERIMENTAL
        </span>
        {text}
      </div>
    </div>
  );
}
