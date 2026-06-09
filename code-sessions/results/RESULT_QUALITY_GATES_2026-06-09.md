# RESULT — LT Quality Gates (PIT-validated eligibility + conviction pipeline)

**Date:** 2026-06-09 · **Analyst:** SESSION-QUALITY-GATES (Claude Code, architect-grade)
**Status:** research + draft implementation — **NO deploy, NO merge, NO live DB writes, NO component-weight changes.**
**Research host:** `mill` (`~/lt-recon-data/` PIT corpus, `~/mill-local-edits/lt_reconstruct.py`). **PR:** MacBook repo, branch `feat/quality-gates`.

---

## TL;DR

Validated 10 candidate gates on the decade PIT panel (427 names × 127 monthly snapshots 2014-12..2025-06, two regime halves split 2021-04). **Most proposed gates do NOT earn an alpha case** — and that's the honest headline. The gates' real value is **risk hygiene + left-tail control + value-trap defense at ~0 aggregate return cost**, not a return boost.

- **EARNS the strict OOS bar** (worse mean and/or worst-decile for flagged names in BOTH regimes, sane flag rate): **B3 secular-decline** down-weight; **A5 interest-coverage <1.0** hard-exclude.
- **Return-NEUTRAL risk-controls (built, but not alpha):** **B1 organic-growth normalization** (Rule-of-40 IC is 3× weaker on M&A names; capping it is free) and **B2 interest-corroboration cap** (the testable proxy did *not* improve returns — beaten-down high-LT names mean-revert *up*). Implemented per the standing cap-don't-kill decisions, labeled non-alpha.
- **Hygiene-only (pre-decided, survivorship-unmeasurable):** A1 price<$5 / A2 cap<$300M / A3 dollar-vol<$2M — live-capital eligibility; the panel can't validate them because the 46 delisted names are already excluded.
- **REJECTED with numbers:** A4 Altman-Z, A6 net-debt/EBITDA, A7 accumulated-deficit.
- **The honest tension:** the two gates with real OOS evidence (B3, A5) do **not** catch GEN; the two that fix GEN (B1, B2) are the return-neutral ones. GEN is deflated by the pipeline, but on this data that deflation buys risk control, not alpha.

---

## 1. Frame & method

Built an enriched panel (`qg_panel.py`, 52,552 records) replicating `lt_reconstruct.py` **byte-for-byte** (verified: valuation IC@12 +0.0551, rule_of_40 +0.0017 with h1 +0.0745 / h2 −0.0723, lt_score +0.0151 — identical to RESULT_LT_RECONSTRUCTION §7.2), and additionally recording every gate input PIT-faithfully (`filed ≤ D`, as-filed annual). New SEC concepts pulled: PaymentsToAcquireBusinesses, Goodwill (+step), Assets/Liabilities/Current, RetainedEarnings, InterestExpense, D&A, plus price-derived dollar-volume and perf_1y.

**High-LT bucket** = top lt_score quintile per snapshot (the would-be High-conviction names). **Metric per gate:** flag rate, and flagged-vs-unflagged forward-12mo **mean** and **worst-decile** (left tail), in **both sub-periods** independently. Per RESULT §7 honesty rules, judged by **sign-consistency across the two regime halves + left-tail**, not raw t-stats (overlapping windows inflate them).

**Survivorship ceiling (stated up front):** the panel excludes the 46 delisted names (no yfinance prices) — **survivorship recovery rate = 0** (no delisted-price archive was available; recovering them needs Sharadar/CRSP). So Tier-A solvency/liquidity gates' true payoff (avoiding the dead names) is **structurally unmeasurable here** — on survivors the distress-flagged names often look fine or even rebound. `dead(≤−50%)` is used only as a survivor proxy.

---

## 2. Phase 1 — every candidate gate, both sub-periods

High-LT bucket fwd12 **mean / worst-decile** (`m / b10`), UNFLAGGED (keep) vs FLAGGED. A=2014-21, B=2021-25.

### Tier A — hard-exclude candidates

| Gate | flag% (of applic.) | A keep → flagged | B keep → flagged | verdict |
|---|---|---|---|---|
| A1 price < $5 | 0.5% | +20.1/−28.4 → **+133/+7.5** (n=46) | (n=0) | survivorship artifact — flagged *rebound*; **hygiene-only** |
| A2 mcap < $300M | 0.4% | +20.9/−28.4 → +71/−14.5 | +9.0/−39.0 → +2.9/−23.2 | not worse both; survivor-biased; **hygiene-only** |
| A3 dollar-vol < $2M | 0.3% | +20.9/−28.3 → +41/+17 | +9.0/−39.2 → −11.6/−24.1 | mixed; **hygiene-only** (investability) |
| A4 Altman-Z < 1.8 | **46.8%** | −5.1 mean / −5.3 tail | −0.6 / **+2.5** | **REJECT** — absurd flag rate, regime-inconsistent tail |
| A4′ Altman-Z < 1.0 | 26.4% | tail −5.4 | tail **+7.5** | **REJECT** — still 26%, sign-flips by regime (asset-light mis-calibration) |
| A5 interest-cov < 1.5 | 11.4% | tail −5.0 | tail −1.6 | tail worse both → candidate |
| **A5′ interest-cov < 1.0** | **8.9%** | tail **−2.1** | tail **−2.6** | **EARNS** — worse tail BOTH regimes, sane flag rate |
| A6 net-debt/EBITDA >5 | 37.5% | mean +8.8 | mean −0.4 | **REJECT** — 37% flag, inconsistent |
| A7 accumulated deficit | 18.5% | mean **+5.9** | mean **+5.8** | **REJECT** — flagged did *better* both regimes (wrong sign) |

