"""
Symmetric directional rebuild — single source of truth for bull/bear bias.

Context (2026-06-08 SESSION-DIRECTIONAL-REBUILD): direction was computed in THREE
divergent places with three different formulas:
  1. score_options (scanner.py)      — symmetric SMA, used in scoring
  2. generate_plays (scanner.py)     — BULL-BIASED: the two SMA terms only ever
                                       added bullish signal (below SMA = nothing),
                                       tilting the rule ~69% long; picks the contract
  3. killer-plays (routers/market.py) — a bare RSI>65/<38 rule, the displayed label
They disagreed by construction, producing the ABBV symptom: a ticker labelled
"bearish" (RSI>65) that emitted a Long Call (generate_plays computed bullish from
the bull-biased SMA + momentum). 5/8 bearish plays on #1415 produced no contract
(the divergent-neutral death path).

Fix: one helper `compute_directional_bias`, symmetric by construction, called by
all three sites. These tests lock in: (1) symmetry, (2) the below-SMA regression,
(3) PLAY-3 label gating (a lone mild RSI is not a direction), (4) a bearish ticker
yields a put/bear-spread with a real strike and NEVER a Long Call, and (5) the
label can never contradict the generated contract's direction.
"""
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.scanner import compute_directional_bias, generate_plays, score_options


# ── helpers ───────────────────────────────────────────────────────────────────

def _playable_chain(price=100.0):
    """A liquid chain ~35 DTE so generate_plays can actually emit contracts."""
    expiry = (datetime.today().date() + timedelta(days=35)).strftime("%Y-%m-%d")
    chains = []
    for strike in (80, 85, 90, 95, 100, 105, 110, 115, 120):
        for typ in ("call", "put"):
            chains.append({
                "expiry": expiry, "type": typ, "strike": float(strike),
                "bid": 2.0, "ask": 2.2, "lastPrice": 2.1,
                "volume": 500, "openInterest": 1000, "iv": 0.45,
            })
    return chains


def _opt_row(**kw):
    base = dict(
        price=100.0, sma_20=98, sma_50=95, sma_200=90,
        price_above_sma20=True, price_above_sma50=True,
        rsi=55, vol_ratio=1.4, iv_rank=None, iv_30d=45,
        bb_width=6.0, short_pct=4.0, beta=1.2, market_cap_b=50,
        whale_score=20, whale_bias="neutral", days_to_earnings=None, perf_3m=0,
    )
    base.update(kw)
    return base


def _score_direction(row):
    return score_options(row)[2]["directional"]["raw_value"]["direction"]


# ── 1. symmetry of compute_directional_bias ───────────────────────────────────

def test_mirror_inputs_give_mirror_directions():
    """A bullish setup and its exact mirror must yield bullish vs bearish with
    equal-and-opposite signal counts — the property the old asymmetric SMA broke."""
    bull_dir, bull_b, bull_be, _ = compute_directional_bias(
        rsi=20, price_above_sma20=True, price_above_sma50=True, perf_3m=20)
    bear_dir, bear_b, bear_be, _ = compute_directional_bias(
        rsi=85, price_above_sma20=False, price_above_sma50=False, perf_3m=-20)
    assert bull_dir == "bullish"
    assert bear_dir == "bearish"
    # mirror symmetry: bull side of one equals bear side of the other
    assert bull_b == bear_be and bull_be == bear_b


def test_below_both_smas_contributes_bearish():
    """THE bull-bias regression. Old generate_plays added nothing toward bearish
    when price was below its SMAs; a name below both SMAs with no other signal was
    a 0/0 tie -> neutral. Now below SMA must actively register bearish."""
    direction, bull, bear, _ = compute_directional_bias(
        rsi=50, price_above_sma20=False, price_above_sma50=False, perf_3m=0)
    assert bear == 2 and bull == 0
    assert direction == "bearish"


def test_above_both_smas_contributes_bullish():
    direction, bull, bear, _ = compute_directional_bias(
        rsi=50, price_above_sma20=True, price_above_sma50=True, perf_3m=0)
    assert bull == 2 and bear == 0
    assert direction == "bullish"


