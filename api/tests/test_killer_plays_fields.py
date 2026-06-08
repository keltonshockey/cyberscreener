"""
Regression test for the /killer-plays field gap that left the forward-test
journal (mill:poll_killer_plays.py) logging appended=0 forever.

The journal qualifies a play only when opt_score >= 65, rc_score >= 50, and
strategy/strike/expiry/premium are all non-null *under those canonical key
names*. Before this fix /killer-plays:
  - emitted play details only under play_*-prefixed keys (play_strategy, ...),
    never the canonical strategy/strike/expiry the journal reads;
  - carried no premium field at all;
  - never selected rc_score from the scores row.
So every play read as null on the journal's contract → appended=0.

These tests build a temp DB with the real prod scores schema + the options_plays
schema, seed a ranked ticker with an open play, and assert /killer-plays surfaces
the canonical contract the journal depends on.
"""
import os
import sys
import sqlite3
import importlib
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

SCORES_SCHEMA = Path(__file__).parent / "fixtures" / "scores_schema.sql"

# Mirrors api/db/migrate_options_plays.py (incl. the ALTER-added columns).
OPTIONS_PLAYS_DDL = """
CREATE TABLE IF NOT EXISTS options_plays (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker          TEXT    NOT NULL,
    generated_at    TEXT    NOT NULL,
    horizon         TEXT,
    strategy        TEXT,
    strike          REAL,
    expiry          TEXT,
    dte             INTEGER,
    entry_price     REAL,
    entry_iv_rank   REAL,
    lt_score        REAL,
    opt_score       REAL,
    rc_score        INTEGER,
    direction       TEXT    DEFAULT 'bullish',
    outcome_price   REAL,
    outcome_date    TEXT,
    pnl_pct         REAL,
    status          TEXT    DEFAULT 'open',
    notes           TEXT,
    max_loss        REAL,
    risk_reward_ratio REAL
);
"""

JOURNAL_CONTRACT = ("strategy", "strike", "expiry", "estimated_premium",
                    "premium", "max_loss", "risk_reward")


def _seed_scores(conn, ticker, *, lt=80.0, opt=80.0, rsi=72.0, iv=40.0,
                 mcap=100.0, rc=60, scan_id=1):
    """A ranked ticker that clears every /killer-plays filter: combined>=65,
    threat ok, no outage/breach, RSI>65 (non-neutral + overbought catalyst),
    IV not suspect."""
    conn.execute(
        "INSERT INTO scores (scan_id, ticker, price, lt_score, opt_score, rsi, "
        "iv_30d, market_cap_b, rc_score, threat_score, outage_status, breach_victim) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 100, 'none', 0)",
        (scan_id, ticker, 200.0, lt, opt, rsi, iv, mcap, rc),
    )


def _seed_open_play(conn, ticker, *, rc=72):
    conn.execute(
        "INSERT INTO options_plays (ticker, generated_at, horizon, strategy, "
        "strike, expiry, dte, entry_price, rc_score, direction, status, "
        "max_loss, risk_reward_ratio) "
        "VALUES (?, '2026-06-08 17:00:00', 'technical', 'Bear Put Spread', "
        "?, '2026-06-26', 18, ?, ?, 'bearish', 'open', ?, ?)",
        (ticker, "195/180", 3.45, rc, 345.0, 1.8),
    )


@pytest.fixture
def market(tmp_path, monkeypatch):
    """routers.market bound to a fresh temp DB (scores + options_plays)."""
    db_file = tmp_path / "kp.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(SCORES_SCHEMA.read_text())
    conn.executescript(OPTIONS_PLAYS_DDL)
    conn.commit()
    conn.close()

    monkeypatch.setenv("CYBERSCREENER_DB", str(db_file))
    import db.models as m
    importlib.reload(m)            # rebind DB_PATH to the temp DB
    import routers.market as mk
    importlib.reload(mk)           # rebind its imported get_db to the reloaded one
    mk._DB_FILE = db_file          # expose for the seed helpers
    return mk


def _conn(market):
    c = sqlite3.connect(market._DB_FILE)
    c.row_factory = sqlite3.Row
    return c


def test_killer_play_carries_journal_contract(market):
    """The decisive assertion: a ranked ticker with an open play surfaces the
    full canonical contract (non-null) the forward-test journal reads."""
    c = _conn(market)
    _seed_scores(c, "ACME")
    _seed_open_play(c, "ACME")
    c.commit()
    c.close()

    resp = market.get_killer_plays(limit=8)
    plays = resp["plays"]
    assert plays, "expected ACME to rank into killer-plays"
    play = next(p for p in plays if p["ticker"] == "ACME")

    for field in JOURNAL_CONTRACT:
        assert play.get(field) is not None, f"{field} must be non-null for the journal"

    assert play["strategy"] == "Bear Put Spread"
    assert play["estimated_premium"] == play["premium"]   # both alias entry_price
    assert play["opt_score"] >= 65                          # journal opt gate
    assert play["rc_score"] >= 50                           # journal rc gate
    assert play["rc_score"] == 72  # play-level RC preferred over scores proxy (60)


def test_top_level_rc_score_present_without_a_play(market):
    """Even with no options_plays row, the scores-table rc_score must reach the
    payload (the journal's rc gate) — it just won't carry the play contract."""
    c = _conn(market)
    _seed_scores(c, "BETA", rc=58)
    c.commit()
    c.close()

    resp = market.get_killer_plays(limit=8)
    play = next(p for p in resp["plays"] if p["ticker"] == "BETA")
    assert play.get("rc_score") == 58          # proxy surfaced for the rc gate
    assert play.get("strategy") is None        # no play row → contract absent