### Tier B — conviction modifiers

| Gate | flag% | A keep → flagged | B keep → flagged | verdict |
|---|---|---|---|---|
| **B3 secular-decline** (3y rev-CAGR<2% & op-margin eroding) | 12.0% | mean **−6.8**, tail −0.8 | mean **−4.6**, tail **−2.7** | **EARNS** — worse mean AND tail BOTH regimes |
| B2 corroboration (perf_1y ≤ 0) | 32.8% | mean **+13.2**, tail −8.5 | mean **+7.5**, tail −0.1 | does **not** earn on returns (flagged *outperform* on mean) |
| B1 M&A flag (as a return predictor) | 21.7% | mean −2.0, tail +2.5 | mean +1.9, tail +3.0 | M&A status alone does **not** predict returns |

**B1 organic-normalization evidence (Rule-of-40 IC@12, M&A vs organic cohort):**
- Regime A: **M&A +0.0170 vs organic +0.0551** — Rule-of-40 carries 3× less information on acquirers.
- Regime B: M&A −0.0309 vs organic −0.0450 — both negative (R40 broadly fails in B, per RESULT §7).
→ The gaudy M&A Rule-of-40 is largely noise. Capping its board credit is justified as **noise removal**.

**B2 conviction-cap evidence (High slice, all vs corroborated-only):**
- A: all mean +20.9 / tail −28.3 → corroborated-only +18.3 / −26.6 (mean **down**, tail slightly better)
- B: all +9.0 / −39.2 → corroborated-only +7.3 / −39.2 (mean **down**, tail flat)
→ Capping uncorroborated names **lowers** the High slice's average return (deep-value mean-reversion). Only a marginal one-regime tail benefit. **B2's return case fails on the one signal we can test.** Its 3 other live signals (sentiment/whale/insider) are absent from the historical corpus → untestable.

---

## 3. Phase 2 — earned/rejected + simulations

**Organic-normalization simulation** (cap M&A Rule-of-40 credit, re-rank high-LT bucket): aggregate impact ≤0.2% mean and ≤0.8% tail either way, both regimes; removes ~270–370 M&A names from the top quintile; composite Q5−Q1 essentially unchanged (A −1.37→−1.58, B −4.78→−4.89). → **return-and-tail-neutral.** Earns its place only as a value-trap de-rater at no cost, NOT as alpha.

**Combined earned-gate pipeline on the high-LT bucket** (Tier-A distress exclude + B3 secular cap + B1 normalization): A mean +20.9→+20.1 (Δ−0.8), tail −28.3→−27.0 (Δ**+1.3**); B mean +9.0→+8.8 (Δ−0.2), tail −39.2→−39.3 (Δ−0.1). → modest left-tail tightening in regime A, return-neutral overall.

**No in/out overfitting gap:** the earned gates are hand-set economic thresholds (not fit to in-sample IC), so the failure mode that killed the naïve IC-reweight (RESULT §7.5) does not apply; they're validated for cross-regime sign-consistency.

### Earned vs Rejected (final)

| Gate | tier | status | basis |
|---|---|---|---|
| **B3 secular-decline** | B down-weight | **EARNS (alpha-relevant)** | worse mean+tail both regimes |
| **A5 interest-coverage <1.0** | A exclude | **EARNS (left-tail/solvency)** | worse tail both regimes, 8.9% flag |
| B1 organic normalization | B down-weight | **BUILD — risk-control** | R40 noise on M&A; return-neutral; fixes GEN #1 |
| B2 corroboration cap | B cap | **BUILD — risk-control** | no return alpha on testable signal; cap-don't-kill (standing decision); fixes GEN #2 |
| A1/A2/A3 liquidity | A exclude | **BUILD — hygiene** | pre-decided live-capital floors; survivorship-unmeasurable |
| A4 Altman-Z | — | **REJECT** | 26–47% flag, regime-inconsistent, asset-light mis-calibration |
| A6 net-debt/EBITDA | — | **REJECT** | 37% flag, inconsistent |
| A7 accumulated-deficit | — | **REJECT** | flagged outperformed both regimes (wrong sign) |

---

## 4. Two-stage pipeline (`api/core/quality_gates.py`)

