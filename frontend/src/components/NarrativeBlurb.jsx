/**
 * QUAEST.TECH — Narrative renderers (shared, single source of truth)
 *
 * One module owns every way the LT/ST narrative is shown:
 *   - StorySection : the canonical LT / ST story line (icon, title, prose,
 *     "as of" date, optional Explain term). Used by BOTH presentations below.
 *   - StoryPanel   : the full, always-open Card with fresh/stale chip + sources.
 *     Surfaced on the Ticker deep-dive page (caller fetches and passes the
 *     `narrative` prop, exactly as before — moved here verbatim so there is no
 *     visual or behavior change, just a single home for the markup).
 *   - NarrativeBlurb : a compact, collapsible "Why this?" affordance for the
 *     Pactum play cards and Conviction rows (and therefore the World building
 *     panels, which reuse those pages). Lazy — fetches only on expand — and
 *     cached per-ticker so re-expanding (or opening the same name elsewhere)
 *     never refetches.
 *
 * Backed by the live, read-only GET /narrative/{ticker} via fetchNarrative.
 * No scoring, no writes, no new endpoint.
 */

import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import { Card } from './ui/Card';
import { Explain } from './ui/Explain';
import { Scroll, Ruler, Zap, ChevronDown, ChevronUp, ChevronRight } from './ui/icons';
import { fetchNarrative } from '../api/endpoints';
import { fmtDateOnly } from '../utils/formatters';

// ── Shared per-ticker cache (lazy + de-duped across every surface) ──
//   missing key  -> never fetched
//   object       -> narrative payload, or { status: 'generating' }
//   null         -> fetched and errored/empty (hide quietly)
const _cache = new Map();
const _inflight = new Map();

// Exposed for tests / debugging; not used by render paths.
export function _clearNarrativeCache() { _cache.clear(); _inflight.clear(); }

function loadNarrative(ticker) {
  if (_cache.has(ticker)) return Promise.resolve(_cache.get(ticker));
  if (_inflight.has(ticker)) return _inflight.get(ticker);
  const p = fetchNarrative(ticker)
    .then(d => { const v = d ?? null; _cache.set(ticker, v); _inflight.delete(ticker); return v; })
    .catch(() => { _cache.set(ticker, null); _inflight.delete(ticker); return null; });
  _inflight.set(ticker, p);
  return p;
}

// ── Canonical story line (the single renderer reused everywhere) ──
export function StorySection({ title, term, Icon, text, generatedAt, tz }) {
  return (
    <div style={{ flex: 1, minWidth: 0 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 8 }}>
        {Icon && <Icon size={13} />}
        <span style={{ fontSize: 12, fontWeight: 700, letterSpacing: 0.4, textTransform: 'uppercase', color: 'var(--color-text-secondary)' }}>{title}</span>
        {term && <Explain term={term} />}
      </div>
      <p style={{ fontSize: 13, lineHeight: 1.6, margin: 0, color: 'var(--color-text-primary)' }}>
        {text || <span style={{ color: 'var(--color-text-tertiary)' }}>No story yet.</span>}
      </p>
      {generatedAt && (
        <div style={{ fontSize: 10, color: 'var(--color-text-tertiary)', marginTop: 6 }}>
          as of {fmtDateOnly(generatedAt, tz)}
        </div>
      )}
    </div>
  );
}

// ── Full panel (Ticker page). Presentational: caller passes `narrative`. ──
export function StoryPanel({ narrative, tz }) {
  // Nothing fetched yet (initial mount) — render nothing rather than a flash.
  if (!narrative) return null;

  // 202 from the API: the mill pipeline hasn't drafted this ticker yet.
  if (narrative.status === 'generating') {
    return (
      <Card style={{ padding: 20 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, margin: '0 0 10px', display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <Scroll size={15} /> Story
        </h3>
        <p style={{ fontSize: 12, color: 'var(--color-text-tertiary)', margin: 0 }}>
          Generating narrative… check back shortly.
        </p>
      </Card>
    );
  }

  const sources = narrative.sources || [];
  const lowConfidence = narrative.confidence && narrative.confidence !== 'ok';
  const fresh = !narrative.stale;
  const dotColor = fresh ? 'var(--color-success)' : 'var(--color-warning)';

  return (
    <Card style={{ padding: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 14 }}>
        <h3 style={{ fontSize: 14, fontWeight: 700, margin: 0, display: 'inline-flex', alignItems: 'center', gap: 8 }}>
          <Scroll size={15} /> Story
        </h3>
        <span
          title={fresh ? 'Fresh' : 'Stale — refresh pending'}
          style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 10, fontWeight: 600, color: 'var(--color-text-tertiary)' }}
        >
          <span style={{ width: 8, height: 8, borderRadius: '50%', background: dotColor, display: 'inline-block' }} />
          {fresh ? 'Fresh' : 'Stale'}
        </span>
      </div>

      {lowConfidence && (
        <div style={{ fontSize: 11, color: 'var(--color-warning)', marginBottom: 12, padding: '6px 10px', borderRadius: 6, background: 'var(--color-bg)', borderLeft: '3px solid var(--color-warning)' }}>
          Low-confidence note — grounded on system signals only; external claims were withheld.
        </div>
      )}

      <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
        <StorySection title="Long-term" term="lt_score" Icon={Ruler} text={narrative.lt_story} generatedAt={narrative.lt_generated_at} tz={tz} />
        <StorySection title="Short-term" term="opt_score" Icon={Zap} text={narrative.st_story} generatedAt={narrative.st_generated_at} tz={tz} />
      </div>

      {sources.length > 0 && (
        <div style={{ marginTop: 16, paddingTop: 12, borderTop: '1px solid var(--color-border-subtle)' }}>
          <div style={{ fontSize: 10, fontWeight: 700, letterSpacing: 0.4, textTransform: 'uppercase', color: 'var(--color-text-tertiary)', marginBottom: 6 }}>Sources</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {sources.map((s, i) => (
              <a
                key={i}
                href={s.url}
                target="_blank"
                rel="noopener noreferrer"
                style={{ fontSize: 11, color: 'var(--imperial-purple-light, var(--imperial-purple))', textDecoration: 'none' }}
              >
                {s.title || s.url}
              </a>
            ))}
          </div>
        </div>
      )}
    </Card>
  );
}

