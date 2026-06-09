/**
 * QUAEST.TECH — sector taxonomy (multi-tag, first-class chips · §4).
 *
 * The backend now emits a maintained multi-tag `sector_tags` per row
 * (core/sector_tags → scores.sector_tags, NVDA = AI + Semis + Tech). `tagsFor`
 * prefers that; the curated overlay + sector/subsector fallback below only cover
 * rows scanned before the column existed (and keep the chip ordering list local).
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

/** Return the de-duplicated tag list for a score row.
 *
 * Prefers the backend-maintained `sector_tags` (now emitted per row from
 * core/sector_tags via /scores/latest); falls back to the curated client map
 * for rows scanned before the column existed. */
export function tagsFor(row) {
  if (!row) return [];

  // Backend taxonomy wins when present (arrives as a JSON string or array).
  let server = row.sector_tags;
  if (typeof server === 'string') {
    try { server = JSON.parse(server); } catch { server = null; }
  }
  if (Array.isArray(server) && server.length) return server;

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
