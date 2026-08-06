"""
Faithful port of `api/core/scanner.py::score_long_term` as it stood for the June
reconstruction, with the June default LT weights.

This is deliberately a COPY, not an import of the live function. Two reasons:

  1. The live scorer has since moved to the v2 baseline (`weights_baseline.json`,
     LT = Valuation 100). Importing it would silently re-point the regression
     gate at different weights and the June numbers would never reproduce.
  2. `research/` must not import application write paths, and reaching into
     `api.core.scanner` drags in yfinance and the whole scanner import chain
     (RESULT_R2_IC_HARNESS correction 3).

The thresholds below are therefore frozen June-era logic. If the live scorer
changes, this file must NOT be updated to match — it is the historical baseline
the reproduction gate is measured against.
"""

from __future__ import annotations

# June-era DEFAULT_LT_WEIGHTS. Sum = 100.
W = {
    "rule_of_40": 25,
    "valuation": 20,
    "fcf_margin": 15,
    "trend": 15,
    "earnings_quality": 10,
    "discount_momentum": 15,
}

COMPONENTS = ["rule_of_40", "valuation", "fcf_margin", "trend",
              "earnings_quality", "discount_momentum"]


def score_component(raw: float, weight: float) -> float:
    """`_score_component`: clamp to [0,1], scale by weight, round to 0.1."""
    return round(max(0, min(1, raw)) * weight, 1)


def score_lt(row: dict) -> dict:
    """
    Compute the six LT components + `lt_score` from a PIT row.

    Missing fundamentals fall through to the same penalised defaults the live
    scorer used, so a name with thin coverage is scored the way production
    would have scored it rather than being dropped.
    """
    bd: dict[str, float] = {}

    rg = row.get("revenue_growth_pct") or 0
    om = row.get("operating_margin_pct") or 0
    gm = row.get("gross_margin_pct") or 0

    # ── Rule of 40 ────────────────────────────────────────────────────────────
    margin = om if om != 0 else (gm * 0.5)
    r40 = rg + margin
    if r40 >= 60:
        raw = 1.0
    elif r40 >= 40:
        raw = 0.7 + 0.3 * ((r40 - 40) / 20)
    elif r40 >= 25:
        raw = 0.3 + 0.4 * ((r40 - 25) / 15)
    elif r40 >= 0:
        raw = 0.1 + 0.2 * (r40 / 25)
    else:
        raw = 0
    bd["rule_of_40"] = score_component(raw, W["rule_of_40"])

    # ── Valuation (growth-adjusted EV/Revenue) — the June survivor ────────────
    ev_rev = row.get("ev_revenue") or row.get("ps_ratio") or 999
    g4v = max(rg, 1)
    vr = ev_rev / g4v if g4v > 0 else 999
    if ev_rev < 3 and rg > 10:
        raw = 1.0
    elif vr < 0.3 and ev_rev < 15:
        raw = 0.85
    elif vr < 0.5 and ev_rev < 20:
        raw = 0.75
    elif vr < 0.8 and ev_rev < 25:
        raw = 0.6
    elif ev_rev < 10:
        raw = 0.5
    elif ev_rev < 20:
        raw = 0.35
    else:
        raw = max(0, 0.15 - (ev_rev - 20) / 100)
    bd["valuation"] = score_component(raw, W["valuation"])

    # ── FCF margin ────────────────────────────────────────────────────────────
    fm = row.get("fcf_margin_pct")
    if fm is not None:
        if fm >= 25:
            raw = 1.0
        elif fm >= 15:
            raw = 0.7 + 0.3 * ((fm - 15) / 10)
        elif fm >= 5:
            raw = 0.3 + 0.4 * ((fm - 5) / 10)
        elif fm >= 0:
            raw = 0.15
        else:
            raw = 0
    else:
        raw = 0
    bd["fcf_margin"] = score_component(raw, W["fcf_margin"])

    # ── Trend ─────────────────────────────────────────────────────────────────
    price = row.get("price", 0)
    s20, s50, s200 = row.get("sma_20"), row.get("sma_50"), row.get("sma_200")
    ts = tmax = 0
    if s200 is not None:
        tmax += 2
        if price > s200:
            ts += 2
    if s50 is not None:
        tmax += 1.5
        if price > s50:
            ts += 1.5
    if s20 is not None:
        tmax += 1
        if price > s20:
            ts += 1
    if s50 and s200 and s50 > s200:  # golden cross
        ts += 0.5
        tmax += 0.5
    raw = ts / tmax if tmax > 0 else 0.5
    bd["trend"] = score_component(raw, W["trend"])

    # ── Earnings quality ──────────────────────────────────────────────────────
    eps = row.get("eps")
    pe = row.get("pe_ratio")
    q = 0
    if eps is not None and eps > 0:
        q += 0.4
        if pe and 10 < pe < 40:
            q += 0.2
        elif pe and pe > 0:
            q += 0.1
    elif rg > 30:
        q += 0.2
    if gm > 75:
        q += 0.3
    elif gm > 60:
        q += 0.2
    elif gm > 40:
        q += 0.1
    elif gm > 0:
        q += 0.05
    bd["earnings_quality"] = score_component(min(1.0, q), W["earnings_quality"])

    # ── Discount + momentum ───────────────────────────────────────────────────
    disc = row.get("pct_from_52w_high") or 0
    p3 = row.get("perf_3m") or 0
    p1 = row.get("perf_1m") or 0
    if disc < -30:
        dr = 1.0 if p1 > 0 else 0.6
    elif disc < -15:
        dr = 0.7 if p1 > 0 else 0.4
    elif disc < -5:
        dr = 0.65 if p3 > 0 else 0.5
    else:
        dr = 1.0 if p3 > 10 else (0.65 if p3 > 0 else 0.3)
    bd["discount_momentum"] = score_component(min(1.0, dr), W["discount_momentum"])

    bd["lt_score"] = round(sum(bd[k] for k in W), 1)
    return bd
