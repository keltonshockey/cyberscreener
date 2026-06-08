"""
IV ingestion sanity — derivation + cap-aware gate + NULL-robust downstream.

Context: stored iv_30d is corrupt at scale (2026-06-08 analysis of scan #1412:
~31% of rows >100% IV, mega-cap tier mean ~100%). Two root issues fixed here:
  1. iv_30d was derived as median(impliedVolatility) over the ENTIRE chain, so
     garbage deep-OTM/ITM IV inflated it ~2-3x — replaced by ATM-windowed IV.
  2. No cap-aware sanity bound let impossible mega-cap IV (e.g. NVDA 152%) flow
     into iv_context scoring — now NULLed + flagged at ingestion.

These tests lock in: the gate rejects data errors without nuking legitimately
high small-cap IV, ATM IV beats the all-strike median, and NULL IV flows through
score_options / generate_plays neutrally (not as a 0 that reads as "cheap IV").
"""
import os
import sys
from datetime import datetime, timedelta

import pandas as pd

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.scanner import (
    _iv_is_suspect,
    _atm_iv_pct,
    _iv_for_play,
    _fallback_iv,
    score_options,
    generate_plays,
)


# ── _iv_is_suspect: tiered, cap-aware bounds ──────────────────────────────────

def test_mega_cap_triple_digit_iv_is_suspect():
    # NVDA-shaped: $5.3T cap reading 152% — physically impossible, reject.
    suspect, reason = _iv_is_suspect(152.1, market_cap_b=5296.0)
    assert suspect and "mega-cap" in reason


def test_mega_cap_normal_iv_is_kept():
    # A mega-cap at a plausible 45% must pass.
    suspect, _ = _iv_is_suspect(45.0, market_cap_b=500.0)
    assert not suspect


def test_large_cap_tier_threshold():
    assert _iv_is_suspect(140.0, market_cap_b=50.0)[0]      # >130 large-cap -> suspect
    assert not _iv_is_suspect(120.0, market_cap_b=50.0)[0]  # 120 large-cap -> kept


def test_mid_cap_tier_threshold():
    assert _iv_is_suspect(180.0, market_cap_b=8.0)[0]       # >170 mid-cap -> suspect
    assert not _iv_is_suspect(150.0, market_cap_b=8.0)[0]   # 150 mid-cap -> kept


def test_legit_high_iv_small_cap_is_kept():
    # The whole point: a $1.5B name legitimately running 140% IV must NOT be nuked.
    suspect, _ = _iv_is_suspect(140.0, market_cap_b=1.5)
    assert not suspect


def test_small_cap_impossible_tail_is_suspect():
    # Even a small-cap can't sustain >300% — reject the impossible tail.
    assert _iv_is_suspect(350.0, market_cap_b=1.5)[0]


def test_absurd_iv_suspect_regardless_of_cap():
    assert _iv_is_suspect(600.0, market_cap_b=None)[0]      # >500 always
    assert _iv_is_suspect(0.5, market_cap_b=10.0)[0]        # <1 always
    assert _iv_is_suspect(None, market_cap_b=10.0)[0]       # missing


# ── _atm_iv_pct: ATM-windowed median beats all-strike median ──────────────────

def _chain(price=100.0):
    """A realistic chain: ATM strikes ~45% IV, deep wings carry yfinance junk."""
    strikes = [50, 70, 85, 95, 100, 105, 115, 130, 160, 200]
    # near-money (85-115) ~0.45; far wings carry absurd 3-9.0 raw IV (yfinance noise)
    iv = [9.0, 5.0, 0.47, 0.45, 0.44, 0.46, 0.48, 3.0, 6.5, 8.0]
    oi = [10, 50, 800, 1200, 1500, 1100, 700, 40, 5, 2]
    vol = [1, 5, 200, 400, 500, 300, 150, 3, 0, 0]
    df = pd.DataFrame({"strike": strikes, "impliedVolatility": iv,
                       "openInterest": oi, "volume": vol})
    return df


def test_atm_iv_ignores_garbage_wings():
    calls = _chain()
    puts = _chain()
    atm = _atm_iv_pct(calls, puts, price=100.0)
    # All-strike median would be ~150-300%; ATM window should land near ~45%.
    assert atm is not None
    assert 40 <= atm <= 55, f"ATM IV {atm} should reflect near-money ~45%, not inflated wings"


def test_atm_iv_much_lower_than_all_strike_median():
    calls = _chain()
    all_strike_median = float(calls["impliedVolatility"].median()) * 100
    atm = _atm_iv_pct(calls, None, price=100.0)
    assert atm < all_strike_median, (
        f"ATM {atm} must be below the inflated all-strike median {all_strike_median}")


def test_atm_iv_handles_empty_and_missing():
    assert _atm_iv_pct(pd.DataFrame(), pd.DataFrame(), price=100.0) is None
    assert _atm_iv_pct(None, None, price=100.0) is None
    assert _atm_iv_pct(_chain(), None, price=0) is None  # no spot


# ── downstream NULL-robustness ────────────────────────────────────────────────

def _opt_row(**kw):
    base = dict(
        price=100.0, sma_20=98, sma_50=95, sma_200=90,
        price_above_sma20=True, price_above_sma50=True,
        rsi=55, vol_ratio=1.4, iv_rank=None, iv_30d=45,
        bb_width=6.0, short_pct=4.0, beta=1.2, market_cap_b=50,
        whale_score=20, whale_bias="neutral", days_to_earnings=None,
    )
    base.update(kw)
    return base