# ── 2. PLAY-3 label gating (a mild RSI is not a direction) ─────────────────────

def test_lone_mild_rsi_is_neutral_not_bearish():
    """PLAY-3: 'RSI 73 should not be sufficient for a bearish call.' With SMA
    position unknown, a single mildly-elevated RSI (+1) must stay neutral."""
    direction, _, _, _ = compute_directional_bias(rsi=67)
    assert direction == "neutral"


def test_lone_mild_rsi_oversold_is_neutral():
    direction, _, _, _ = compute_directional_bias(rsi=33)
    assert direction == "neutral"


def test_true_rsi_extreme_with_confluence_labels():
    # RSI>78 (+3 bear) + below both SMAs (+2 bear) = decisively bearish.
    direction, _, _, _ = compute_directional_bias(
        rsi=82, price_above_sma20=False, price_above_sma50=False)
    assert direction == "bearish"


def test_unknown_sma_is_skipped_not_assumed_bullish():
    """None (unknown) SMA must contribute nothing — neither bull nor bear."""
    _, bull, bear, _ = compute_directional_bias(
        rsi=50, price_above_sma20=None, price_above_sma50=None)
    assert bull == 0 and bear == 0


# ── 3. generate_plays: a bearish ticker gets a bear contract, never a call ─────

def _bearish_inputs():
    # below both SMAs + overbought + negative momentum = unambiguous bearish
    return dict(rsi=82, price_above_sma20=False, price_above_sma50=False, perf_3m=-15)


def test_bearish_ticker_emits_put_or_bear_spread_with_strike():
    plays = generate_plays("ACME", 100.0, _playable_chain(), iv_30d=40, **_bearish_inputs())
    assert plays, "a clearly bearish ticker must produce at least one contract"
    bear_strats = {"Long Put", "Bear Put Spread"}
    bear_plays = [p for p in plays if p["strategy"] in bear_strats]
    assert bear_plays, f"expected a put/bear-spread, got {[p['strategy'] for p in plays]}"
    for p in bear_plays:
        assert p.get("strike") not in (None, ""), "bear contract must carry a strike"


def test_bearish_ticker_never_emits_long_call():
    """The ABBV symptom: a bearish thesis must never produce a Long Call."""
    plays = generate_plays("ACME", 100.0, _playable_chain(), iv_30d=40, **_bearish_inputs())
    assert all(p["strategy"] != "Long Call" for p in plays)
    # No directional long-premium play may be tagged Bullish on a bearish ticker.
    assert all(p.get("direction") != "Bullish" for p in plays)


def test_bullish_ticker_never_emits_long_put():
    bull = dict(rsi=22, price_above_sma20=True, price_above_sma50=True, perf_3m=20)
    plays = generate_plays("ACME", 100.0, _playable_chain(), iv_30d=40, **bull)
    assert plays
    assert all(p["strategy"] != "Long Put" for p in plays)
    assert all(p.get("direction") != "Bearish" for p in plays)


# ── 4. no direction/strategy mismatch across the whole input grid ──────────────

def test_label_and_contract_never_disagree():
    """For any setup, the bias that picks the contract is the same helper that
    labels the ticker, so a 'bearish' label can never carry a bullish contract
    (and vice-versa). This is the structural guarantee the rebuild provides."""
    grid = []
    for rsi in (15, 33, 50, 67, 75, 85):
        for a20 in (True, False):
            for a50 in (True, False):
                for perf in (-20, 0, 20):
                    grid.append((rsi, a20, a50, perf))
    for rsi, a20, a50, perf in grid:
        bias, _, _, _ = compute_directional_bias(
            rsi=rsi, price_above_sma20=a20, price_above_sma50=a50, perf_3m=perf)
        plays = generate_plays("ACME", 100.0, _playable_chain(), iv_30d=40,
                               rsi=rsi, price_above_sma20=a20, price_above_sma50=a50,
                               perf_3m=perf)
        for p in plays:
            pdir = (p.get("direction") or "").lower()
            if bias == "bearish":
                assert "bullish" not in pdir, (
                    f"bearish setup {(rsi,a20,a50,perf)} produced bullish play {p['strategy']}")
            elif bias == "bullish":
                assert not pdir.startswith("bearish"), (
                    f"bullish setup {(rsi,a20,a50,perf)} produced bearish play {p['strategy']}")


