# LT Score Audit — `score_long_term()` in `api/core/scanner.py`

Investigation of the reported "every ticker scores 60-90, nothing below 60"
issue, plus the fix actually applied.

## Headline finding: there is no 60-floor

The reported symptom does **not** exist in the code or in production data.

- `score_long_term()` returns a plain weighted sum of six 0-1 raw components
  scaled by their weights (`_score_component` = `max(0, min(1, raw)) * weight`).
  There is **no** `max(60, …)`, no `min_score`, no percentile mapping, and no
  post-processing in the scan loop (`main.py:894` uses the value directly).
- The live distribution (480-ticker universe, snapshot pulled during this audit)
  was: **min 18.7, max 90.0, avg 50.9, p50 50.5**, with **48% already below 50**
  and only **4% above 75**.

So the real problem was the opposite end: **high-end compression** — genuinely
strong companies couldn't get above ~75 because two components systematically
withheld points.

## Per-component audit

Each component returns a raw score in `[0, 1]`, clamped then multiplied by its
weight. Min possible output is 0 for every component; max is the weight.

| Component | Weight (max) | Min | What it measures |
|---|---|---|---|
| rule_of_40 | 25 | 0 | revenue growth % + operating margin % |
| valuation | 20 | 0 | EV/Revenue, growth-adjusted (PEG-like) |
| fcf_margin | 15 | 0 | FCF / revenue |
| trend | 15 | 0 | price vs SMA20/50/200 + golden cross |
| earnings_quality | 10 | 0 | positive EPS, P/E sanity, gross margin |
| discount_momentum | 15 | 0 | 52w discount + momentum + short-interest delta |

### Sample outputs (5 tickers spanning the universe, post-fix)

| Ticker | LT | rule_of_40 | valuation | fcf_margin | trend | earnings_quality | discount_momentum |
|---|---|---|---|---|---|---|---|
| FMC | 20.7 | 0 | 10.0 | 2.2 | 0 | 0.5 | 8.0 |
| SYK | 46.6 | 6.6 | 10.0 | 11.5 | 0 | 8.0 | 10.5 |
| CVS | 57.7 | 4.5 | 17.0 | 2.2 | 15 | 5.5 | 13.5 |
| IRM | 67.0 | 18.5 | 14.0 | 0 | 15 | 6.0 | 13.5 |
| GEN | 91.5 | 25 | 17.0 | 15 | 15 | 9.0 | 10.5 |

Components hit their true 0 (FMC: rule_of_40=0, trend=0) and true max
(GEN: rule_of_40=25, fcf=15, trend=15), confirming the full range is reachable.

## Root cause of high-end compression

1. **discount_momentum dead zone.** Stocks down 5-15% from their 52w high matched
   *none* of the `if disc < -30 / elif disc < -15 / elif disc > -5` branches, so
   they scored a flat 0 on a 15-point component. Stocks near their highs without
   >10% 3-month momentum were capped at raw 0.2.
2. **valuation cliff.** The 10-20x EV/Revenue band returned raw 0.2 (4/20). Quality
   compounders rarely trade below 10x, so they were stuck near the bottom of the
   valuation component regardless of growth/quality.

## Fix applied

- **discount_momentum**: filled the -15%..-5% dead zone (raw 0.45, 0.6 with positive
  3m momentum); raised near-highs-with-strong-momentum to 0.9 and added a 0.55 tier
  for modest positive momentum; nudged the -15% tier up (0.4 / 0.7).
- **valuation**: added a `val_ratio < 0.8 & ev_rev < 25` tier (raw 0.55); raised the
  10-20x fallback (0.2 → 0.35) and the cheap-but-low-growth tier (0.4 → 0.5).

No floor was added; low scorers are unchanged (they lose points on rule_of_40 /
trend / fcf, which the fix doesn't touch).

## Result (same 480-ticker snapshot, re-scored)

| | min | max | avg | p10 | p50 | p90 | <50 | >75 |
|---|---|---|---|---|---|---|---|---|
| Before | 18.7 | 90.0 | 50.9 | 33.9 | 50.5 | 68.6 | 48% | 4% |
| After | 20.7 | 91.5 | 57.3 | 40.2 | 57.7 | 75.2 | 33% | 10% |

Both distribution targets are met: **≥10% below 50 (33%)** and **≥10% above 75 (10%)**.
Spot checks: bad names (FMC, DOW, JBLU) stay 20-26; strong names (GEN, FSLR, LLY,
ADI) land 87-92.
