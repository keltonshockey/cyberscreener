"""
Opt Score: earnings catalyst is a multiplier, not a base component.

Verifies:
- base Opt Score is computed from iv/directional/technical/liquidity/asymmetry only
  (no earnings drag when there are no earnings),
- earnings proximity amplifies the final score (×1.3 at 3-14 days, ×1.1 at 14-30),
- the score is capped at 100,
- earnings_catalyst is no longer a weighted base component.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.scanner import score_options, DEFAULT_OPT_WEIGHTS


def _row(**kw):
    base = dict(
        price=100.0, sma_20=98, sma_50=95, sma_200=90,
        price_above_sma20=True, price_above_sma50=True,
        rsi=55, vol_ratio=1.4, iv_rank=30, iv_30d=45,
        bb_width=6.0, short_pct=4.0, beta=1.2, market_cap_b=50,
        whale_score=20, whale_bias="neutral",
    )
    base.update(kw)
    return base


def test_earnings_not_in_base_weights():
    assert "earnings_catalyst" not in DEFAULT_OPT_WEIGHTS
    assert abs(sum(DEFAULT_OPT_WEIGHTS.values()) - 100) < 0.01


def test_no_earnings_uses_base_only():
    """A ticker with no earnings scores on setup quality alone (×1.0)."""
    score, _, bd = score_options(_row(days_to_earnings=None))
    base = sum(bd[c]["points"] for c in
               ["iv_context", "directional", "technical", "liquidity", "asymmetry"])
    assert abs(score - base) < 0.05, f"no-earnings score {score} should equal base {base}"
    assert bd["earnings_catalyst"]["multiplier"] == 1.0
    assert bd["earnings_catalyst"]["max"] == 0  # not a base component


def test_prime_window_applies_1_3x():
    row = _row(days_to_earnings=7)
    score, _, bd = score_options(row)
    base = bd["earnings_catalyst"]["base_score"]
    assert bd["earnings_catalyst"]["multiplier"] == 1.3
    assert abs(score - min(100.0, base * 1.3)) < 0.05


def test_building_window_applies_1_1x():
    row = _row(days_to_earnings=22)
    score, _, bd = score_options(row)
    assert bd["earnings_catalyst"]["multiplier"] == 1.1
    base = bd["earnings_catalyst"]["base_score"]
    assert abs(score - min(100.0, base * 1.1)) < 0.05


def test_far_earnings_no_amplification():
    for dte in (40, 90, 2):  # >30, and just-too-imminent (<3) get no bonus
        _, _, bd = score_options(_row(days_to_earnings=dte))
        assert bd["earnings_catalyst"]["multiplier"] == 1.0, f"dte={dte}"


def test_multiplier_caps_at_100():
    # Force a high base, then a near-earnings multiplier; result must not exceed 100.
    row = _row(days_to_earnings=7, iv_rank=15, rsi=72, vol_ratio=3.0,
               bb_width=2.0, short_pct=20, beta=2.5, whale_score=80, whale_bias="bullish")
    score, _, _ = score_options(row)
    assert score <= 100.0


def test_prime_window_beats_no_earnings():
    """Same setup scores higher with a near-term catalyst than without."""
    no_e = score_options(_row(days_to_earnings=None))[0]
    with_e = score_options(_row(days_to_earnings=7))[0]
    assert with_e > no_e
