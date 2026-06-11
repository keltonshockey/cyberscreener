"""
Full-column persistence round-trip — the drift-proof test.

Builds a scan row carrying a DISTINCT sentinel value for every column
save_scan() writes, INSERTs it, SELECTs it back, and asserts each column
survives with exactly the value supplied. Any future column added to the
INSERT list without a matching `?` placeholder (the 66-for-67 bug that froze
scans at #1412), any column silently dropped, and any binding/serialization
drift fails this test by name of the offending column.

Same treatment for the options_plays journal via log_play().

A static canary additionally parses the scores INSERT in db/models.py source
and asserts column-count == placeholder-count, so the #1412 class is caught
even before any row is bound.
"""
import json
import re
import importlib
from pathlib import Path

import pytest


@pytest.fixture
def models(tmp_path, monkeypatch):
    """db.models bound to a fresh temp DB built by init_db() (the schema a
    clean deploy gets — migration agreement is part of what's under test)."""
    monkeypatch.setenv("CYBERSCREENER_DB", str(tmp_path / "roundtrip.db"))
    import db.models as m
    importlib.reload(m)
    m.init_db()
    return m


# Every key save_scan() reads from a result row, with a distinct sentinel value.
SCAN_ROW = {
    "ticker": "RT",
    "price": 123.45,
    "market_cap_b": 45.6,
    "lt_score": 71.5,
    "opt_score": 64.25,
    "lt_rule_of_40": 18.0,
    "lt_valuation": 12.0,
    "lt_fcf_margin": 9.0,
    "lt_trend": 7.5,
    "lt_earnings_quality": 5.0,
    "lt_discount_momentum": 11.0,
    "opt_earnings_catalyst": 1.5,
    "opt_iv_context": 17.4,
    "opt_directional": 19.6,
    "opt_technical": 4.6,
    "opt_liquidity": 8.0,
    "opt_asymmetry": 6.5,
    "revenue_growth_pct": 22.5,
    "gross_margin_pct": 78.1,
    "operating_margin_pct": 14.2,
    "ps_ratio": 9.9,
    "pe_ratio": 31.0,
    "ev_revenue": 8.8,
    "fcf_m": 456.7,
    "fcf_margin_pct": 19.3,
    "revenue_b": 4.2,
    "rsi": 61.2,
    "sma_20": 120.0,
    "sma_50": 115.5,
    "sma_200": 99.9,
    "bb_width": 11.1,
    "vol_ratio": 1.45,
    "iv_30d": 47.5,
    "iv_rank": 62.0,
    "beta": 1.33,
    "short_pct": 6.7,
    "perf_1y": 41.0,
    "perf_3m": 12.5,
    "perf_1m": -3.2,
    "pct_from_52w_high": -8.5,
    "days_to_earnings": 12,
    "sec_score": 55,
    "sentiment_score": 33,
    "sentiment_bull_pct": 64.0,
    "whale_score": 21,
    "pc_ratio": 0.85,
    "insider_buys_30d": 3,
    "insider_sells_30d": 1,
    "lt_breakdown": {"rule_of_40": {"points": 18.0, "max": 25}},
    "opt_breakdown": {"iv_context": {"points": 17.4, "max": 29}},
    "horizon": "swing",
    "horizon_reason": "earnings window",
    "horizon_confidence": 0.8,
    "recommended_expiry": "2026-07-17",
    "recommended_dte": 36,
    "timing_signals": ["bb_squeeze", "rsi_cross"],
    "timing_debug": {"bb_width": 11.1},
    "sector": "energy",
    "subsector": "solar",
    "scoring_profile": "hardware",
    "threat_score": 88,
    "outage_status": "degraded",
    "breach_victim": True,
    "demand_signal": False,
    "short_delta": -2.5,
    "rc_score": 67,
    "iv_suspect": True,
    "sector_tags": ["solar", "energy"],
    "lt_reasons": ["Rule of 40: 37 (below threshold)"],
    "opt_reasons": ["IV Rank 62% — mid-range"],
}

