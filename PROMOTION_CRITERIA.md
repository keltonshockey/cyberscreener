# Promotion Criteria — Baseline vs Layers (pre-registered 2026-06-11)

This file is the ONLY path by which a scoring component's baseline membership
changes. It exists so that weight decisions are made by pre-registered rule on
out-of-sample evidence — never by eyeballing a quarter of forward data or
re-fitting the regime we just lived through. See `api/core/weights_baseline.json`
for current membership and `DEEP_REVIEW_2026-06-11.md` for the program rationale.

## Definitions

- **Baseline**: components that fund the live `lt_score` / `opt_score`.
  Membership as of 2026-06-11: LT = Valuation (100), Opt = Asymmetry (100).
  The symmetric directional rule (PR #6) picks play direction/labels but is
  unweighted.
- **Layer**: computed and persisted every scan, zero baseline weight,
  user-addable in the UI as an explicitly experimental view.
- **PIT sub-periods**: the two halves of the decade point-in-time corpus
  (2014–2021 and 2021–2025, `RESULT_LT_RECONSTRUCTION_2026-06-08.md`), or for
  options-horizon signals the walk-forward train/test splits used by
  `SIGNAL_ANALYSIS_2026-06-08.md`.
- **Scheduled regime re-runs**: the 250-day and 500-day signal re-runs
  (first due ~late Sept 2026).

## Promotion (layer → baseline)

A layer enters the baseline ONLY when ALL THREE hold, **on data not used to
propose the promotion**:

1. **Significance + consistency**: |IC| with t ≥ 3 at the component's relevant
   horizon, with the SAME sign in both PIT sub-periods (no regime flippers —
   weight by sign-consistency, not IC magnitude; the naive IC-reweight
   overfit is documented in `RESULT_LT_RECONSTRUCTION_2026-06-08.md`).
2. **Economic size**: positive OOS quintile spread (Q5−Q1 of the component
   alone) at the relevant horizon.
3. **Survival**: the signal still clears (1) and (2) at the next scheduled
   regime re-run (250d/500d) after the promotion is proposed.

The proposing analysis must be written down (a RESULT doc in
`code-sessions/results/`) BEFORE the confirming re-run is read.

## Demotion (baseline → layer) — symmetric

A baseline component drops to layer when, at any scheduled re-run, it fails
EITHER the sign-consistency test or the positive OOS spread test at its
horizon. Demotion is executed in the next PR, not debated.

## Weight changes inside the baseline

With a single component per stack this is moot; once ≥2 components share a
stack, weights are set by sign-consistency-weighted allocation, re-evaluated
ONLY at scheduled re-runs. **No mid-cycle weight tweaks** — between re-runs
the config is frozen no matter how the forward journal looks (the journal is
underpowered by construction until ~600 closed plays; see
`DEEP_REVIEW_2026-06-11.md` §sample-size).

## Cohort discipline

Every change to baseline membership or weights bumps `score_version` in
`weights_baseline.json` and therefore the `score_version` stamped on new
forward-test journal rows. Gate reads are per-cohort; historical conviction
values are never rewritten.

## What does NOT count

- In-sample IC on the current regime (that is how technical got 23%).
- Forward-journal win rates below the powered sample (~384 decided plays for
  a 55%-vs-50% claim at p<0.05).
- Visual/narrative appeal of a layer view in the UI.
- Calibration output (`/calibrate` writes weights history for the record;
  it does not touch the baseline while this file stands).
