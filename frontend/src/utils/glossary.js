/**
 * QUAEST.TECH — glossary for the universal hover-explain system (§6).
 * Write the copy once, use everywhere via <Explain term="...">.
 * Each entry: { title, def (plain language), why (why it matters),
 * how (how it's computed) }. Keep it jargon-free.
 */
export const GLOSSARY = {
  lt_score: {
    title: 'Long-term value score (0–100)',
    def: 'A quality + valuation blend built for buy-and-hold and LEAPS ideas — not short-term timing.',
    why: 'High = a business worth owning for years at a sensible price.',
    how: 'Rule of 40, FCF margin, relative valuation, trend, earnings quality, discount + momentum.',
  },
  opt_score: {
    title: 'Options score (0–100)',
    def: 'Whether there is an asymmetric short-term trade right now.',
    why: 'High = a tactical days-to-weeks setup, independent of long-term quality.',
    how: 'Earnings catalyst, IV context, directional conviction, technical setup, liquidity, asymmetry.',
  },
  rc_score: {
    title: 'Reality check (0–100)',
    def: 'A six-component sanity gate on whether a play is actually tradeable.',
    why: 'Filters out ideas that score well but are impractical to execute.',
    how: 'Trade quality, execution, score alignment, IV context, catalyst, technical.',
  },
  conviction: {
    title: 'Conviction',
    def: 'A single blended ranking score combining options opportunity and long-term value.',
    why: 'Ranks the whole board by how strong the overall case is.',
    how: 'opt_score × 0.6 + lt_score × 0.4, bucketed into High / Solid / Watch tiers.',
  },
  pe: {
    title: 'P/E ratio',
    def: 'Price ÷ trailing earnings per share.',
    why: 'A rough valuation gauge — lower can mean cheaper, but compare within a sector.',
    how: 'Share price divided by trailing twelve-month earnings per share.',
  },
  sma: {
    title: '50-day moving average',
    def: 'The average closing price over the last 50 trading days.',
    why: 'Price above it = uptrend; below = downtrend. A simple trend read.',
    how: 'Mean of the last 50 daily closes, re-computed each day.',
  },
  trend50: {
    title: '50-day trend',
    def: 'The slope from the 200-day average through the 50-day and 20-day to today’s price.',
    why: 'Rising line = constructive momentum; falling = weakening.',
    how: 'A sparkline of long → short moving averages → current price.',
  },
  rsi: {
    title: 'RSI (relative strength index)',
    def: 'A 0–100 momentum oscillator.',
    why: 'Below ~30 = oversold (possible bounce); above ~70 = overbought.',
    how: 'Ratio of average gains to average losses over 14 days.',
  },
  iv_rank: {
    title: 'IV rank',
    def: 'Where current implied volatility sits in its own 1-year range.',
    why: 'Low = options cheap (buy premium); high = options rich (sell premium).',
    how: 'Current IV positioned between its 52-week low and high.',
  },
  iv_estimated: {
    title: 'Estimated IV',
    def: 'Implied volatility inferred from a proxy when a live chain value is unavailable.',
    why: 'Treat IV-driven signals on this name with extra caution.',
    how: 'Backfilled from sector/beta proxies; flagged so you know it is not exact.',
  },
  direction: {
    title: 'Directional lean',
    def: 'The system’s short-term bias: bullish, bearish, or neutral.',
    why: 'Tells you which side a tactical play would take.',
    how: 'Symmetric confluence of RSI, price vs SMAs, volume and whale flow — neutral unless the signed margin clears a threshold.',
  },
  rule_of_40: {
    title: 'Rule of 40',
    def: 'Revenue growth % + free-cash-flow margin %.',
    why: '≥ 40 is the mark of an efficiently growing software/quality business.',
    how: 'Sum of year-over-year growth and FCF margin.',
  },
  fcf_margin: {
    title: 'FCF margin',
    def: 'Free cash flow as a percentage of revenue.',
    why: 'High = the business turns sales into real, reinvestable cash.',
    how: 'Free cash flow divided by revenue.',
  },
  whale: {
    title: 'Whale flow',
    def: 'Unusual options activity that hints at institutional positioning.',
    why: 'Large directional flow can precede a move.',
    how: 'Outsized volume vs open interest and large single-strike premium.',
  },
  sec: {
    title: 'SEC / filings layer',
    def: 'Insider transactions, analyst actions and recent 8-K filing activity.',
    why: 'Corporate events and insider behavior add context to the thesis.',
    how: 'Aggregated from SEC EDGAR Form 4s and 8-K counts.',
  },
  sentiment: {
    title: 'Sentiment layer',
    def: 'News/market sentiment read for the name.',
    why: 'Persistent negative or positive tone can reinforce or fight the thesis.',
    how: 'FinBERT (with a keyword-bag fallback) over recent headlines.',
  },
};

export function getTerm(term) {
  return GLOSSARY[term] || null;
}
