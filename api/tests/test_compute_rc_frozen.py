"""
Frozen behavior test for the unified Reality Check scorer (_compute_rc).

_compute_rc moved verbatim from main.py to routers/plays.py during the router
split (SESSION-ROUTER-SPLIT) to break the import cycle the extraction created.
It is FROZEN pending the forward-test gate reads — this test pins its exact
input→output (score + full per-component breakdown, including the existing
labelling quirks) so any accidental change to the moved function fails loudly,
the same guarantee the scoring golden file gives the scanner.

These expected values were captured from the function as it existed in main.py
immediately before the move; they are behavior, not a re-derivation.
"""
from routers.plays import _compute_rc


def test_compute_rc_bullish_debit_high_quality():
    play = {
        "strategy": "long call (debit)", "direction": "bullish",
        "dte": 30, "risk_reward_ratio": 2.5, "breakeven_distance_pct": 4.0,
        "volume": 600, "open_interest": 2500, "bid_ask_spread_pct": 4.0,
        "action": "BUY",
    }
    td = {
        "opt_score": 66, "lt_score": 62, "iv_rank": 20, "days_to_earnings": 10,
        "rsi": 45, "price_above_sma20": True, "price_above_sma50": True,
    }
    out = _compute_rc(play, td)
    assert out == {
        "score": 91,
        "breakdown": {
            "trade_quality": {"points": 19, "max": 25, "detail": "R/R 2.5:1, BE 4.0%"},
            "execution": {"points": 20, "max": 20, "detail": "Vol 600, OI 2500, Sprd 4%"},
            "score_alignment": {"points": 20, "max": 20, "detail": "Opt 66, LT 62"},
            "iv_context": {"points": 15, "max": 15, "detail": "IV Rank 20%, buying"},
            "catalyst": {"points": 10, "max": 10, "detail": "Earnings in 10d, DTE 30"},
            "technical": {"points": 7, "max": 10, "detail": "RSI 45, bullish"},
        },
    }


def test_compute_rc_bearish_credit_low_quality():
    # Note the existing quirks this pins: "bear call credit spread" contains
    # "call", so technical scores via the bullish branch (→ 0 here); and IV
    # context falls to the selling branch yet labels itself "buying". Frozen.
    play = {
        "strategy": "bear call credit spread", "direction": "bearish",
        "dte": 21, "risk_reward_ratio": 0.8, "breakeven_distance_pct": 12.0,
        "volume": 40, "open_interest": 120, "bid_ask_spread_pct": 15.0,
        "action": "SELL/BUY",
    }
    td = {
        "opt_score": 41, "lt_score": 36, "iv_rank": 80, "days_to_earnings": None,
        "rsi": 72, "price_above_sma20": False, "price_above_sma50": False,
    }
    out = _compute_rc(play, td)
    assert out == {
        "score": 45,
        "breakdown": {
            "trade_quality": {"points": 5, "max": 25, "detail": "R/R 0.8:1, BE 12.0%"},
            "execution": {"points": 6, "max": 20, "detail": "Vol 40, OI 120, Sprd 15%"},
            "score_alignment": {"points": 9, "max": 20, "detail": "Opt 41, LT 36"},
            "iv_context": {"points": 15, "max": 15, "detail": "IV Rank 80%, buying"},
            "catalyst": {"points": 10, "max": 10, "detail": "Earnings N/A, DTE 21"},
            "technical": {"points": 0, "max": 10, "detail": "RSI 72, bearish"},
        },
    }
