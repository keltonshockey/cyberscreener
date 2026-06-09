/**
 * QUAEST.TECH — text sanitizers
 * The backend still emits some emoji-prefixed strings (reason text, catalyst
 * labels, direction labels). Until those are stripped at generation
 * (backend follow-up: scanner.py / routers/market.py), we strip them on
 * display so the UI honors the "zero emoji" rule.
 */

// Broad emoji + symbol ranges (pictographs, dingbats, arrows, flags, VS16).
const EMOJI_RE =
  /[\u{1F000}-\u{1FAFF}\u{2600}-\u{27BF}\u{2B00}-\u{2BFF}\u{2190}-\u{21FF}\u{2300}-\u{23FF}\u{25A0}-\u{25FF}\u{1F1E6}-\u{1F1FF}\u{FE0F}\u{200D}]/gu;

/** Remove every emoji/pictograph from a string, collapse the leftover space. */
export function stripEmoji(s) {
  if (typeof s !== 'string') return s;
  return s.replace(EMOJI_RE, '').replace(/\s{2,}/g, ' ').trim();
}