# column name -> expected stored value (after save_scan's transforms)
EXPECTED_COLUMNS = {
    "ticker": "RT",
    "price": 123.45,
    "market_cap_b": 45.6,
    "lt_score": 71.5,
    "opt_score": 64.25,
    "lt_rule_of_40": 18.0,
    "lt_valuation": 12.0,
    "lt_fcf_margin": 9.0,
    "lt_trend": 7.5,
    "lt_earnings_quality": 5.0,
    "lt_discount_momentum": 11.0,
    "opt_earnings_catalyst": 1.5,
    "opt_iv_context": 17.4,
    "opt_directional": 19.6,
    "opt_technical": 4.6,
    "opt_liquidity": 8.0,
    "opt_asymmetry": 6.5,
    "revenue_growth_pct": 22.5,
    "gross_margin_pct": 78.1,
    "operating_margin_pct": 14.2,
    "ps_ratio": 9.9,
    "pe_ratio": 31.0,
    "ev_revenue": 8.8,
    "fcf_m": 456.7,
    "fcf_margin_pct": 19.3,
    "revenue_b": 4.2,
    "rsi": 61.2,
    "sma_20": 120.0,
    "sma_50": 115.5,
    "sma_200": 99.9,
    "bb_width": 11.1,
    "vol_ratio": 1.45,
    "iv_30d": 47.5,
    "iv_rank": 62.0,
    "beta": 1.33,
    "short_pct": 6.7,
    "perf_1y": 41.0,
    "perf_3m": 12.5,
    "perf_1m": -3.2,
    "pct_from_52w_high": -8.5,
    "days_to_earnings": 12,
    "sec_score": 55,
    "sentiment_score": 33,
    "sentiment_bull_pct": 64.0,
    "whale_score": 21,
    "pc_ratio": 0.85,
    "insider_buys_30d": 3,
    "insider_sells_30d": 1,
    "lt_breakdown": json.dumps(SCAN_ROW["lt_breakdown"]),
    "opt_breakdown": json.dumps(SCAN_ROW["opt_breakdown"]),
    "horizon": "swing",
    "horizon_reason": "earnings window",
    "horizon_confidence": 0.8,
    "recommended_expiry": "2026-07-17",
    "recommended_dte": 36,
    "timing_signals": json.dumps(SCAN_ROW["timing_signals"]),
    "timing_debug": json.dumps(SCAN_ROW["timing_debug"]),
    "sector": "energy",
    "subsector": "solar",
    "scoring_profile": "hardware",
    "threat_score": 88,
    "outage_status": "degraded",
    "breach_victim": 1,
    "demand_signal": 0,
    "short_delta": -2.5,
    "rc_score": 67,
    "iv_suspect": 1,
    "sector_tags": json.dumps(SCAN_ROW["sector_tags"]),
}


def test_scores_full_column_roundtrip(models):
    """Every column save_scan writes must come back with the value supplied."""
    sid, _ = models.save_scan([dict(SCAN_ROW)], intel_layers=["base"],
                              duration_seconds=1.0)

    conn = models.get_db()
    row = conn.execute("SELECT * FROM scores WHERE scan_id=?", (sid,)).fetchone()
    conn.close()
    assert row is not None, "scan row did not persist at all"
    stored = dict(row)

    missing = [c for c in EXPECTED_COLUMNS if c not in stored]
    assert not missing, f"columns absent from the scores table: {missing}"

    mismatches = {
        c: (stored[c], want)
        for c, want in EXPECTED_COLUMNS.items()
        if stored[c] != want
    }
    assert not mismatches, f"columns that did not round-trip (got, want): {mismatches}"
    assert stored["scan_id"] == sid


def test_scores_insert_placeholder_count_matches_columns():
    """Static canary for the #1412 freeze class: in db/models.py source, the
    scores INSERT's explicit column list and its VALUES placeholder list must
    be the same length. Fails at the source level, before any binding."""
    import db.models as m
    src = Path(m.__file__).read_text()
    match = re.search(
        r"INSERT INTO scores\s*\((?P<cols>.*?)\)\s*VALUES\s*\((?P<vals>.*?)\)\s*\"\"\"",
        src, re.DOTALL,
    )
    assert match, "could not locate the scores INSERT in db/models.py"
    n_cols = len([c for c in match.group("cols").split(",") if c.strip()])
    n_qs = match.group("vals").count("?")
    assert n_cols == n_qs, (
        f"scores INSERT lists {n_cols} columns but {n_qs} placeholders — "
        f"this is exactly the mismatch that froze scans at #1412"
    )