def test_null_iv_scores_neutral_not_low():
    """NULL iv_30d (gated) must score iv_context NEUTRAL, not as cheap (0)-IV.

    Before the fix `iv = row.get("iv_30d") or 0` collapsed None to 0, which fell
    into the `iv <= 40` branch (raw 0.2 — reads as 'cheap, good for buying') and
    quietly rewarded a data hole. Neutral raw is 0.3.
    """
    _, _, bd = score_options(_opt_row(iv_30d=None, iv_rank=None))
    assert bd["iv_context"]["raw"] == 0.3
    assert bd["iv_context"]["raw_value"] is None


def test_null_iv_does_not_crash_score_options():
    score, _, _ = score_options(_opt_row(iv_30d=None, iv_rank=None))
    assert isinstance(score, float) and 0 <= score <= 100


def test_null_iv_does_not_read_as_cheap_buy_signal():
    """A genuinely low-IV name (cheap options) should out-score a NULL-IV name on
    iv_context — i.e. NULL is not silently treated as the best (cheapest) case."""
    low_iv = score_options(_opt_row(iv_30d=25, iv_rank=10))[2]["iv_context"]["points"]
    null_iv = score_options(_opt_row(iv_30d=None, iv_rank=None))[2]["iv_context"]["points"]
    assert null_iv < low_iv


def test_null_iv_does_not_crash_generate_plays():
    # No chains -> empty list, but crucially must not raise on None iv_30d.
    plays = generate_plays("ACME", 100.0, [], iv_30d=None, rsi=55, iv_rank=None)
    assert plays == []


# ── _iv_for_play / _fallback_iv: NULL IV must not silently drop a ticker ───────
#
# The interaction flaw this guards against: once the ingestion gate began NULLing
# corrupt IV (and every absent IV), the downstream play paths all called
# _iv_is_suspect and *skipped* on a hit. _iv_is_suspect(None) is True, so ~19% of
# the universe silently vanished from /killer-plays and play generation. The fix
# substitutes a cap-tier proxy and flags iv_estimated instead of dropping.

def test_iv_for_play_passes_through_trustworthy_value():
    iv_use, estimated, note = _iv_for_play(45.0, market_cap_b=500.0)
    assert iv_use == 45.0 and not estimated and note is None


def test_iv_for_play_estimates_on_null_instead_of_dropping():
    iv_use, estimated, note = _iv_for_play(None, market_cap_b=500.0)
    assert estimated is True
    assert isinstance(iv_use, float) and iv_use > 0   # a usable IV, never None
    assert note and "estimated" in note.lower()


def test_iv_for_play_estimates_on_corrupt_high_value():
    # Mega-cap reading an impossible 152% -> rejected, but still estimated, not dropped.
    iv_use, estimated, note = _iv_for_play(152.0, market_cap_b=5000.0)
    assert estimated is True
    assert isinstance(iv_use, float) and 0 < iv_use < 100
    assert note and "rejected" in note.lower()


def test_fallback_iv_scales_inversely_with_cap():
    assert _fallback_iv(500.0) == 35.0   # mega
    assert _fallback_iv(50.0) == 45.0    # large
    assert _fallback_iv(8.0) == 55.0     # mid
    assert _fallback_iv(1.5) == 70.0     # small
    assert _fallback_iv(None) == 60.0    # unknown
    # Inverse relationship holds across tiers.
    assert _fallback_iv(500.0) < _fallback_iv(50.0) < _fallback_iv(8.0) < _fallback_iv(1.5)


def _playable_chain(price=100.0):
    """A liquid chain ~35 DTE so generate_plays can actually emit a directional play."""
    expiry = (datetime.today().date() + timedelta(days=35)).strftime("%Y-%m-%d")
    chains = []
    for strike in (90, 95, 100, 105, 110):
        for typ in ("call", "put"):
            chains.append({
                "expiry": expiry, "type": typ, "strike": float(strike),
                "bid": 2.0, "ask": 2.2, "lastPrice": 2.1,
                "volume": 500, "openInterest": 1000, "iv": 0.45,
            })
    return chains


def test_null_iv_ticker_still_generates_a_play():
    """Core interaction fix: a NULL-IV ticker must still produce a play (via the
    estimated fallback IV), not silently vanish."""
    iv_use, estimated, _ = _iv_for_play(None, market_cap_b=500.0)
    assert estimated
    plays = generate_plays("ACME", 100.0, _playable_chain(), iv_30d=iv_use, rsi=30,
                           price_above_sma20=True, price_above_sma50=True)
    assert len(plays) >= 1, "NULL-IV ticker must still generate a play, not vanish"


def test_corrupt_iv_ticker_still_generates_a_play():
    """A rejected (corrupt-high) IV must also still produce a play, not vanish."""
    iv_use, estimated, _ = _iv_for_play(152.0, market_cap_b=5000.0)
    assert estimated
    plays = generate_plays("ACME", 100.0, _playable_chain(), iv_30d=iv_use, rsi=30,
                           price_above_sma20=True, price_above_sma50=True)
    assert len(plays) >= 1
