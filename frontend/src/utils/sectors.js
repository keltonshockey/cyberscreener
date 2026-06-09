/**
 * QUAEST.TECH — sector taxonomy (multi-tag, first-class chips · §4).
 *
 * The backend currently persists a single coarse `sector` (cyber/energy/
 * defense/broad) + a `subsector`. The plan calls for an expanded, multi-tag
 * taxonomy (NVDA = AI + Semis + Tech) driven from the data layer. Until that
 * lands server-side (flagged as a backend follow-up), we derive tags here:
 *  1. a curated overlay for prominent multi-tag names, then
 *  2. a fallback mapping from sector/subsector.
 */

// Expanded taxonomy — order = chip display order.
export const SECTOR_TAGS = [
  'AI', 'Semis', 'Cyber', 'Energy', 'Nuclear', 'Defense',
  'Fintech', 'Space', 'Quantum', 'Biotech',
  'Tech', 'Health', 'Financials', 'Consumer', 'Industrials', 'REITs',
];

// Curated multi-tag overlay for well-known names.
const TICKER_TAGS = {
  NVDA: ['AI', 'Semis', 'Tech'], AMD: ['AI', 'Semis', 'Tech'], AVGO: ['AI', 'Semis', 'Tech'],
  TSM: ['Semis', 'Tech'], MU: ['Semis', 'Tech'], ASML: ['Semis', 'Tech'], INTC: ['Semis', 'Tech'],
  ARM: ['AI', 'Semis', 'Tech'], MRVL: ['AI', 'Semis', 'Tech'], SMCI: ['AI', 'Semis', 'Tech'],
  PLTR: ['AI', 'Defense', 'Tech'], MSFT: ['AI', 'Tech'], GOOGL: ['AI', 'Tech'], META: ['AI', 'Tech'],
  AMZN: ['AI', 'Tech', 'Consumer'], CRWD: ['Cyber', 'AI', 'Tech'], PANW: ['Cyber', 'AI', 'Tech'],
  ZS: ['Cyber', 'Tech'], FTNT: ['Cyber', 'Tech'], OKTA: ['Cyber', 'Tech'], NET: ['Cyber', 'Tech'],
  S: ['Cyber', 'AI', 'Tech'], CYBR: ['Cyber', 'Tech'], GEN: ['Cyber', 'AI'], DDOG: ['Cyber', 'AI', 'Tech'],
  CEG: ['Nuclear', 'Energy'], CCJ: ['Nuclear', 'Energy'], VST: ['Nuclear', 'Energy'], NEE: ['Energy'],
  FSLR: ['Energy'], ENPH: ['Energy'], EQIX: ['REITs', 'Tech'], DLR: ['REITs', 'Tech'],
  LMT: ['Defense'], RTX: ['Defense'], NOC: ['Defense'], GD: ['Defense'], AVAV: ['Defense', 'Space'],
  KTOS: ['Defense', 'Space'], RKLB: ['Space', 'Defense'], LUNR: ['Space'], ASTS: ['Space'],
  V: ['Fintech', 'Financials'], MA: ['Fintech', 'Financials'], PYPL: ['Fintech', 'Tech'],
  SQ: ['Fintech', 'Tech'], COIN: ['Fintech'], HOOD: ['Fintech'], SOFI: ['Fintech', 'Financials'],
  IONQ: ['Quantum', 'Tech'], RGTI: ['Quantum', 'Tech'], QBTS: ['Quantum', 'Tech'],
  LLY: ['Health', 'Biotech'], MRNA: ['Biotech', 'Health'], CRSP: ['Biotech', 'Health'],
  VRTX: ['Biotech', 'Health'], REGN: ['Biotech', 'Health'],
};

const SUBSECTOR_TAGS = {
  'Technology': ['Tech'],
  'Health Care': ['Health'],
  'Financials': ['Financials'],
  'Consumer Disc': ['Consumer'],
  'Consumer Staples': ['Consumer'],
  'Industrials': ['Industrials'],
  'Real Estate': ['REITs'],
  'Energy': ['Energy'],
};

/** Return the de-duplicated tag list for a score row. */
export function tagsFor(row) {
  if (!row) return [];
  const t = TICKER_TAGS[row.ticker];
  if (t) return t;

  const out = [];
  if (row.sector === 'cyber') out.push('Cyber', 'Tech');
  else if (row.sector === 'defense') out.push('Defense');
  else if (row.sector === 'energy') {
    out.push('Energy');
    if (/uran|nuclear/i.test(row.subsector || '')) out.push('Nuclear');
  } else if (row.sector === 'broad') {
    (SUBSECTOR_TAGS[row.subsector] || []).forEach(x => out.push(x));
  }
  return out.length ? [...new Set(out)] : ['Tech'];
}

/** Count rows per tag (for chip badges). */
export function tagCounts(rows) {
  const counts = {};
  for (const r of rows || []) {
    for (const tag of tagsFor(r)) counts[tag] = (counts[tag] || 0) + 1;
  }
  return counts;
}