Pure **post-processor**, isolated from the raw LT/Opt component scores (so it never collides with the Valuation/options weight work — those remain separate tasks). Every gate fires **only when its input is present** (graceful degradation; absent data never silently drops a name).

1. **`evaluate_eligibility(row)` — Tier A hard-exclude:** price<$5, cap<$300M, dollar-vol<$2M, interest-coverage<1.0. An excluded name leaves the board.
2. **`conviction_modifiers(row)` — Tier B cap-don't-kill:** B1 caps M&A Rule-of-40 board credit at 15/25; B3 subtracts 8 board pts for organic secular decline; B2 caps the tier below High without ≥1 corroborating signal. Returns `(lt_penalty, conviction_penalty, tier_cap, reasons)`. **Raw lt_score/opt_score and their breakdowns are read, never mutated.**
3. **`gated_tier(combined, assessment)`** → HIGH/SOLID/WATCH respecting the cap.

**Wired (stack-aware, per the brief):**
- **LT board (`/buy-zone`)** — full Tier A + Tier B; ranks by the gate-deflated `lt_board_score`; tier respects the corroboration cap.
- **Options board (`/killer-plays`)** — **Tier-A eligibility ONLY** (liquidity/solvency); no quality/secular/corroboration gates on tactical options, as required.

**Live now vs scanner follow-up (graceful no-op until persisted):** ACTIVE on today's `scores` schema: A1 price, A2 market_cap_b, B2 corroboration (sentiment_bull_pct / whale_score / insider_buys_30d / perf_3m), and B1 Rule-of-40 read from `lt_breakdown`. NEEDS a small scanner addition before activating: `dollar_volume` (close×averageVolume), `interest_coverage` (EBIT/interest_expense), `acquisition_flag` (goodwill-step / shares-growth / business-acquisition cash-flow), `rev_cagr_3y` + `op_margin_delta_3y` (multi-year trend), optional `perf_1y`. **Recommended backend follow-up task**, out of scope here (no DB schema/scanner changes shipped in this PR beyond reading existing columns).

---

## 5. GEN before/after trace (`qg_gen.py`; GEN not in the PIT corpus — uses the brief's row)

| step | result |
|---|---|
| raw lt_score | **91.5 (UNCHANGED — Tier B isolated from raw components)** |
| Tier A eligibility | price $28, cap $15B, cov 4.0× → **ELIGIBLE** (passes hygiene — surgical, not a junk filter) |
| Tier B organic-normalization | M&A-flagged (acq 12%rev, goodwill-step 25%rev) → Rule-of-40 credit 25 → 15 (**−10 board pts**) |
| Tier B corroboration cap | sentiment 0 / whale 0 / insider 0 / perf_1y −13% → **capped below High** |
| **conviction-adjusted board score** | **91.5 → 81.5, tier "Solid/capped"** → GEN no longer tops a conviction-ranked board |

**Honest caveat (not a hard-code):** on a board sorted by **raw lt_score**, GEN still ranks high — only the out-of-scope **Valuation reweight** moves the raw score. The gates move **conviction**, which is the correct lever for the tiered-enforcement decision. GEN is deflated by the validated rule mechanics (M&A R40 normalization + corroboration cap), not by any GEN special-case.

---

## 6. Tests & verification

`api/tests/test_quality_gates.py` — **17 passing**: Tier-A exclusion fixtures (price/cap/coverage/dollar-vol), Tier-B organic-normalization fixture (M&A cap + organic no-op + derived-flag + graceful-absent), secular-decline fixture, corroboration cap/allow + cap-don't-kill, the GEN end-to-end trace, and a **buy-zone endpoint integration** test (sub-$5 excluded, uncorroborated capped to SOLID, corroborated reaches HIGH). Module + router `py_compile`-clean.

Full suite: **95 passed**, 2 failed — both (`test_killer_plays_fields`) are **pre-existing on `main`** (verified by reverting my router change; unrelated directional-bias fixture drift). `test_schwab_client` errors on collection (pandas not in the venv) — also pre-existing/environment.

---

## 7. Artifacts & out of scope

- Implementation: `api/core/quality_gates.py`, wiring in `api/routers/market.py`, tests `api/tests/test_quality_gates.py`.
- Analysis (reproducible): `code-sessions/quality-gates-analysis/{qg_panel,qg_sanity,qg_analyze,qg_refine,qg_gen}.py` (run on mill against `~/lt-recon-data/`).
- **OUT OF SCOPE (untouched):** deploy/merge, live DB writes, LT/Opt component-weight changes (the Valuation reweight + options reweight are separate tasks — gates modify eligibility + conviction only), restated fundamentals (as-filed only), the signals DB-prune ops task.
- **Follow-up:** the scanner additions in §4 to fully activate A3/A5/B1/B3 on live data, and a delisted-price archive to close the survivorship ceiling behind the Tier-A solvency gates.

**Draft PR:** `feat/quality-gates` (link in PR).
