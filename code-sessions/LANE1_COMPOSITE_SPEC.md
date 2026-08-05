# LANE 1 COMPOSITE SPEC — candidate, 2026-08-05

**Status: CANDIDATE ONLY.** Promotion to the live baseline runs through
`PROMOTION_CRITERIA.md` and nothing else. This document proposes; it does not ship.
No weight, score, or journal row was changed by the analysis behind it.

## The composite

```
LANE1_COMPOSITE = Valuation (growth-adjusted EV/Revenue), 100%
```

**Valuation alone.** Not because nothing else was tested — 10 pre-registered
Chen-Zimmermann predictors were — but because the pre-committed falsifier fired.

## Why not the survivors

Two predictors cleared every statistical bar, and both are genuinely low-turnover:

| predictor | CZ sign | IC @12mo | t | H1 → H2 | OOS Q5−Q1 @12mo | turnover |
|---|---|---|---|---|---|---|
| `Investment` (capex/revenue, negated) | −1 | +0.0602 | +6.70 | +0.0737 → +0.0465 | +0.90% | **1.2%** |
| `NOA` (net operating assets, negated) | −1 | +0.0621 | +5.54 | +0.0419 → +0.0827 | +3.54% | **3.2%** |

They still earn no place, because the equal-weight composite of
`Investment + NOA + Valuation` **underperforms Valuation alone at 12 months**:

| horizon | Valuation alone | Composite | |
|---|---|---|---|
| 6mo | +2.48% | **+3.28%** | composite wins |
| 12mo | **+5.93%** | +4.75% | composite loses |

The falsifier was fixed at **12mo** in the pre-registration (commit `a58ea3f`), before any
predictor return was computed, precisely so that a 6mo win could not be used to rescue a
12mo loss after the fact. 12mo is the horizon Lane 1 exists to serve. The falsifier fires;
the composite ships as Valuation-only.

`Investment` and `NOA` are **nominated for future work**, not discarded: both are
sign-consistent, both clear |t| ≥ 3 at the Bonferroni-adjusted bar across 20 hypotheses,
and both have turnover an order of magnitude inside the 50% cap. A future Lane 1 iteration
may find a construction in which they add value — but not this one, and not by relaxing a
bar after seeing the result.

## Standing caveat (inherited from Milestone C — attaches to everything above)

> The 12-month OOS Valuation quintile premium is **+1.3% to +5.9%**, not the +5.9% June
> headline. 9.7% of the universe exited over the window and their prices are unrecoverable
> from free sources (independently confirmed by SEC's active-registrant map and by Yahoo).
> The lower bound reflects an adverse but unfalsifiable survivorship assumption.

Any promotion decision must be made against the **range**, not the point estimate.

## What this does NOT authorise

- No change to `weights_baseline.json`, no `score_version` bump, no deploy.
- LT baseline membership is already Valuation-100, so this analysis **confirms the current
  live configuration rather than proposing a change to it**.
- Promotion of anything new still requires PROMOTION_CRITERIA.md in full, including
  criterion 3 (survival at the next scheduled 250d/500d regime re-run).
