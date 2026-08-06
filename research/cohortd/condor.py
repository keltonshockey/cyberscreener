"""
Iron condor construction and settlement — PREREG_COHORT_D.md §4 and §6.

The settlement math here is the strategy-correct four-leg version. It is
reimplemented rather than imported: the tested closure logic in the app
(PR #12) lives behind journal write paths, and this lane imports nothing from
`api/` (prereg §11). The behaviour is re-derived and re-tested from scratch.

Isolation: no `api/` import, no database, no network.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass

# PREREG §4 — fixed structure parameters.
SHORT_DELTA = 0.20
LONG_DELTA = 0.05
DTE_MIN, DTE_MAX = 30, 45
DTE_TARGET = 37


@dataclass
class Condor:
    expiry: str
    dte: int
    short_put: float
    long_put: float
    short_call: float
    long_call: float
    credit: float
    put_width: float
    call_width: float

    @property
    def defined_risk(self) -> float:
        """PREREG §4: max(put_width, call_width) - credit."""
        return max(self.put_width, self.call_width) - self.credit

    def as_dict(self) -> dict:
        d = asdict(self)
        d["defined_risk"] = self.defined_risk
        return d


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via erf — avoids a scipy dependency."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def bs_delta(spot, strike, iv, dte_days, kind, rate=0.0) -> float | None:
    """
    Black-Scholes delta, used only when the chain supplies none.

    Returns the SIGNED delta (calls positive, puts negative); callers compare on
    absolute value.
    """
    if not (spot > 0 and strike > 0 and iv and iv > 0 and dte_days > 0):
        return None
    T = dte_days / 365.0
    d1 = (math.log(spot / strike) + (rate + 0.5 * iv * iv) * T) / (iv * math.sqrt(T))
    return _norm_cdf(d1) if kind == "call" else _norm_cdf(d1) - 1.0


def _delta_of(row: dict, spot: float, dte: int, kind: str) -> float | None:
    d = row.get("delta")
    if d is not None:
        try:
            return float(d)
        except (TypeError, ValueError):
            pass
    return bs_delta(spot, float(row["strike"]), row.get("impliedVolatility"), dte, kind)


def _mid(row: dict) -> float | None:
    """
    Mid of bid/ask.

    PREREG §4 registers mid-pricing as a KNOWN UPWARD BIAS versus realistic
    fills. It is not silently corrected here; it is disclosed on every read.
    Rows without a two-sided market are unusable and return None rather than
    falling back to `lastPrice`, which can be stale by days.
    """
    try:
        bid, ask = float(row.get("bid") or 0), float(row.get("ask") or 0)
    except (TypeError, ValueError):
        return None
    if bid <= 0 or ask <= 0 or ask < bid:
        return None
    return (bid + ask) / 2.0


def _nearest_by_delta(rows, target, spot, dte, kind):
    """Row whose |delta| is closest to `target`, ignoring unusable quotes."""
    best, best_gap = None, None
    for r in rows:
        d = _delta_of(r, spot, dte, kind)
        if d is None or _mid(r) is None:
            continue
        gap = abs(abs(d) - target)
        if best_gap is None or gap < best_gap:
            best, best_gap = r, gap
    return best


def choose_expiry(expiries_dte: dict) -> str | None:
    """
    Expiry within 30-45 DTE, nearest to 37 (PREREG §4).

    `expiries_dte` maps expiry string -> DTE.
    """
    eligible = [(e, d) for e, d in expiries_dte.items() if DTE_MIN <= d <= DTE_MAX]
    if not eligible:
        return None
    return min(eligible, key=lambda ed: (abs(ed[1] - DTE_TARGET), ed[1]))[0]


def build_condor(spot, expiry, dte, puts, calls) -> Condor | None:
    """
    Select the four legs: 20-delta shorts, 5-delta wings (PREREG §4).

    Returns None if any leg is missing or the geometry is invalid — a partial
    condor is not a defined-risk position and must not be logged as one.
    """
    sp = _nearest_by_delta(puts, SHORT_DELTA, spot, dte, "put")
    lp = _nearest_by_delta(puts, LONG_DELTA, spot, dte, "put")
    sc = _nearest_by_delta(calls, SHORT_DELTA, spot, dte, "call")
    lc = _nearest_by_delta(calls, LONG_DELTA, spot, dte, "call")
    if not all((sp, lp, sc, lc)):
        return None

    sp_k, lp_k = float(sp["strike"]), float(lp["strike"])
    sc_k, lc_k = float(sc["strike"]), float(lc["strike"])

    # Geometry: long put below short put, long call above short call, and the
    # short strikes must not cross. A chain that violates this is malformed.
    if not (lp_k < sp_k < sc_k < lc_k):
        return None

    credit = (_mid(sp) - _mid(lp)) + (_mid(sc) - _mid(lc))
    if credit <= 0:
        return None

    put_width, call_width = sp_k - lp_k, lc_k - sc_k
    condor = Condor(expiry=expiry, dte=dte, short_put=sp_k, long_put=lp_k,
                    short_call=sc_k, long_call=lc_k, credit=credit,
                    put_width=put_width, call_width=call_width)
    # Credit above the widest wing would imply a risk-free position; that is a
    # data error, not an opportunity.
    if condor.defined_risk <= 0:
        return None
    return condor


def settle(condor: Condor, settlement_price: float) -> dict:
    """
    Settle at expiry from the SPY close — PREREG §6, exactly.

        put_side  = max(0, Ps - S) - max(0, Pl - S)
        call_side = max(0, S - Cs) - max(0, S - Cl)
        pnl       = credit - (put_side + call_side)

    Each side is intrinsically capped at its own wing width by construction, so
    loss can never exceed `max(width) - credit`; the tests assert that on a
    sweep across every settlement region rather than trusting the algebra.
    """
    S = float(settlement_price)
    put_side = max(0.0, condor.short_put - S) - max(0.0, condor.long_put - S)
    call_side = max(0.0, S - condor.short_call) - max(0.0, S - condor.long_call)
    pnl = condor.credit - (put_side + call_side)
    risk = condor.defined_risk
    return {
        "settlement_price": S,
        "put_side_loss": put_side,
        "call_side_loss": call_side,
        "pnl": pnl,
        "r_multiple": pnl / risk if risk > 0 else float("nan"),
        "win": pnl > 0,
    }