# ── 5. the three sites agree (score == contract-bias) ──────────────────────────

def test_score_options_direction_matches_helper():
    """score_options must derive direction from the same helper, so the persisted
    scoring direction equals the contract bias for identical inputs."""
    row = _opt_row(rsi=82, price_above_sma20=False, price_above_sma50=False, perf_3m=-15)
    helper_dir, _, _, _ = compute_directional_bias(
        rsi=82, price_above_sma20=False, price_above_sma50=False, perf_3m=-15,
        weekly_above_sma20=None, vol_ratio=row["vol_ratio"], whale_bias="neutral")
    assert _score_direction(row) == helper_dir == "bearish"


# ── 6. exhaustive mirror symmetry (SESSION-TEST-HARNESS) ───────────────────────
# Deepens the single mirror case above: the symmetric property must hold for
# every RSI band pair, each SMA term in isolation, and the full input grid —
# not just one hand-picked setup. Any future edit that re-introduces an
# asymmetric term fails here immediately.

import pytest as _pytest


@_pytest.mark.parametrize("rsi_bull, rsi_bear", [
    (20, 85),   # extreme band: <22 vs >78
    (25, 75),   # strong band: <28 vs >72
    (32, 68),   # mild band:   <35 vs >65
])
def test_rsi_bands_are_mirrored_in_magnitude(rsi_bull, rsi_bear):
    """Each oversold band must carry exactly the weight of its overbought twin."""
    _, bull, _, _ = compute_directional_bias(rsi=rsi_bull)
    _, _, bear, _ = compute_directional_bias(rsi=rsi_bear)
    assert bull == bear and bull > 0


@_pytest.mark.parametrize("kwargs_bull, kwargs_bear", [
    (dict(price_above_sma20=True), dict(price_above_sma20=False)),
    (dict(price_above_sma50=True), dict(price_above_sma50=False)),
    (dict(weekly_above_sma20=True), dict(weekly_above_sma20=False)),
    (dict(perf_3m=15), dict(perf_3m=-15)),
])
def test_each_term_contributes_equal_weight_both_ways(kwargs_bull, kwargs_bear):
    """Above-SMA and below-SMA (and +/- momentum) must contribute the SAME
    magnitude to their respective sides — the structural ~69% long bias was
    exactly this property being violated."""
    _, bull, bear_side, _ = compute_directional_bias(rsi=50, **kwargs_bull)
    _, bull_side, bear, _ = compute_directional_bias(rsi=50, **kwargs_bear)
    assert bull == bear and bull == 1
    assert bear_side == 0 and bull_side == 0


def test_full_grid_mirror_property():
    """For every input combo, mirroring all inputs swaps (bull, bear) exactly
    and flips the label (neutral stays neutral)."""
    flip = {"bullish": "bearish", "bearish": "bullish", "neutral": "neutral"}
    rsi_mirror = {20: 80, 30: 70, 40: 60, 50: 50, 60: 40, 70: 30, 80: 20}
    for rsi in (20, 30, 40, 50, 60, 70, 80):
        for a20 in (True, False, None):
            for a50 in (True, False, None):
                for perf in (-15, 0, 15):
                    d1, b1, be1, _ = compute_directional_bias(
                        rsi=rsi, price_above_sma20=a20,
                        price_above_sma50=a50, perf_3m=perf)
                    mirror_a20 = None if a20 is None else (not a20)
                    mirror_a50 = None if a50 is None else (not a50)
                    d2, b2, be2, _ = compute_directional_bias(
                        rsi=rsi_mirror[rsi], price_above_sma20=mirror_a20,
                        price_above_sma50=mirror_a50, perf_3m=-perf)
                    assert (b1, be1) == (be2, b2), (
                        f"mirror broke at rsi={rsi} a20={a20} a50={a50} perf={perf}")
                    assert d2 == flip[d1]
