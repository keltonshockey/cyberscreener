"""
HAR-RV volatility forecasting — Corsi (2009).

PREREG_COHORT_D.md §5 fixes this as the forecast that gates entry. The entry rule
is `ATM_IV30 - HAR_RV_21d_forecast >= 2.0` vol points, so this module decides
whether a cycle trades at all.

Registered approximation, repeated here because it matters: daily realized
variance uses CLOSE-TO-CLOSE log returns (`RV_t = r_t^2`), which is a noisier
proxy than intraday realized variance. Accepted because the decision is a coarse
2.0-vol-point threshold rather than a precise variance estimate, and because
intraday SPY data is not available to this lane. This was registered in advance,
not discovered afterwards.

Isolation: this module imports nothing from `api/` and touches no database.
"""

from __future__ import annotations

import math

import numpy as np

TRADING_DAYS = 252
HORIZON_DAYS = 21          # forecast horizon, per the prereg
WEEK_LAG = 5
MONTH_LAG = 22
MIN_HISTORY = MONTH_LAG + HORIZON_DAYS + 30   # enough for lags, target, and a fit


def log_returns(closes) -> np.ndarray:
    """Close-to-close log returns from a price series."""
    c = np.asarray(closes, dtype=float)
    if c.ndim != 1 or c.size < 2:
        return np.array([], dtype=float)
    if np.any(c <= 0):
        raise ValueError("non-positive close in price series")
    return np.diff(np.log(c))


def realized_variance(closes) -> np.ndarray:
    """Daily realized variance proxy, r_t^2."""
    r = log_returns(closes)
    return r * r


def annualize_variance(var_daily: float) -> float:
    """Daily variance -> annualized volatility in POINTS (e.g. 18.5)."""
    return math.sqrt(max(var_daily, 0.0) * TRADING_DAYS) * 100.0


def _design(rv: np.ndarray, t: int) -> list[float]:
    """HAR regressors at index t: [1, RV_daily, RV_weekly, RV_monthly]."""
    return [1.0,
            float(rv[t]),
            float(rv[t - WEEK_LAG + 1:t + 1].mean()),
            float(rv[t - MONTH_LAG + 1:t + 1].mean())]


def fit_har(rv: np.ndarray):
    """
    OLS fit of  RV_{t+1:t+21} = b0 + bd*RV_d + bw*RV_w + bm*RV_m.

    Fitted on an EXPANDING window using only observations whose full forward
    target is already realized — so no row in the fit can contain information
    from after its own target window. That is what keeps the forecast
    point-in-time rather than fitted on the future it is predicting.
    """
    n = rv.size
    last_t = n - HORIZON_DAYS - 1          # last index with a complete target
    if last_t < MONTH_LAG:
        return None
    X, y = [], []
    for t in range(MONTH_LAG - 1, last_t + 1):
        X.append(_design(rv, t))
        y.append(float(rv[t + 1:t + 1 + HORIZON_DAYS].mean()))
    X = np.asarray(X)
    y = np.asarray(y)
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    return beta


def forecast_har(closes) -> dict:
    """
    21-day-ahead annualized volatility forecast, in vol points.

    Returns a dict carrying the components as well as the forecast, because the
    prereg requires the computed values to be logged for skipped cycles too — a
    filter whose rejections are not recorded cannot be audited later.
    """
    rv = realized_variance(closes)
    if rv.size < MIN_HISTORY:
        return {"ok": False, "reason": f"need >= {MIN_HISTORY} returns, have {rv.size}"}

    beta = fit_har(rv)
    if beta is None:
        return {"ok": False, "reason": "insufficient history to fit HAR"}

    t = rv.size - 1
    x = np.asarray(_design(rv, t))
    var_hat = float(x @ beta)

    # OLS on variance can return a negative fitted value. Clamp to the smallest
    # observed positive daily variance rather than to zero: a zero forecast
    # would make the IV-minus-forecast spread artificially huge and manufacture
    # an entry, which is the failure direction that actually costs money.
    floor = float(rv[rv > 0].min()) if np.any(rv > 0) else 1e-12
    clamped = var_hat < floor
    var_hat = max(var_hat, floor)

    return {
        "ok": True,
        "forecast_vol_points": annualize_variance(var_hat),
        "var_daily": var_hat,
        "clamped": clamped,
        "rv_d": annualize_variance(float(rv[t])),
        "rv_w": annualize_variance(float(rv[t - WEEK_LAG + 1:t + 1].mean())),
        "rv_m": annualize_variance(float(rv[t - MONTH_LAG + 1:t + 1].mean())),
        "beta": [float(b) for b in beta],
        "n_obs": int(rv.size),
    }


def forecast_garch(closes) -> dict:
    """
    Optional GARCH(1,1) comparison forecast.

    PREREG §5: logged alongside HAR for later comparison, but it NEVER gates an
    entry — the registered rule uses HAR only. A missing `arch` package is not
    an error; the reason is recorded and the run continues.
    """
    try:
        from arch import arch_model
    except Exception as exc:
        return {"ok": False, "reason": f"arch unavailable ({type(exc).__name__})"}
    try:
        r = log_returns(closes) * 100.0
        if r.size < MIN_HISTORY:
            return {"ok": False, "reason": "insufficient history"}
        res = arch_model(r, vol="Garch", p=1, q=1, mean="Constant").fit(disp="off")
        f = res.forecast(horizon=HORIZON_DAYS, reindex=False)
        mean_var_pct2 = float(np.asarray(f.variance)[-1].mean())
        return {"ok": True,
                "forecast_vol_points": annualize_variance(mean_var_pct2 / 10000.0)}
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
