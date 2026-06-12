# Forward-Test Gate — Pre-Registration (2026-06-11)

Written and committed BEFORE the first real closure wave (2026-06-18), so the
late-July and late-September reads cannot be quietly reinterpreted after the
data arrives. This document EXTENDS `api/core/FORWARD_TEST_SEMANTICS.md`
(closure semantics, settlement windows, win/EV definitions, distinct-play
dedup) — nothing here contradicts it. Computation: `api/core/gate_report.py`.
Companion policy: `PROMOTION_CRITERIA.md` (weights change only at scheduled
re-runs, never on interim journal reads).

## 1. Cohorts (the contamination split — resolved as cohort-split, not delete)

The journal spans three scoring regimes. Every row is assigned a cohort,
derived deterministically from immutable entry fields — **no journal row is
ever rewritten** (the tag is computed at read time from `generated_at` and
`score_version`):

| Cohort | Definition (exact) | Regime |
|---|---|---|
| **A** | `generated_at < 2026-06-09 04:00:00 UTC` and not C | legacy IV (median-across-strikes corruption) + legacy bull-biased directional |
| **B** | `generated_at >= 2026-06-09 04:00:00 UTC` and not C | fixed IV (PR #4, deployed 6/8 eve) + symmetric directional (PR #6, deployed ~03:5x UTC 6/9), legacy composite weights |
| **C** | `score_version = 'v2-baseline'` (authoritative, regardless of timestamp) | baseline weights (PR #14) — begins at the first post-baseline-deploy scan |

Boundary note: rows entered on 2026-06-08 after the IV fix but before the
directional fix are deliberately classed **A** (mixed regime → the legacy
cohort; conservative). The B-start timestamp is the PR #6 service restart.

**All gate statistics are reported per cohort and never pooled.** Cohorts A
and B are context only. **Only cohort C gates anything** (live capital,
architecture decisions). A and B win rates appearing better or worse than C
changes nothing — they measured different machines.

## 2. Buckets and metrics

Per cohort, by `entry_conviction` (= 0.6*opt + 0.4*lt as of entry, per
FORWARD_TEST_SEMANTICS §4):

- Context bucket: `< 65` (reported, never gates)
- Gate buckets: **65–75**, **75–85**, **85+**
- Gate aggregate: **>= 65** (the union the pass/fail rules read)

Per bucket per cohort, over **distinct** closed plays (earliest-row dedup per
FORWARD_TEST_SEMANTICS — duplicates never pseudo-replicate):

| Metric | Definition |
|---|---|
| n_decided | distinct closed plays with a decided win/loss |
| n_unresolvable | reported as its own count, never silently dropped |
| win_rate | wins / n_decided |
| 95% CI | Wilson score interval on win_rate (z = 1.96) |
| avg_win / avg_loss | mean realized_return of winners / of losers (plays with known return) |
| payoff_ratio | avg_win / abs(avg_loss) |
| profit_factor | sum(positive returns) / abs(sum(negative returns)) |
| expectancy | mean realized_return |

Small n is **reported, not hidden**: every table row carries its n, and any
read below the powered sample is labeled `DIRECTIONAL, NOT SIGNIFICANT`.

## 3. Pass bar (pre-committed)

The forward test PASSES (per cohort-C gate aggregate, conviction >= 65) only
when ALL THREE hold:

1. **win_rate >= 0.55**
2. **payoff_ratio (avg_win / abs(avg_loss)) >= 1.5**
3. **n_decided >= 384** — the powered sample. Math, shown:
   detecting a true 55% vs the 50% null at alpha = 0.05 (two-sided) needs
   `n = p(1-p) * (z / delta)^2 = 0.25 * (1.96 / 0.05)^2 ≈ 384`.
   (At alpha = 0.01: ~664.) Until n >= 384 every read is **directional,
   not significant** — stated in the report itself, every time.

No interim read, however good, substitutes for the powered sample. At ~80
distinct plays/month this bar is reachable roughly Nov 2026 at the earliest.

## 4. Fail-case rule (pre-committed)

**If cohort C reads win_rate < 0.50 on the gate aggregate (conviction >= 65)
once n_decided >= 80: stop new feature work and re-architect the signal stack
before adding anything.** The weekly report computes and prints this trigger
mechanically (`FAIL RULE TRIGGERED`); it is not subject to reinterpretation,
averaging-in of cohort A/B, or "one more week."

Live capital additionally remains gated on the 250d/500d second-regime
re-runs per PROMOTION_CRITERIA.md, independent of this journal gate.

## 5. Reporting cadence

- Weekly, Sundays (after the Friday expiries settle), starting the first
  Sunday after the 2026-06-18 + 2026-06-22 closure waves (**2026-06-21**;
  effectively meaningful from **2026-06-28**).
- Output: `GATE_READ_<date>.md` (ASCII), one table per cohort + the rule
  evaluations, written by the read-only report script; one-line Pushover
  summary (win rate + n + significance label for cohort C, or the best
  populated cohort until C exists).
- Expected closure waves (from `RESULT_FORWARD_TEST_CLOSURE_2026-06-09.md`):
  12 plays on 6/18, 11 on 6/22, 9 on 7/10, 48 on 7/17 → ~83 distinct by
  late July (cohorts A/B). Cohort C accrues only after the baseline deploy.

## 6. What this pre-registration forbids

- Pooling cohorts in any gate statistic.
- Re-bucketing, re-thresholding, or redefining "win" after a read.
- Treating an underpowered hot streak as a pass (n >= 384 or it does not pass).
- Ignoring the fail rule because A/B "look fine."
- Mutating journal outcomes (the report script opens the DB read-only).
