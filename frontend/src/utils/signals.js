/**
 * QUAEST.TECH — signals relevance engine (§6b).
 *
 * The backend now attaches relevance metadata at generation
 * (core/signals_meta.classify_signal → /signals/:ticker/recent): emoji-free
 * text plus `stack` (lt/options/both), `polarity` (tailwind/headwind/event),
 * `sector_context` (general/cyber-demand/breach-headwind/suppress) and
 * `dedupe_key`. classifySignals prefers those real fields and only falls back to
 * the client heuristics below for rows that predate them. It then:
 *   • dedupes by identity (show once, with a count + recency)
 *   • hides cross-stack noise (options signals in the value view & vice-versa)
 *   • respects the sector-context gate (suppress = not relevant to this stock)
 *   • groups into Thesis drivers / Catalysts / Risks
 */
import { signalIcon } from '../components/ui/icons';

const OPTIONS_RE = /iv rank|implied vol|premium|directional lean|straddle|strangle|theta|p\/c ratio|put\/call|dte|expiry|condor|spread|delta/i;
const LT_RE = /rule of 40|fcf|ev\/rev|valuation|p\/e|dividend|moat|compounder|free cash/i;
const CATALYST_RE = /earnings|8-k|analyst|target|filing|insider|catalyst|squeeze|breakout/i;
const RISK_RE = /risk|headwind|cooling|expensive|burn|weak|below|overbought|dilut|debt|miss/i;
const THREAT_RE = /threat landscape|active threat|demand signal|breach/i;

function inferStack(t) {
  if (OPTIONS_RE.test(t)) return 'options';
  if (LT_RE.test(t)) return 'lt';
  return 'both';
}

function inferPolarity(impact, t) {
  if (impact === 'positive') return 'tailwind';
  if (impact === 'negative') return 'headwind';
  if (RISK_RE.test(t)) return 'headwind';
  if (CATALYST_RE.test(t)) return 'event';
  return 'event';
}

function inferGroup(polarity, t) {
  if (polarity === 'headwind') return 'risks';
  if (CATALYST_RE.test(t)) return 'catalysts';
  return 'drivers';
}

const norm = (t) => t.toLowerCase().replace(/[\d.,$%+-]/g, '').replace(/\s+/g, ' ').trim();

/**
 * @param {Array} raw      signals from /signals/:ticker/recent
 * @param {Object} row     the score row (for sector context)
 * @param {string} stack   'lt' | 'options' — current view
 * @returns {{drivers:[], catalysts:[], risks:[], hidden:number}}
 */
export function classifySignals(raw, row, stack) {
  const isCyberVendor = row?.sector === 'cyber';
  const isBreachVictim = !!row?.breach_victim;

  // 1. dedupe — prefer the backend dedupe_key, else a normalized identity.
  const byKey = new Map();
  for (const s of raw || []) {
    const text = (s.signal_text || '').trim();
    if (!text) continue;
    const key = s.dedupe_key || norm(text);
    if (!key) continue;
    const ts = s.scan_ts || s.timestamp || '';
    const prev = byKey.get(key);
    if (prev) {
      prev.count += 1;
      if (ts > prev.ts) { prev.ts = ts; prev.text = text; }
    } else {
      byKey.set(key, {
        text, impact: s.impact, ts, count: 1,
        stack: s.stack, polarity: s.polarity, sectorContext: s.sector_context,
      });
    }
  }

  const out = { drivers: [], catalysts: [], risks: [], hidden: 0 };

  for (const sig of byKey.values()) {
    const t = sig.text;
    // Prefer backend relevance metadata; fall back to heuristics for legacy rows.
    const stk = sig.stack || inferStack(t);
    let polarity = sig.polarity || inferPolarity(sig.impact, t);

    if (sig.sectorContext) {
      // Backend already gated this signal for THIS stock's context.
      if (sig.sectorContext === 'suppress') continue;  // not relevant → hide + don't score
    } else if (THREAT_RE.test(t)) {
      // Legacy fallback: threat/demand only relevant to security vendors.
      if (isBreachVictim) polarity = 'headwind';
      else if (!isCyberVendor) continue;
      else if (polarity === 'event') polarity = 'tailwind';
    }

    // cross-stack relevance: hide options noise in the value view & vice-versa.
    if (stk !== 'both' && stk !== stack) { out.hidden += 1; continue; }

    const group = inferGroup(polarity, t);
    out[group].push({
      text: t, polarity, count: sig.count, ts: sig.ts,
      Icon: signalIcon(t, sig.impact),
    });
  }

  return out;
}
