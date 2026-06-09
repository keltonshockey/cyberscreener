"""
§6b signal relevance metadata, asserted end-to-end through save_scan against the
real production schema fixture (same harness as test_scan_persist).

Covers:
  • classify_signal unit behaviour (stack / polarity / sector-context gate / dedupe);
  • signals persisted emoji-free with relevance metadata, impact derived from
    polarity (not the dead emoji heuristic).
"""
import os
import sys
import sqlite3
import importlib
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.signals_meta import classify_signal, dedupe_key

SCHEMA = Path(__file__).parent / "fixtures" / "scores_schema.sql"


# ── pure-unit: classify_signal ──────────────────────────────────────────────

def test_stack_inference():
    assert classify_signal("IV Rank 10% — good for buying premium")["stack"] == "options"
    assert classify_signal("Rule of 40: 75 (elite)")["stack"] == "lt"
    assert classify_signal("Earnings in 7 days")["stack"] == "both"


def test_polarity_and_impact():
    pos = classify_signal("Deep value: 4x EV/Rev with 40% growth")
    assert pos["polarity"] == "tailwind" and pos["impact"] == "positive"
    neg = classify_signal("Cash burn: FCF margin -20%")
    assert neg["polarity"] == "headwind" and neg["impact"] == "negative"


def test_sector_context_gate():
    # threat/demand is noise for a non-cyber name → suppressed, must not score
    off = classify_signal("Active threat landscape demand signal", sector="energy")
    assert off["sector_context"] == "suppress" and off["applies"] is False
    # tailwind for a cyber vendor
    on = classify_signal("Active threat landscape demand signal", sector="cyber")
    assert on["sector_context"] == "cyber-demand" and on["applies"] is True
    assert on["polarity"] == "tailwind"
    # headwind for a breach victim
    victim = classify_signal("Active threat landscape", sector="cyber", breach_victim=True)
    assert victim["polarity"] == "headwind"


def test_dedupe_key_collapses_numeric_variants():
    assert dedupe_key("Analyst target $30.01") == dedupe_key("Analyst target $28.50")
    assert dedupe_key("RSI 73 overbought") == dedupe_key("RSI 41 overbought")


# ── integration through save_scan ───────────────────────────────────────────

@pytest.fixture
def models(tmp_path, monkeypatch):
    db_file = tmp_path / "test_meta.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(SCHEMA.read_text())
    conn.commit()
    conn.close()
    monkeypatch.setenv("CYBERSCREENER_DB", str(db_file))
    import db.models as m
    importlib.reload(m)
    return m


def _row(ticker="CRWD", **kw):
    base = dict(
        ticker=ticker, price=100.0, market_cap_b=12.3,
        lt_score=72.0, opt_score=64.0, rc_score=58,
        sector="cyber", subsector="saas", scoring_profile="saas",
        sector_tags=["Cyber", "AI", "Tech"],
        lt_breakdown={}, opt_breakdown={},
        lt_reasons=["🚀 Rule of 40: 75 (elite)"],
        opt_reasons=["🌋 Demand Signal — active threat landscape"],
    )
    base.update(kw)
    return base


def test_signals_persisted_emoji_free_with_metadata(models):
    sid, _ = models.save_scan([_row("CRWD")])
    conn = models.get_db()
    rows = conn.execute(
        "SELECT signal_text, impact, stack, polarity, sector_context, dedupe_key "
        "FROM signals WHERE scan_id=? AND ticker='CRWD' ORDER BY id", (sid,)
    ).fetchall()
    conn.close()

    texts = [r[0] for r in rows]
    assert any("🚀" in t or "🌋" in t for t in texts) is False  # emoji stripped
    assert "Rule of 40: 75 (elite)" in texts

    by_text = {r[0]: r for r in rows}
    r40 = by_text["Rule of 40: 75 (elite)"]
    assert r40[2] == "lt" and r40[4] == "general"

    demand = by_text["Demand Signal — active threat landscape"]
    # cyber vendor → demand is a tailwind, not suppressed
    assert demand[3] == "tailwind" and demand[4] == "cyber-demand"
    assert demand[1] == "positive"  # impact derived from polarity