def test_scan_writes_price_snapshot_and_signals(models):
    """save_scan side tables: a prices snapshot row and one signals row per
    reason must land alongside the score row."""
    sid, _ = models.save_scan([dict(SCAN_ROW)])

    conn = models.get_db()
    price = conn.execute(
        "SELECT close_price FROM prices WHERE ticker='RT'").fetchone()
    signals = conn.execute(
        "SELECT signal_text FROM signals WHERE scan_id=? AND ticker='RT'", (sid,)
    ).fetchall()
    conn.close()

    assert price is not None and price[0] == 123.45
    texts = {s[0] for s in signals}
    assert "Rule of 40: 37 (below threshold)" in texts
    assert len(texts) == len(SCAN_ROW["lt_reasons"]) + len(SCAN_ROW["opt_reasons"])


# ── options_plays journal round-trip ──────────────────────────────────────────

PLAY_KWARGS = dict(
    ticker="RT", horizon="swing", strategy="Bear Put Spread",
    strike="195/180", expiry="2026-07-17", dte=36,
    entry_price=3.45, entry_iv_rank=62.0,
    lt_score=71.5, opt_score=64.25, rc_score=67,
    direction="bearish", notes="Pay $3.45 debit",
    max_loss=345.0, risk_reward_ratio=1.8,
)

EXPECTED_PLAY_COLUMNS = {
    "ticker": "RT",
    "horizon": "swing",
    "strategy": "Bear Put Spread",
    "strike": "195/180",
    "expiry": "2026-07-17",
    "dte": 36,
    "entry_price": 3.45,
    "entry_iv_rank": 62.0,
    "lt_score": 71.5,
    "opt_score": 64.25,
    "rc_score": 67,
    "direction": "bearish",
    "status": "open",
    "notes": "Pay $3.45 debit",
    "max_loss": 345.0,
    "risk_reward_ratio": 1.8,
    # derived at log time: 0.6*opt + 0.4*lt, the gate's bucketing key
    "entry_conviction": round(0.6 * 64.25 + 0.4 * 71.5, 2),
}


def test_options_plays_full_column_roundtrip(models):
    play_id = models.log_play(**PLAY_KWARGS)

    conn = models.get_db()
    row = conn.execute(
        "SELECT * FROM options_plays WHERE id=?", (play_id,)).fetchone()
    conn.close()
    assert row is not None
    stored = dict(row)

    missing = [c for c in EXPECTED_PLAY_COLUMNS if c not in stored]
    assert not missing, f"columns absent from options_plays: {missing}"

    mismatches = {
        c: (stored[c], want)
        for c, want in EXPECTED_PLAY_COLUMNS.items()
        if stored[c] != want
    }
    assert not mismatches, f"play columns that did not round-trip (got, want): {mismatches}"
    assert stored["generated_at"]  # filed at log time


def test_log_play_dedups_identical_open_play(models):
    """The pre-warm loop re-logs the same play every scan; log_play must return
    the existing open play's id instead of re-inserting (216-rows-for-83-plays
    journal spam regression)."""
    first = models.log_play(**PLAY_KWARGS)
    second = models.log_play(**PLAY_KWARGS)
    assert second == first

    conn = models.get_db()
    n = conn.execute("SELECT COUNT(*) FROM options_plays").fetchone()[0]
    conn.close()
    assert n == 1


def test_log_play_distinct_contract_is_new_row(models):
    first = models.log_play(**PLAY_KWARGS)
    other = dict(PLAY_KWARGS, strike="200/185")
    second = models.log_play(**other)
    assert second != first

    conn = models.get_db()
    n = conn.execute("SELECT COUNT(*) FROM options_plays").fetchone()[0]
    conn.close()
    assert n == 2
