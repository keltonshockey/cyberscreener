"""
Sign-persistence conditioner statistic - the ONE tested hypothesis family of E2.

Registered in PREREG_E2_DECAY_TELEMETRY.md (commit a5b2c8d, first commit on the
branch, before any of this code existed). The registered statistic, verbatim:

    For each component: build the monthly IC series; for each month m with >= 12
    trailing months, record predictor s_m = sign(mean IC over months m-12..m-1)
    and outcome o_m = sign(IC_m). Test: OLS/t of IC_m on s_m (equivalently,
    difference in mean next-month IC after positive vs negative trailing years),
    Newey-West corrected (lag 3).

    Bar for SUPPORTED: |t| >= 3 AND the effect carries the same sign in both
    halves of the sample period AND significance survives Bonferroni across ALL
    components tested (the hypothesis count is printed in the output; expected
    N = 6 on the PIT primary).
    Everything else: NOISE. Series with < 24 monthly ICs: INSUFFICIENT.
    Direction fixed now: the claim is positive persistence. A significant
    NEGATIVE (contrarian) result is reported as a FAILED H1, not re-labeled.

Implementation notes, none of which weaken the registered bar:

* Newey-West is implemented HERE in numpy (classic Newey-West 1987, Bartlett
  kernel, lag 3, no small-sample correction) because mill's minimal venv has
  pandas + numpy only - no statsmodels. It is pinned against hand-computed
  values in api/tests/test_e2_persistence.py.
* "Significance survives Bonferroni" is read at the significance level the
  registered t-bar itself implies: alpha = two-sided normal p at |t| = 3
  (~0.0027). SUPPORTED therefore requires p_two * N <= alpha, i.e. for N > 1
  the Bonferroni clause BINDS above the raw |t| >= 3 clause (for N = 6 the
  effective t is ~3.51). Reading it at a looser alpha (e.g. 0.05/N -> t ~2.6)
  would make the clause vacuous next to |t| >= 3, which cannot be the
  registered intent.
* p-values use the normal approximation (math.erfc). The registered bar is
  stated on t itself; p enters only through the Bonferroni scaling, and on the
  powered PIT sample (~100 pairs) the normal and t distributions agree to well
  past the third decimal at |t| ~3.5.
* The half-split is on the SAMPLE PERIOD (calendar midpoint of the pair dates),
  not on the observation list - the R2 correction-4 lesson, same as
  `window_midpoint` in ic_report.py and `Panel.midpoint` in lane1.
* "Effect" per half = mean(IC_m | s=+1) - mean(IC_m | s=-1) within the half
  (the prereg's own equivalence: difference in mean next-month IC after
  positive vs negative trailing years = 2 * the OLS slope on s in {-1,+1}).
  A half containing only one predictor sign cannot certify an effect sign, so
  same_sign is False and the bar is not met.
* A degenerate predictor (trailing sign constant over the whole sample) leaves
  the registered statistic uncomputable - no regression slope exists. That is
  reported INSUFFICIENT with an explanatory note, never a fabricated NOISE/t.
* sign(0) = 0: a pair whose trailing mean is exactly zero keeps s_m = 0 in the
  regression (it is a legal regressor value) and is excluded from the
  per-half difference-of-means, which is defined on the +/- groups.

Dependencies: numpy + stdlib only. This module must stay importable on the
minimal weekly venv and on mill.

No conditioning logic anywhere: this module computes and labels. Nothing in it
is imported by any scoring or selection path.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

import numpy as np

# The registered constants. Changing any of these is a prereg amendment, which
# PREREG_E2_DECAY_TELEMETRY.md forbids after data contact.
T_BAR = 3.0
NW_LAG = 3
TRAILING_MONTHS = 12
MIN_MONTHS = 24

# Two-sided normal p at the registered t-bar - the significance level that
# "survives Bonferroni" is measured against (see module docstring).
ALPHA = math.erfc(T_BAR / math.sqrt(2.0))

VERDICT_SUPPORTED = "SUPPORTED"
VERDICT_NOISE = "NOISE"
VERDICT_INSUFFICIENT = "INSUFFICIENT"
VERDICT_FAILED_H1 = "FAILED_H1"


@dataclass
class PersistenceResult:
    component: str
    n_months: int
    n_pairs: int
    beta: float = float("nan")
    se_nw: float = float("nan")
    t_nw: float = float("nan")
    p_two: float = float("nan")
    effect_h1: float = float("nan")
    effect_h2: float = float("nan")
    same_sign: bool = False
    bonferroni_n: int = 1
    p_bonf: float = float("nan")
    verdict: str = VERDICT_INSUFFICIENT
    note: str = ""


def two_sided_p(t: float) -> float:
    """Two-sided normal p-value for a t statistic (normal approximation)."""
    if t != t:
        return float("nan")
    return math.erfc(abs(t) / math.sqrt(2.0))


def newey_west_slope(y, x, lag: int = NW_LAG):
    """
    OLS of y on [1, x] with a Newey-West (1987) HAC standard error on the slope.

    Classic estimator, Bartlett weights w_l = 1 - l/(lag+1), no small-sample
    correction:

        beta = (X'X)^-1 X'y,  e = y - X beta
        S    = sum_t e_t^2 x_t x_t'
               + sum_{l=1..lag} w_l sum_{t>l} e_t e_{t-l} (x_t x_{t-l}' + x_{t-l} x_t')
        V    = (X'X)^-1 S (X'X)^-1
        se   = sqrt(V[1,1]),  t = beta_1 / se

    Returns (beta1, se_nw, t_nw). Pinned against hand-computed values in
    api/tests/test_e2_persistence.py::test_newey_west_matches_hand_computed.
    """
    y = np.asarray(y, dtype=float)
    x = np.asarray(x, dtype=float)
    n = len(y)
    if n != len(x) or n < 3:
        return float("nan"), float("nan"), float("nan")
    X = np.column_stack([np.ones(n), x])
    xtx = X.T @ X
    if np.linalg.matrix_rank(xtx) < 2:
        return float("nan"), float("nan"), float("nan")
    xtx_inv = np.linalg.inv(xtx)
    beta = xtx_inv @ (X.T @ y)
    e = y - X @ beta

    xe = X * e[:, None]                       # rows x_t * e_t
    S = xe.T @ xe                             # lag-0 term
    L = min(lag, n - 1)
    for l in range(1, L + 1):
        w = 1.0 - l / (L + 1.0)
        gamma = xe[l:].T @ xe[:-l]            # sum_t (x_t e_t)(x_{t-l} e_{t-l})'
        S += w * (gamma + gamma.T)

    V = xtx_inv @ S @ xtx_inv
    var1 = float(V[1, 1])
    if not var1 > 0:
        return float(beta[1]), float("nan"), float("nan")
    se = math.sqrt(var1)
    return float(beta[1]), se, float(beta[1]) / se


def build_pairs(months, ics, trailing: int = TRAILING_MONTHS):
    """
    (date, s_m, IC_m) pairs: s_m = sign(mean IC over the `trailing` preceding
    monthly ICs), outcome IC_m. Exactly the registered construction; the first
    `trailing` months seed the predictor and produce no pair.
    """
    pairs = []
    for i in range(trailing, len(ics)):
        window = ics[i - trailing:i]
        s = float(np.sign(np.mean(window)))
        pairs.append((months[i], s, float(ics[i])))
    return pairs


def _half_effect(pairs):
    """Difference in mean outcome IC after positive vs negative trailing sign.

    Returns (effect, ok): ok is False when either sign group is empty, in which
    case no effect sign can be certified for this half.
    """
    pos = [ic for (_d, s, ic) in pairs if s > 0]
    neg = [ic for (_d, s, ic) in pairs if s < 0]
    if not pos or not neg:
        return float("nan"), False
    return float(np.mean(pos) - np.mean(neg)), True


def persistence_test(months, ics, component: str, bonferroni_n: int,
                     trailing: int = TRAILING_MONTHS,
                     min_months: int = MIN_MONTHS) -> PersistenceResult:
    """
    Apply the registered statistic and bar to one component's monthly IC series.

    `months` are the monthly dates (ascending), `ics` the monthly ICs (floats,
    no Nones - callers drop unusable months first). `bonferroni_n` is the size
    of the hypothesis family this component is tested inside; the caller prints
    it in every output table (multiple-comparisons honesty, prereg Discipline).
    """
    months = list(months)
    ics = [float(v) for v in ics]
    n_months = len(ics)

    # Registered: series with < 24 monthly ICs -> INSUFFICIENT.
    if n_months < min_months:
        return PersistenceResult(
            component=component, n_months=n_months, n_pairs=0,
            bonferroni_n=bonferroni_n, verdict=VERDICT_INSUFFICIENT,
            note=f"{n_months} monthly ICs < {min_months} required",
        )

    pairs = build_pairs(months, ics, trailing)
    s_vals = [p[1] for p in pairs]
    o_vals = [p[2] for p in pairs]

    if len(set(s_vals)) < 2:
        # Constant predictor: the registered regression has no slope to
        # estimate. Reported honestly rather than fabricating a statistic.
        return PersistenceResult(
            component=component, n_months=n_months, n_pairs=len(pairs),
            bonferroni_n=bonferroni_n, verdict=VERDICT_INSUFFICIENT,
            note="trailing sign constant across all pairs - effect not estimable",
        )

    beta, se, t = newey_west_slope(o_vals, s_vals, NW_LAG)
    if t != t:  # NaN t: degenerate regression
        return PersistenceResult(
            component=component, n_months=n_months, n_pairs=len(pairs),
            beta=beta, bonferroni_n=bonferroni_n, verdict=VERDICT_INSUFFICIENT,
            note="degenerate regression - t not computable",
        )
    p = two_sided_p(t)
    p_bonf = min(1.0, p * bonferroni_n)

    # Half split on the SAMPLE PERIOD (calendar midpoint of pair dates), never
    # on the observation list.
    d0, d1 = pairs[0][0], pairs[-1][0]
    mid = d0 + (d1 - d0) / 2
    h1 = [p_ for p_ in pairs if p_[0] <= mid]
    h2 = [p_ for p_ in pairs if p_[0] > mid]
    eff1, ok1 = _half_effect(h1)
    eff2, ok2 = _half_effect(h2)
    note = ""
    if not (ok1 and ok2):
        same_sign = False
        which = []
        if not ok1:
            which.append("H1")
        if not ok2:
            which.append("H2")
        note = ("half " + "/".join(which) +
                " has only one trailing-sign group - effect sign not certifiable")
    else:
        same_sign = bool(eff1 != 0 and eff2 != 0 and
                         math.copysign(1, eff1) == math.copysign(1, eff2))

    # The registered bar, clause by clause.
    t_clause = abs(t) >= T_BAR
    bonf_clause = p_bonf <= ALPHA
    bar_met = t_clause and same_sign and bonf_clause

    if bar_met:
        # Direction fixed by the prereg: positive persistence is the claim.
        # A significant negative effect FAILS H1 and is never relabeled.
        verdict = VERDICT_SUPPORTED if beta > 0 else VERDICT_FAILED_H1
    else:
        verdict = VERDICT_NOISE
        misses = []
        if not t_clause:
            misses.append(f"|t|={abs(t):.2f}<{T_BAR:g}")
        if not same_sign and not note:
            misses.append("effect sign flips between halves")
        if t_clause and same_sign and not bonf_clause:
            misses.append(
                f"fails Bonferroni (p*{bonferroni_n}={p_bonf:.5f}>{ALPHA:.5f})")
        if misses and not note:
            note = "; ".join(misses)
        elif misses:
            note += "; " + "; ".join(misses)

    return PersistenceResult(
        component=component, n_months=n_months, n_pairs=len(pairs),
        beta=beta, se_nw=se, t_nw=t, p_two=p, effect_h1=eff1, effect_h2=eff2,
        same_sign=same_sign, bonferroni_n=bonferroni_n, p_bonf=p_bonf,
        verdict=verdict, note=note,
    )


def run_family(series_by_component: dict) -> list[PersistenceResult]:
    """
    Test a whole hypothesis family with a single Bonferroni count.

    `series_by_component` maps component name -> (months, ics). The Bonferroni
    N is the FULL family size (every component submitted), the conservative
    reading of "across ALL components tested" - an INSUFFICIENT sibling never
    loosens the bar for the others.
    """
    n = len(series_by_component)
    return [
        persistence_test(months, ics, component=comp, bonferroni_n=n)
        for comp, (months, ics) in series_by_component.items()
    ]


def free_path(out_dir, stem: str, ext: str):
    """
    First non-existing path for `stem` + `ext` in `out_dir` (append-only rule:
    a run never overwrites a previous report; same contract as
    `ic_report._free_path`).
    """
    from pathlib import Path

    out_dir = Path(out_dir)
    candidate = out_dir / f"{stem}{ext}"
    if not candidate.exists():
        return candidate
    for i in range(2, 1000):
        candidate = out_dir / f"{stem}-{i:02d}{ext}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot find a free filename for {stem}{ext}")


def month_key(d: dt.date) -> dt.date:
    """First-of-month date for grouping daily observations into months."""
    return dt.date(d.year, d.month, 1)
