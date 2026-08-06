"""
Cohort D metrics — PREREG_COHORT_D.md §7 and §9.

Every number the cohort reports is defined here, so a read cannot quietly use a
different statistic than the one registered. In particular:

  * win rate NEVER appears without its Wilson interval,
  * expectancy uses a BOOTSTRAP interval, because short-premium P&L is strongly
    left-skewed and a t-interval understates tail risk at small n,
  * a PASS claim requires beta-adjusted alpha, never raw win rate (§9).

Isolation: imports nothing from `api/`.
"""

from __future__ import annotations

import math
import random

# PREREG §8 / §10 thresholds.
FAIL_STOP_MIN_N = 30
VERDICT_MIN_N = 100
BOOTSTRAP_RESAMPLES = 10_000
BOOTSTRAP_SEED = 20260806      # fixed so a read is reproducible


def wilson_interval(wins: int, n: int, z: float = 1.96):
    """Wilson score interval — correct at small n, unlike the normal approximation."""
    if n == 0:
        return (0.0, 0.0)
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def bootstrap_mean_ci(values, resamples=BOOTSTRAP_RESAMPLES, alpha=0.05,
                      seed=BOOTSTRAP_SEED):
    """Percentile bootstrap CI for the mean (PREREG §7)."""
    vals = [float(v) for v in values]
    n = len(vals)
    if n < 2:
        return (float("nan"), float("nan"))
    rng = random.Random(seed)
    means = []
    for _ in range(resamples):
        means.append(sum(vals[rng.randrange(n)] for _ in range(n)) / n)
    means.sort()
    lo = means[int((alpha / 2) * resamples)]
    hi = means[min(resamples - 1, int((1 - alpha / 2) * resamples))]
    return (lo, hi)


def max_drawdown(r_multiples) -> float:
    """Max drawdown of the cumulative R curve (returns a non-positive number)."""
    peak = cum = 0.0
    worst = 0.0
    for r in r_multiples:
        cum += float(r)
        peak = max(peak, cum)
        worst = min(worst, cum - peak)
    return worst


def profit_factor(r_multiples) -> float:
    gains = sum(r for r in r_multiples if r > 0)
    losses = -sum(r for r in r_multiples if r < 0)
    if losses == 0:
        return float("inf") if gains > 0 else float("nan")
    return gains / losses


def ols_alpha_beta(y, x):
    """
    Regress cohort R-multiples on contemporaneous SPY returns (PREREG §9).

    Returns alpha, beta and alpha's standard error. A short-condor book is
    structurally short crash risk and therefore loaded on equity beta; without
    removing that beta, a positive average return is mostly a free market
    exposure rather than skill.
    """
    n = len(y)
    if n < 3 or len(x) != n:
        return None
    mx = sum(x) / n
    my = sum(y) / n
    sxx = sum((xi - mx) ** 2 for xi in x)
    if sxx == 0:
        return None
    beta = sum((x[i] - mx) * (y[i] - my) for i in range(n)) / sxx
    alpha = my - beta * mx
    resid = [y[i] - (alpha + beta * x[i]) for i in range(n)]
    dof = n - 2
    s2 = sum(r * r for r in resid) / dof
    se_alpha = math.sqrt(s2 * (1.0 / n + mx * mx / sxx))
    return {"alpha": alpha, "beta": beta, "se_alpha": se_alpha,
            "t_alpha": alpha / se_alpha if se_alpha > 0 else float("nan"), "n": n}


def summarize(rows, spy_returns=None) -> dict:
    """
    The full registered metric set for a monthly read.

    `verdict` is capped by sample size per §8 and can never be upgraded by a
    good-looking number; `fail_stop` implements §10 exactly.
    """
    r = [float(x["r_multiple"]) for x in rows if x["r_multiple"] is not None]
    n = len(r)
    wins = sum(1 for x in r if x > 0)

    out = {
        "n": n,
        "wins": wins,
        "win_rate": wins / n if n else float("nan"),
        "win_rate_ci95": wilson_interval(wins, n),
        "expectancy_r": sum(r) / n if n else float("nan"),
        "expectancy_ci95": bootstrap_mean_ci(r) if n >= 2 else (float("nan"),) * 2,
        "profit_factor": profit_factor(r),
        "max_drawdown_r": max_drawdown(r),
        "total_r": sum(r),
    }

    # PREREG §10 — fail-stop.
    lo, hi = out["expectancy_ci95"]
    out["fail_stop_armed"] = n >= FAIL_STOP_MIN_N
    out["fail_stop_triggered"] = bool(n >= FAIL_STOP_MIN_N and hi == hi and hi < 0)

    # PREREG §9 — alpha vs SPY beta. Only meaningful with paired returns.
    out["alpha"] = ols_alpha_beta(r, list(spy_returns)) if spy_returns and len(spy_returns) == n else None

    # PREREG §8 — verdict labels are capped by n.
    if out["fail_stop_triggered"]:
        out["verdict"] = "FAIL-STOP: expectancy CI entirely below zero at n>=30"
    elif n < VERDICT_MIN_N:
        out["verdict"] = f"DIRECTIONAL (n={n} < {VERDICT_MIN_N}; no verdict permitted)"
    elif out["alpha"] and out["alpha"]["alpha"] > 0 and out["alpha"]["t_alpha"] >= 1.96:
        out["verdict"] = "PASS-CANDIDATE: positive beta-adjusted alpha (confirm bias check)"
    else:
        out["verdict"] = "H0 NOT REJECTED: no positive beta-adjusted alpha"
    return out
