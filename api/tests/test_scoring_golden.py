"""
Scoring determinism — golden-file tests for the LT score, Opt score, ticker RC
and directional bias over 10 synthetic fixture tickers.

Purpose (SESSION-TEST-HARNESS, pre-baseline-weights safety net): any change to
scoring math or weights MUST surface as an explicit, reviewable diff in
fixtures/scoring_golden.json — never as silent drift. The upcoming
baseline-weights restructure is expected to change these numbers; that change
should arrive as an intentional golden-file update in the same PR.

All scores are computed with the DEFAULT weights passed explicitly, so live
calibration state can never leak into the assertion.

To regenerate after an INTENTIONAL scoring change:
    UPDATE_GOLDEN=1 python -m pytest tests/test_scoring_golden.py
then review the golden diff like any code change.
"""
import json
import os
from pathlib import Path

import pytest

from core.scanner import (
    DEFAULT_LT_WEIGHTS, DEFAULT_OPT_WEIGHTS,
    score_long_term, score_options, _compute_ticker_rc, compute_directional_bias,
)

FIXTURES = Path(__file__).parent / "fixtures" / "scoring_fixtures.json"
GOLDEN = Path(__file__).parent / "fixtures" / "scoring_golden.json"


def _load_fixtures() -> dict:
    data = json.loads(FIXTURES.read_text())
    data.pop("_doc", None)
    return data


def _score_one(row: dict) -> dict:
    """Deterministic scoring snapshot for one fixture row."""
    lt_score, _, lt_breakdown = score_long_term(row, weights=DEFAULT_LT_WEIGHTS)
    opt_score, _, opt_breakdown = score_options(row, weights=DEFAULT_OPT_WEIGHTS)
    direction, bull, bear, conviction = compute_directional_bias(
        rsi=row.get("rsi", 50),
        price_above_sma20=row.get("price_above_sma20"),
        price_above_sma50=row.get("price_above_sma50"),
        perf_3m=row.get("perf_3m") or 0,
        weekly_above_sma20=row.get("weekly_above_sma20"),
        vol_ratio=row.get("vol_ratio") or 1.0,
        whale_bias=row.get("whale_bias") or "neutral",
    )
    rc = _compute_ticker_rc({**row, "lt_score": lt_score, "opt_score": opt_score})
    from core.baseline import compute_baseline_lt, compute_baseline_opt
    return {
        # Baseline scores (SESSION-BASELINE-WEIGHTS): the live scoring regime.
        # LT = Valuation only, Opt = Asymmetry only, no earnings multiplier.
        "baseline_lt_score": compute_baseline_lt(lt_breakdown),
        "baseline_opt_score": compute_baseline_opt(opt_breakdown),
        # Legacy composite (kept computable behind CYBERSCREENER_LEGACY_SCORES)
        "lt_score": lt_score,
        "lt_points": {k: v["points"] for k, v in lt_breakdown.items()},
        "opt_score": opt_score,
        "opt_points": {k: v["points"] for k, v in opt_breakdown.items()},
        "opt_earnings_multiplier": opt_breakdown["earnings_catalyst"]["multiplier"],
        "rc_score": rc,
        "direction": direction,
        "direction_signals": {"bull": bull, "bear": bear, "conviction": conviction},
    }


def _compute_all() -> dict:
    return {name: _score_one(row) for name, row in sorted(_load_fixtures().items())}


def test_golden_file_matches():
    computed = _compute_all()
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN.write_text(json.dumps(computed, indent=2, sort_keys=True) + "\n")
        pytest.skip("golden file regenerated — review and commit the diff")
    assert GOLDEN.exists(), (
        "fixtures/scoring_golden.json missing — generate with UPDATE_GOLDEN=1")
    golden = json.loads(GOLDEN.read_text())
    assert computed == golden, (
        "Scoring output drifted from the golden file. If this change is "
        "INTENTIONAL (a weight/scoring change), regenerate with UPDATE_GOLDEN=1 "
        "and commit the reviewed diff. If not, you just caught silent drift."
    )


def test_scoring_is_deterministic():
    """Same inputs, same outputs — twice in a row, no hidden state."""
    assert _compute_all() == _compute_all()


def test_default_weights_sum_to_100():
    assert sum(DEFAULT_LT_WEIGHTS.values()) == 100
    assert sum(DEFAULT_OPT_WEIGHTS.values()) == 100


# ── Hand-computed anchors (independent of the golden file) ────────────────────
# These pin a few values derived by hand from the scoring code, so the golden
# file itself can't be silently regenerated around a bug.

def test_elite_saas_hand_computed():
    """elite_saas hits the max branch of every LT component except earnings
    quality (raw 0.9): 25 + 20 + 15 + 15 + 9 + 15 = 99.0."""
    row = _load_fixtures()["elite_saas"]
    lt, _, bd = score_long_term(row, weights=DEFAULT_LT_WEIGHTS)
    assert lt == 99.0
    assert bd["rule_of_40"]["points"] == 25.0   # 40% growth + 30% margin = 70 >= 60
    assert bd["valuation"]["points"] == 20.0    # 2.5x EV/Rev with 40% growth
    assert bd["earnings_quality"]["points"] == 9.0

    # Opt: ivr 10 -> 0.9*29 = 26.1; conviction 3 (2 SMAs + perf) -> 0.7*28 = 19.6;
    # technical 0; liquidity mcap 100 -> 10; asymmetry 0; no earnings -> x1.0.
    opt, _, obd = score_options(row, weights=DEFAULT_OPT_WEIGHTS)
    assert opt == 55.7
    assert obd["earnings_catalyst"]["multiplier"] == 1.0

    # RC: opt 20 (capped) + lt 20 (capped) + iv 5 + rsi 10 + sma20 5 + sma50 5 = 65
    rc = _compute_ticker_rc({**row, "lt_score": lt, "opt_score": opt})
    assert rc == 65


def test_earnings_multiplier_applies_in_prime_window():
    """premium_seller_high_ivr has earnings in 5 days -> base x1.3 (capped 100)."""
    row = _load_fixtures()["premium_seller_high_ivr"]
    opt, _, bd = score_options(row, weights=DEFAULT_OPT_WEIGHTS)
    assert bd["earnings_catalyst"]["multiplier"] == 1.3
    assert opt == round(min(100.0, bd["earnings_catalyst"]["base_score"] * 1.3), 1)


def test_sparse_row_scores_without_crashing_and_stays_low():
    """neutral_sparse exercises every missing-data fallback; it must score, not
    crash, and a data-hole must never look like a high-conviction setup."""
    row = _load_fixtures()["neutral_sparse"]
    lt, _, _ = score_long_term(row, weights=DEFAULT_LT_WEIGHTS)
    opt, _, obd = score_options(row, weights=DEFAULT_OPT_WEIGHTS)
    assert 0 <= lt < 50
    assert 0 <= opt < 50
    # absent IV must read neutral (0.3 raw), not "cheap options" (0.9 raw)
    assert obd["iv_context"]["raw"] == pytest.approx(0.3)


def test_explicit_default_weights_equal_module_defaults():
    """Passing DEFAULT_*_WEIGHTS explicitly must equal calling with the module's
    pristine active weights (guards against the two drifting apart)."""
    import core.scanner as sc
    row = _load_fixtures()["overbought_momentum"]
    explicit = score_long_term(row, weights=DEFAULT_LT_WEIGHTS)[0]
    if sc._active_lt_weights == DEFAULT_LT_WEIGHTS:
        assert score_long_term(row)[0] == explicit