// ── Compact collapsible blurb (Pactum cards, Conviction rows) ──
export function NarrativeBlurb({ ticker, prefer = 'st', tz }) {
  const navigate = useNavigate();
  const sym = ticker?.toUpperCase();
  const [open, setOpen] = useState(false);
  const [data, setData] = useState(() => (sym ? _cache.get(sym) : undefined));
  const [loading, setLoading] = useState(false);

  const onToggle = useCallback(() => {
    if (!sym) return;
    const next = !open;
    setOpen(next);
    if (!next) return;
    if (_cache.has(sym)) { setData(_cache.get(sym)); return; }
    setLoading(true);
    loadNarrative(sym).then(v => { setData(v); setLoading(false); });
  }, [sym, open]);

  if (!sym) return null;

  // Fetched and errored/empty: hide quietly so the host card is untouched.
  const resolved = data !== undefined ? data : _cache.get(sym);
  if (open && !loading && resolved === null) return null;

  const generating = resolved && resolved.status === 'generating';
  const lowConfidence = resolved && resolved.confidence && resolved.confidence !== 'ok';

  const lt = resolved && !generating && resolved.lt_story
    ? <StorySection key="lt" title="Long-term" Icon={Ruler} text={resolved.lt_story} generatedAt={resolved.lt_generated_at} tz={tz} />
    : null;
  const st = resolved && !generating && resolved.st_story
    ? <StorySection key="st" title="Short-term" Icon={Zap} text={resolved.st_story} generatedAt={resolved.st_generated_at} tz={tz} />
    : null;
  const ordered = prefer === 'lt' ? [lt, st] : [st, lt];

  return (
    <div style={{ marginTop: 10, borderTop: '1px solid var(--color-border-subtle)', paddingTop: 10 }}>
      <button
        onClick={(e) => { e.stopPropagation(); onToggle(); }}
        style={{
          display: 'inline-flex', alignItems: 'center', gap: 6, background: 'none', border: 'none',
          padding: 0, cursor: 'pointer', color: 'var(--color-text-secondary)', fontSize: 11,
          fontWeight: 700, fontFamily: 'inherit', letterSpacing: 0.2,
        }}
      >
        <Scroll size={13} /> Why this?
        {open ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
      </button>

      {open && (
        <div style={{ marginTop: 10 }} onClick={(e) => e.stopPropagation()}>
          {loading && (
            <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>Reading the record…</div>
          )}
          {!loading && generating && (
            <div style={{ fontSize: 11, color: 'var(--color-text-tertiary)' }}>Generating narrative… check back shortly.</div>
          )}
          {!loading && resolved && !generating && (
            <>
              {lowConfidence && (
                <div style={{ fontSize: 10, color: 'var(--color-warning)', marginBottom: 8, padding: '5px 8px', borderRadius: 6, background: 'var(--color-bg)', borderLeft: '3px solid var(--color-warning)' }}>
                  Low-confidence note — grounded on system signals only; external claims were withheld.
                </div>
              )}
              <div style={{ display: 'flex', gap: 18, flexWrap: 'wrap' }}>
                {ordered}
              </div>
              <button
                onClick={(e) => { e.stopPropagation(); navigate(`/ticker/${sym}`); }}
                style={{
                  marginTop: 10, display: 'inline-flex', alignItems: 'center', gap: 3, background: 'none',
                  border: 'none', padding: 0, cursor: 'pointer', fontSize: 10, fontWeight: 700,
                  color: 'var(--imperial-purple-light, var(--imperial-purple))', fontFamily: 'inherit',
                }}
              >
                full story <ChevronRight size={11} />
              </button>
            </>
          )}
        </div>
      )}
    </div>
  );
}
