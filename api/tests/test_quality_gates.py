"""
Quality gates (core.quality_gates) — two-stage eligibility + conviction pipeline.

Covers the three required fixtures (Tier-A exclusion, Tier-B conviction cap, organic
normalization) plus graceful degradation on absent inputs and a GEN-shaped end-to-end
trace. PIT-validated rationale lives in core/quality_gates.py + RESULT_QUALITY_GATES.
"""
import os
import sys
import json

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core import quality_gates as qg


def _lt_breakdown(r40=25.0):
    return json.dumps({
        "rule_of_40": {"points": r40, "max": 25},
        "valuation": {"points": 16, "max": 20},
    })


# ── Tier A — hard-exclude ─────────────────────────────────────────────────────

def test_tierA_price_floor_excludes():
    a = qg.assess({"price": 3.10, "market_cap_b": 5.0})
    assert a.eligible is False
    assert any("price" in r for r in a.exclude_reasons)


def test_tierA_market_cap_floor_excludes():
    a = qg.assess({"price": 40.0, "market_cap_b": 0.12})
    assert a.eligible is False
    assert any("market cap" in r for r in a.exclude_reasons)


def test_tierA_interest_coverage_excludes():
    a = qg.assess({"price": 40.0, "market_cap_b": 5.0, "interest_coverage": 0.4})
    assert a.eligible is False
    assert any("interest coverage" in r for r in a.exclude_reasons)


def test_tierA_dollar_volume_excludes():
    a = qg.assess({"price": 40.0, "market_cap_b": 5.0, "dollar_volume": 500_000})
    assert a.eligible is False


def test_tierA_healthy_name_eligible():
    a = qg.assess({"price": 120.0, "market_cap_b": 15.0, "dollar_volume": 80e6,
                   "interest_coverage": 6.0, "sentiment_bull_pct": 40})
    assert a.eligible is True
    assert a.exclude_reasons == []


def test_tierA_graceful_on_absent_inputs():
    # No solvency/liquidity fields present -> cannot exclude (graceful degradation).
    a = qg.evaluate_eligibility({"sentiment_bull_pct": 30})
    assert a[0] is True and a[1] == []


# ── Tier B — organic-growth normalization ─────────────────────────────────────

def test_organic_normalization_caps_ma_rule_of_40():
    # M&A-flagged with a maxed Rule-of-40 -> board penalty = excess over 15.
    row = {"price": 28.0, "market_cap_b": 15.0, "acquisition_flag": True,
           "lt_breakdown": _lt_breakdown(r40=25.0), "sentiment_bull_pct": 30}
    lt_pen, conv_pen, cap, reasons = qg.conviction_modifiers(row)
    assert lt_pen == 10.0                     # 25 -> 15
    assert conv_pen == 10.0 * qg.LT_WEIGHT_IN_CONVICTION
    assert any("organic-normalization" in r for r in reasons)


def test_organic_normalization_noop_on_organic_name():
    row = {"price": 28.0, "market_cap_b": 15.0, "acquisition_flag": False,
           "lt_breakdown": _lt_breakdown(r40=25.0), "sentiment_bull_pct": 30}
    lt_pen, conv_pen, cap, reasons = qg.conviction_modifiers(row)
    assert lt_pen == 0.0
    assert not any("organic" in r for r in reasons)


def test_organic_normalization_noop_when_flag_absent():
    # No M&A inputs at all -> not flagged (graceful).
    row = {"lt_breakdown": _lt_breakdown(r40=25.0), "sentiment_bull_pct": 30}
    lt_pen, *_ = qg.conviction_modifiers(row)
    assert lt_pen == 0.0


def test_organic_normalization_derived_flag_from_goodwill_step():
    row = {"goodwill_step_pct_rev": 25.0, "lt_breakdown": _lt_breakdown(r40=22.0),
           "sentiment_bull_pct": 30}
    lt_pen, *_ = qg.conviction_modifiers(row)
    assert lt_pen == 7.0                       # 22 -> 15


# ── Tier B — secular decline ──────────────────────────────────────────────────

def test_secular_decline_downweights():
    row = {"rev_cagr_3y": 0.5, "op_margin_delta_3y": -3.0, "sentiment_bull_pct": 30}
    lt_pen, _, _, reasons = qg.conviction_modifiers(row)
    assert lt_pen == qg.SECULAR_LT_PENALTY
    assert any("secular-decline" in r for r in reasons)


def test_secular_decline_requires_both_inputs():
    assert qg.is_secular_decline({"rev_cagr_3y": 0.5}) is False           # margin missing
    assert qg.is_secular_decline({"op_margin_delta_3y": -3.0}) is False   # cagr missing
    assert qg.is_secular_decline({"rev_cagr_3y": 8.0, "op_margin_delta_3y": -3.0}) is False  # growing


# ── Tier B — interest-corroboration cap (cap-don't-kill) ──────────────────────

def test_corroboration_cap_blocks_high_without_signal():
    # Zero corroboration -> tier capped below High even on a strong score.
    row = {"sentiment_bull_pct": 0, "whale_score": 0, "insider_buys_30d": 0, "perf_3m": -8.0}
    _, _, cap, reasons = qg.conviction_modifiers(row)
    assert cap == "SOLID"
    a = qg.QualityAssessment(tier_cap="SOLID")
    assert qg.gated_tier(80.0, a) == "SOLID"        # would be HIGH without the cap


