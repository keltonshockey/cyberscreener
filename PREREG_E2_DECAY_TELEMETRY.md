# PRE-REGISTRATION - E2: decay telemetry + sign-persistence conditioner - 2026-08-10

Written BEFORE any E2 code exists and BEFORE any conditioner statistic has been computed
on any dataset. This document is committed as the FIRST commit on `feat/e2-decay-telemetry`
(provable by commit order, R4 pattern) and mirrored in the kb. Governing program:
`RESEARCH_EPHEMERAL_EDGE_2026-08-06.md` Part B, phase E2. Inherits every standing gate:
draft-PR-only, read-only data access, frozen paths, golden byte-identical, no weight or
scoring change under the 08-02 fail rule. E2 is evaluation infrastructure, explicitly
allowed; nothing here feeds scoring.

## Honest expectations, stated first

E2 confirming nothing is a successful outcome. If sign-persistence does not predict, the
decay telemetry remains a monitoring tool, never a conditioner, and that finding is
reported at full volume.

## What E2 ships (instrument)

Extension of the standing weekly IC harness (`research/harness/ic_report.py`):

1. **Decay slope per component:** rolling mean-IC trend (OLS slope of the daily IC series
   over a trailing window, with CI) at 5d and 21d horizons, reported in the weekly md/csv.
   Telemetry only - no verdict semantics change.
2. **Regime-tagged IC (descriptive telemetry only):** each component's IC split by a
   pre-registered 2-state volatility proxy - state = HIGH when the trailing 21-day
   realized vol of the universe median daily return exceeds its trailing 252-day median,
   else LOW. This proxy is explicitly interim scaffolding to be replaced by E1's jump-model
   states; NO hypothesis is tested on it in E2 and no bar applies to it.
3. **The sign-persistence conditioner test (the ONE tested hypothesis family), below.**

## The tested hypothesis

**H1 (per component):** the sign of a component's trailing 12-month mean IC predicts the
sign of its next-month IC (Ehsani-Linnainmaa factor-momentum logic applied to our own
components). **H0: no predictive sign-persistence.**

### Datasets, in order of power

- **Primary (powered): the decade PIT corpus on mill** (127 monthly snapshots,
  2014-12 to 2025-06, ~413 names/snapshot) for the 6 LT components reconstructable PIT
  (valuation, rule_of_40, fcf_margin, trend, earnings_quality, discount_momentum), using
  the existing `research/lane1/` engine's monthly IC machinery. ~114 usable
  (trailing-12mo, next-month) pairs per component.
- **Secondary (accruing, underpowered TODAY and said so): the live 30-min panel**
  (2026-02 onward) at monthly resolution for all persisted components. At ~6 monthly
  observations this CANNOT clear any bar now; it is registered so the same statistic
  accrues weekly and becomes decision-grade in years, not so it can be read now. Any
  number it produces this cycle is labeled INSUFFICIENT.

### Statistic and bar (fixed now)

For each component: build the monthly IC series; for each month m with >= 12 trailing
months, record predictor s_m = sign(mean IC over months m-12..m-1) and outcome
o_m = sign(IC_m). Test: OLS/t of IC_m on s_m (equivalently, difference in mean next-month
IC after positive vs negative trailing years), Newey-West corrected (lag 3).

- **Bar for SUPPORTED:** |t| >= 3 AND the effect carries the same sign in both halves of
  the sample period AND significance survives Bonferroni across ALL components tested
  (the hypothesis count is printed in the output; expected N = 6 on the PIT primary).
- Everything else: NOISE. Series with < 24 monthly ICs: INSUFFICIENT.
- **Direction fixed now:** the claim is positive persistence (trailing-positive predicts
  next-positive). A significant NEGATIVE (contrarian) result is reported as a FAILED H1,
  not re-labeled as a discovery; it may be nominated for a future prereg only.

### Falsifier / kill condition

If no component clears the bar on the PIT primary, E2's conditioner is DEAD: decay
telemetry ships as monitoring only, and no conditioning logic may be built on it (E3's
design must then exclude sign-persistence gating). This kill is decided by the PIT run
alone; the accruing live panel cannot resurrect it this cycle.

### What would have caught the asymmetry inversion

Stated for the record: applied to the live panel, the conditioner logic (had it existed
with power) is the instrument that would have flagged opt_asymmetry's +0.10 -> -0.17 flip
months before the gate failure. That motivates the telemetry; it is not evidence for H1.

## Discipline

- All reads via `connect_ro` or file-path-loaded `ro.py` (R2 pattern); the harness never
  writes to `cyberscreener.db` and never touches the PIT corpus files (read-only, 0 files
  modified - R3's corpus gate pattern).
- Output stays append-only dated files; previous reports never overwritten.
- No weights, no score_version, no journal writes, no deploy.
- The mill run that produces the PIT-primary result is a supervised/scheduled step
  recorded with artifact evidence (the far-end file, not exit status).
- Multiple-comparisons honesty: every output table prints the hypothesis count.
- Prereg amendments after data contact: not allowed. A new question = a new prereg.
