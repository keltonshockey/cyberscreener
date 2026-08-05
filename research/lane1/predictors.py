"""
Chen-Zimmermann low-turnover predictors, computed point-in-time — Milestone D.

The list, the signs and the bars were PRE-REGISTERED in
`RESULT_R3_LANE1_2026-08-05.md` (git commit `a58ea3f`) before this file existed.
Nothing here may deviate from that registration: in particular the SIGNS come
from CZ's `SignalDoc.csv` and are fixed. Flipping one after seeing a result is
how a null becomes a "finding".

Every input obeys the same `filed <= D` discipline as `pit.py` — these are
as-filed accounting figures, never restatements.
"""

from __future__ import annotations

import datetime as dt

from .pit import (CAPEX, CASH, DEBT_CUR, DEBT_LT, GROSS, OCF, OPINC, REV,
                  SHARES, annual_facts, as_of_annual, as_of_instant,
                  instant_facts, prior_annual)

# Additional concepts this milestone needs beyond pit.py's set.
ASSETS = ["Assets"]
EQUITY = ["StockholdersEquity",
          "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
NETINCOME = ["NetIncomeLoss", "ProfitLoss"]
LIABILITIES = ["Liabilities"]

# name -> CZ documented sign. Higher oriented value = expected higher return.
# FIXED BY PRE-REGISTRATION.
CZ_SIGN = {
    "BM": +1,
    "EP": +1,
    "CF": +1,
    "GP": +1,
    "OperProf": +1,
    "Accruals": -1,
    "NOA": -1,
    "AssetGrowth": -1,
    "ShareIss1Y": -1,
    "Investment": -1,
}
PREDICTORS = list(CZ_SIGN)


def prior_instant(facts, D: dt.date, cur_end: dt.date, min_gap_days: int = 300):
    """
    Latest instant value at least ~a year before `cur_end`, knowable at D.

    Needed for the growth-style predictors (AssetGrowth, ShareIss1Y, NOA), which
    are ratios against a LAGGED balance-sheet figure. Both legs must respect
    `filed <= D` or the growth term leaks the future.
    """
    cand = [(e, fl, v) for (e, fl, v) in facts
            if fl <= D and e < cur_end and (cur_end - e).days >= min_gap_days]
    if not cand:
        return None
    best_end = max(e for (e, _fl, _v) in cand)
    same = sorted([(fl, v) for (e, fl, v) in cand if e == best_end])
    return same[0][1]


class FactBundle:
    """Pre-extracted fact series for one ticker, so snapshots don't re-parse."""

    def __init__(self, us_gaap: dict, dei: dict):
        g, d = us_gaap, dei
        self.rev = annual_facts(g, REV)
        self.gross = annual_facts(g, GROSS)
        self.opinc = annual_facts(g, OPINC)
        self.ocf = annual_facts(g, OCF)
        self.capex = annual_facts(g, CAPEX)
        self.ni = annual_facts(g, NETINCOME)
        self.assets = instant_facts(g, ASSETS)
        self.equity = instant_facts(g, EQUITY)
        self.liab = instant_facts(g, LIABILITIES)
        self.cash = instant_facts(g, CASH)
        self.debt_lt = instant_facts(g, DEBT_LT)
        self.debt_cur = instant_facts(g, DEBT_CUR)
        self.shares = instant_facts(d, SHARES)


def compute(bundle: FactBundle, D: dt.date, price: float) -> dict:
    """
    All 10 predictors as of D, ORIENTED by the pre-registered CZ sign.

    Returns only the predictors whose inputs are all available; a missing input
    yields an absent key rather than a zero, so the cross-section drops that
    name for that predictor instead of ranking it against a fabricated value.
    """
    out: dict[str, float] = {}

    shares = as_of_instant(bundle.shares, D)
    mktcap = price * shares if (shares and shares > 0) else None

    assets_row = None
    cand = [(e, fl, v) for (e, fl, v) in bundle.assets if fl <= D]
    if cand:
        best_end = max(e for (e, _f, _v) in cand)
        assets_row = (best_end, sorted([(fl, v) for (e, fl, v) in cand if e == best_end])[0][1])
    assets = assets_row[1] if assets_row else None

    equity = as_of_instant(bundle.equity, D)
    liab = as_of_instant(bundle.liab, D)
    cash = as_of_instant(bundle.cash, D)
    debt = (as_of_instant(bundle.debt_lt, D) or 0) + (as_of_instant(bundle.debt_cur, D) or 0)

    rev = as_of_annual(bundle.rev, D)
    gross = as_of_annual(bundle.gross, D)
    opinc = as_of_annual(bundle.opinc, D)
    ocf = as_of_annual(bundle.ocf, D)
    capex = as_of_annual(bundle.capex, D)
    ni = as_of_annual(bundle.ni, D)

    # ── valuation-class: accounting quantity per dollar of market cap ─────────
    if mktcap and mktcap > 0:
        if equity is not None:
            out["BM"] = equity / mktcap
        if ni is not None:
            out["EP"] = ni[1] / mktcap
        if ocf is not None:
            out["CF"] = ocf[1] / mktcap

    # ── profitability-class ──────────────────────────────────────────────────
    if assets and assets > 0 and gross is not None:
        out["GP"] = gross[1] / assets
    if equity and equity > 0 and opinc is not None:
        out["OperProf"] = opinc[1] / equity

    # ── accruals ─────────────────────────────────────────────────────────────
    if assets and assets > 0 and ni is not None and ocf is not None:
        out["Accruals"] = (ni[1] - ocf[1]) / assets

    # ── balance-sheet composition / growth (need a lagged leg) ───────────────
    if assets_row and assets and assets > 0:
        prior_assets = prior_instant(bundle.assets, D, assets_row[0])
        if prior_assets and prior_assets > 0:
            out["AssetGrowth"] = assets / prior_assets - 1
            if liab is not None and cash is not None:
                # Operating assets less operating liabilities, scaled by lagged assets.
                op_assets = assets - cash
                op_liabs = liab - debt
                out["NOA"] = (op_assets - op_liabs) / prior_assets

    if shares and shares > 0:
        cand_s = [(e, fl, v) for (e, fl, v) in bundle.shares if fl <= D]
        if cand_s:
            cur_end = max(e for (e, _f, _v) in cand_s)
            prior_sh = prior_instant(bundle.shares, D, cur_end)
            if prior_sh and prior_sh > 0:
                out["ShareIss1Y"] = shares / prior_sh - 1

    # ── investment ───────────────────────────────────────────────────────────
    if rev is not None and rev[1] and capex is not None:
        out["Investment"] = capex[1] / rev[1]

    # Orientation is applied LAST and uniformly, using the pre-registered signs.
    return {k: v * CZ_SIGN[k] for k, v in out.items()}