def test_corroboration_present_allows_high():
    row = {"whale_score": 12.0, "sentiment_bull_pct": 0, "insider_buys_30d": 0}
    _, _, cap, _ = qg.conviction_modifiers(row)
    assert cap is None
    assert qg.gated_tier(80.0, qg.QualityAssessment()) == "HIGH"


def test_corroboration_does_not_exclude():
    # Cap-don't-kill: uncorroborated name stays ELIGIBLE.
    a = qg.assess({"price": 40.0, "market_cap_b": 5.0,
                   "sentiment_bull_pct": 0, "whale_score": 0, "insider_buys_30d": 0,
                   "perf_3m": -5.0})
    assert a.eligible is True
    assert a.tier_cap == "SOLID"


# ── GEN-shaped end-to-end (the motivating value trap) ─────────────────────────

def test_gen_value_trap_end_to_end():
    """
    GEN: lt_score 91.5, Rule-of-40 25/25 on M&A-juiced revenue, solvent + liquid
    ($15B, P/E 16), but sentiment/whale/insider all 0 and 1y trend -13%.
    Expected: ELIGIBLE (passes hygiene), but board-penalized (R40 normalized) AND
    capped below High (no corroboration) -> no longer tops a conviction-ranked board.
    Raw lt_score is NOT mutated by this module.
    """
    gen = {
        "ticker": "GEN", "price": 28.0, "market_cap_b": 15.0, "dollar_volume": 80e6,
        "interest_coverage": 4.0, "acquisition_flag": True,
        "lt_breakdown": _lt_breakdown(r40=25.0),
        "lt_score": 91.5, "opt_score": 40.0,
        "sentiment_bull_pct": 0, "whale_score": 0, "insider_buys_30d": 0, "perf_1y": -13.0,
    }
    a = qg.assess(gen)
    assert a.eligible is True                      # hygiene passes — surgical, not a junk filter
    assert a.lt_penalty == 10.0                    # Rule-of-40 25 -> 15 on the board
    assert a.tier_cap == "SOLID"                   # zero corroboration

    gated_lt = gen["lt_score"] - a.lt_penalty
    assert gated_lt == 81.5                         # board score deflated 91.5 -> 81.5
    assert gen["lt_score"] == 91.5                  # raw score untouched (Tier B isolated)

    combined = gen["opt_score"] * 0.6 + gen["lt_score"] * 0.4   # 60.6
    assert qg.gated_tier(combined, a) == "SOLID"    # capped out of High


# ── Buy-zone endpoint integration (the live LT-board wiring) ──────────────────
# Proves the gates active on the CURRENT scores schema: Tier-A liquidity exclusion
# + B2 corroboration cap. B1/B3/A5 require scanner columns not yet persisted and
# no-op gracefully (documented in RESULT_QUALITY_GATES as the scanner follow-up).

import sqlite3
import importlib
from pathlib import Path

import pytest

SCORES_SCHEMA = Path(__file__).parent / "fixtures" / "scores_schema.sql"


@pytest.fixture
def market(tmp_path, monkeypatch):
    db_file = tmp_path / "qg.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(SCORES_SCHEMA.read_text())
    conn.commit()
    conn.close()
    monkeypatch.setenv("CYBERSCREENER_DB", str(db_file))
    import db.models as m
    importlib.reload(m)
    import routers.market as mk
    importlib.reload(mk)
    mk._DB_FILE = db_file
    return mk


def _seed(market, ticker, *, lt, opt=60.0, price=120.0, mcap=15.0, rsi=30.0,
          sent=0.0, whale=0.0, insider=0, perf3=-8.0):
    c = sqlite3.connect(market._DB_FILE)
    c.execute(
        "INSERT INTO scores (scan_id, ticker, price, lt_score, opt_score, rsi, "
        "market_cap_b, sentiment_bull_pct, whale_score, insider_buys_30d, perf_3m, "
        "threat_score, outage_status, breach_victim, lt_breakdown) "
        "VALUES (1, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 100, 'none', 0, '{}')",
        (ticker, price, lt, opt, rsi, mcap, sent, whale, insider, perf3),
    )
    c.commit(); c.close()


def test_buyzone_excludes_subdollar_and_caps_uncorroborated(market):
    _seed(market, "CLEAN", lt=82.0, sent=40.0)                       # corroborated -> High
    _seed(market, "TRAP", lt=85.0, sent=0.0, whale=0.0, insider=0, perf3=-8.0)  # capped
    _seed(market, "PENNY", lt=88.0, price=3.5)                       # Tier-A exclude
    resp = market.get_buy_zone(limit=8)
    picks = {p["ticker"]: p for p in resp["picks"]}
    assert "PENNY" not in picks                       # hard-excluded (price < $5)
    assert picks["TRAP"]["conviction"] == "SOLID"     # eligible but capped (no corroboration)
    assert picks["CLEAN"]["conviction"] == "HIGH"     # corroborated -> can reach High
