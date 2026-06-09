/**
 * QUAEST.TECH — signals relevance engine (§6b).
 *
 * Today's raw signals are duplicated, context-blind and emoji-laden, and they
 * carry no stack/polarity/sector metadata. The right fix is to attach that
 * metadata at *generation* (scanner.py / intel/) and gate scoring on it too —
 * flagged as a backend follow-up. Here we do the display-relevance we can now:
 *   • strip emoji
 *   • dedupe by signal identity (show once, with a count + recency)
 *   • infer `stack` (lt / options / both) and hide cross-stack noise
 *   • infer `polarity` (tailwind / headwind / event)
 *   • apply a sector-context gate (threat/demand only helps cyber vendors;
 *     for a breach victim it is a headwind; otherwise suppressed)
 *   • group into Thesis drivers / Catalysts / Risks
 */
import { stripEmoji } from './text';
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

  // 1. clean + dedupe
  const byKey = new Map();
  for (const s of raw || []) {
    const text = stripEmoji(s.signal_text || '');
    if (!text) continue;
    const key = norm(text);
    if (!key) continue;
    const ts = s.scan_ts || s.timestamp || '';
    const prev = byKey.get(key);
    if (prev) {
      prev.count += 1;
      if (ts > prev.ts) { prev.ts = ts; prev.text = text; }
    } else {
      byKey.set(key, { text, impact: s.impact, ts, count: 1 });
    }
  }

  const out = { drivers: [], catalysts: [], risks: [], hidden: 0 };

  for (const sig of byKey.values()) {
    const t = sig.text;
    let stk = inferStack(t);
    let polarity = inferPolarity(sig.impact, t);

    // sector-context gate: threat/demand is only relevant to security vendors.
    if (THREAT_RE.test(t)) {
      if (isBreachVictim) polarity = 'headwind';
      else if (!isCyberVendor) { continue; }       // noise for non-cyber → suppress
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
