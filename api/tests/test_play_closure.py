"""
Tests for settlement_v2 play closure (core/play_closure.py).
Semantics under test are pre-registered in core/FORWARD_TEST_SEMANTICS.md.
"""
import sqlite3

import pytest

from core.play_closure import (
    parse_strikes, compute_outcome, settlement_for, close_due_plays,
    migrate_legacy_closures, backfill_entry_conviction, conviction_asof,
    gate_metrics, distinct_closed_plays, Outcome,
)
from db.migrate_play_closure import run_migration


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript("""
        CREATE TABLE options_plays (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL, generated_at TEXT NOT NULL,
            horizon TEXT, strategy TEXT, strike REAL, expiry TEXT, dte INTEGER,
            entry_price REAL, entry_iv_rank REAL, lt_score REAL, opt_score REAL,
            rc_score INTEGER, direction TEXT DEFAULT 'bullish',
            outcome_price REAL, outcome_date TEXT, pnl_pct REAL,
            status TEXT DEFAULT 'open', notes TEXT,
            max_loss REAL, risk_reward_ratio REAL
        );
        CREATE TABLE prices (ticker TEXT, date TEXT, close_price REAL);
        CREATE TABLE scans (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT);
        CREATE TABLE scores (id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER, ticker TEXT, lt_score REAL, opt_score REAL);
    """)
    run_migration(c)
    return c


def add_play(conn, **kw):
    fields = {"ticker": "TST", "generated_at": "2026-05-01 14:00:00",
              "strategy": "Long Call", "strike": 100.0, "expiry": "2026-06-01",
              "entry_price": 5.0, "status": "open", "notes": ""}
    fields.update(kw)
    cols = ", ".join(fields)
    qs = ", ".join("?" * len(fields))
    cur = conn.execute(f"INSERT INTO options_plays ({cols}) VALUES ({qs})",
                       list(fields.values()))
    return cur.lastrowid


def add_price(conn, ticker, date, close):
    conn.execute("INSERT INTO prices VALUES (?, ?, ?)", (ticker, date, close))


# ── Strike parsing ────────────────────────────────────────────────────────────

def test_parse_strikes():
    assert parse_strikes("Long Call", 230.0) == [230.0]
    assert parse_strikes("Long Call", "230.0") == [230.0]
    assert parse_strikes("Bull Call Spread", "210/230") == [210.0, 230.0]
    assert parse_strikes("Iron Condor", "270/285/315/330") == [270.0, 285.0, 315.0, 330.0]
    assert parse_strikes("Iron Condor", "270/285") is None        # wrong arity
    assert parse_strikes("Iron Condor", "330/315/285/270") is None  # not ascending
    assert parse_strikes("Long Call", "abc") is None
    assert parse_strikes("Long Call", None) is None


# ── Per-strategy outcome math ────────────────────────────────────────────────

def test_long_call_itm_win():
    o = compute_outcome({"strategy": "Long Call", "strike": 100.0, "entry_price": 5.0},
                        112.0, "2026-06-01")
    assert (o.status, o.outcome, o.win) == ("closed", "win", 1)
    assert o.realized_pnl == pytest.approx(7.0)       # max(112-100,0) - 5
    assert o.realized_return == pytest.approx(1.4)    # 7/5


def test_long_call_otm_total_loss():
    o = compute_outcome({"strategy": "Long Call", "strike": 100.0, "entry_price": 5.0},
                        95.0, "2026-06-01")
    assert (o.outcome, o.realized_return) == ("loss", -1.0)


def test_bull_call_spread_capped_gain():
    o = compute_outcome({"strategy": "Bull Call Spread", "strike": "210/230",
                         "entry_price": 4.59}, 260.0, "2026-06-01")
    assert o.outcome == "win"
    assert o.realized_pnl == pytest.approx(20.0 - 4.59)   # capped at width


def test_bull_call_spread_partial():
    o = compute_outcome({"strategy": "Bull Call Spread", "strike": "210/230",
                         "entry_price": 4.59}, 212.0, "2026-06-01")
    assert o.outcome == "loss"                            # value 2.0 < debit 4.59
    assert o.realized_pnl == pytest.approx(2.0 - 4.59)


def test_bear_put_spread():
    o = compute_outcome({"strategy": "Bear Put Spread", "strike": "230/210",
                         "entry_price": 4.0}, 205.0, "2026-06-01")
    assert o.outcome == "win"
    assert o.realized_pnl == pytest.approx(20.0 - 4.0)


def test_spread_entry_price_is_underlying_is_unresolvable():
    # early pre-fix rows filed the underlying price as entry_price
    o = compute_outcome({"strategy": "Bull Call Spread", "strike": "210/230",
                         "entry_price": 298.35, "notes": ""}, 260.0, "2026-06-01")
    assert o.status == "unresolvable"
    assert o.realized_pnl is None and o.realized_return is None


def test_straddle():
    win = compute_outcome({"strategy": "Straddle", "strike": 120.0, "entry_price": 6.8},
                          135.0, "2026-06-01")
    assert win.outcome == "win" and win.realized_pnl == pytest.approx(15.0 - 6.8)
    loss = compute_outcome({"strategy": "Straddle", "strike": 120.0, "entry_price": 6.8},
                           121.0, "2026-06-01")
    assert loss.outcome == "loss"


def test_iron_condor_inside_range_with_credit():
    o = compute_outcome({"strategy": "Iron Condor", "strike": "270/285/315/330",
                         "entry_price": 2.82}, 310.26, "2026-06-04")
    assert (o.outcome, o.win) == ("win", 1)
    assert o.realized_pnl == pytest.approx(2.82)
    assert o.realized_return == pytest.approx(2.82 / (15 - 2.82), abs=1e-4)


def test_iron_condor_credit_from_notes_when_entry_price_is_underlying():
    # the 11 legacy AAPL condors: entry_price = underlying, credit in notes
    o = compute_outcome({"strategy": "Iron Condor", "strike": "270/285/315/330",
                         "entry_price": 300.71,
                         "notes": "Sell elevated IV (306%) on both sides. Collect $2.82."},
                        310.26, "2026-06-04")
    assert (o.outcome, o.win) == ("win", 1)
    assert o.realized_pnl == pytest.approx(2.82)


def test_iron_condor_breached_with_credit():
    o = compute_outcome({"strategy": "Iron Condor", "strike": "270/285/315/330",
                         "entry_price": 2.82}, 320.0, "2026-06-04")
    assert o.outcome == "loss"
    assert o.realized_pnl == pytest.approx(2.82 - 5.0)    # S - Cs = 5 loss leg


def test_iron_condor_unknown_credit_inside_range_win_without_magnitude():
    o = compute_outcome({"strategy": "Iron Condor", "strike": "270/285/315/330",
                         "entry_price": 300.0, "notes": "no credit recorded"},
                        310.0, "2026-06-04")
    assert (o.status, o.outcome, o.win) == ("closed", "win", 1)
    assert o.realized_return is None                      # never fabricated


def test_iron_condor_unknown_credit_full_breach_is_minus_100pct():
    o = compute_outcome({"strategy": "Iron Condor", "strike": "270/285/315/330",
                         "entry_price": 300.0, "notes": ""}, 340.0, "2026-06-04")
    assert (o.outcome, o.realized_return) == ("loss", -1.0)


def test_iron_condor_unknown_credit_between_short_and_wing_unresolvable():
    o = compute_outcome({"strategy": "Iron Condor", "strike": "270/285/315/330",
                         "entry_price": 300.0, "notes": ""}, 320.0, "2026-06-04")
    assert o.status == "unresolvable"


# ── Settlement window ─────────────────────────────────────────────────────────

def test_settlement_uses_latest_price_at_or_before_expiry(conn):
    add_price(conn, "TST", "2026-06-04", 310.26)
    add_price(conn, "TST", "2026-06-08", 314.30)  # post-expiry — must be ignored
    assert settlement_for(conn, "TST", "2026-06-05") == (310.26, "2026-06-04")


def test_settlement_reachback_limited_to_3_days(conn):
    add_price(conn, "TST", "2026-06-01", 300.0)   # 4 days before expiry
    assert settlement_for(conn, "TST", "2026-06-05") is None


# ── Closure job ───────────────────────────────────────────────────────────────

def test_close_due_plays_expiry_boundary(conn):
    add_price(conn, "TST", "2026-05-31", 120.0)
    add_price(conn, "TST", "2026-06-01", 120.0)
    due = add_play(conn, expiry="2026-06-01")          # strictly before today
    on_today = add_play(conn, expiry="2026-06-02")     # expiry == today: NOT closed
    future = add_play(conn, expiry="2026-07-17")
    s = close_due_plays(conn, today="2026-06-02")
    assert s["due"] == 1 and s["closed"] == 1
    statuses = dict(conn.execute("SELECT id, status FROM options_plays").fetchall())
    assert statuses[due] == "closed"
    assert statuses[on_today] == "open"
    assert statuses[future] == "open"


def test_close_writes_pre_registered_fields(conn):
    add_price(conn, "TST", "2026-06-01", 120.0)
    pid = add_play(conn, expiry="2026-06-01")          # long call K=100, prem 5
    close_due_plays(conn, today="2026-06-03")
    row = dict(conn.execute("SELECT * FROM options_plays WHERE id = ?", (pid,)).fetchone())
    assert row["status"] == "closed" and row["outcome"] == "win" and row["win"] == 1
    assert row["settlement_price"] == 120.0 and row["settlement_date"] == "2026-06-01"
    assert row["realized_return"] == pytest.approx(3.0)   # (20-5)/5
    assert row["pnl_pct"] == pytest.approx(300.0)         # compat column
    assert row["close_method"] == "settlement_v2"
    assert row["closed_at"] == "2026-06-03"


def test_no_price_within_grace_stays_open(conn):
    pid = add_play(conn, expiry="2026-06-01")
    s = close_due_plays(conn, today="2026-06-05")      # 4 days past, no price
    assert s["pending"] == 1 and s["closed"] == 0
    assert conn.execute("SELECT status FROM options_plays WHERE id = ?",
                        (pid,)).fetchone()[0] == "open"


def test_no_price_past_grace_is_unresolvable_not_fabricated(conn):
    pid = add_play(conn, expiry="2026-06-01")
    s = close_due_plays(conn, today="2026-06-15")      # 14 days past grace=10
    assert s["unresolvable"] == 1
    row = dict(conn.execute("SELECT * FROM options_plays WHERE id = ?", (pid,)).fetchone())
    assert row["status"] == "unresolvable"
    assert row["realized_pnl"] is None and row["realized_return"] is None
    assert row["win"] is None and row["outcome"] is None


def test_idempotent_second_run_no_ops(conn):
    add_price(conn, "TST", "2026-06-01", 120.0)
    add_play(conn, expiry="2026-06-01")
    assert close_due_plays(conn, today="2026-06-03")["closed"] == 1
    s2 = close_due_plays(conn, today="2026-06-03")
    assert s2["due"] == 0 and s2["closed"] == 0


def test_one_bad_play_does_not_abort_batch(conn):
    add_price(conn, "TST", "2026-06-01", 120.0)
    bad = add_play(conn, expiry="2026-06-01", strategy="Iron Condor", strike="garbage")
    good = add_play(conn, expiry="2026-06-01")
    s = close_due_plays(conn, today="2026-06-03")
    statuses = dict(conn.execute("SELECT id, status FROM options_plays").fetchall())
    assert statuses[good] == "closed"
    assert statuses[bad] == "unresolvable"            # parse failure → flagged, not error
    assert s["errors"] == 0


# ── Legacy migration ──────────────────────────────────────────────────────────

def test_legacy_condor_migration_flips_to_win_and_keeps_audit(conn):
    add_price(conn, "AAPL", "2026-06-04", 310.26)
    pid = add_play(conn, ticker="AAPL", strategy="Iron Condor",
                   strike="270/285/315/330", expiry="2026-06-05",
                   entry_price=300.71, status="closed", pnl_pct=-12.7,
                   outcome_price=310.26, outcome_date="2026-06-06",
                   notes="Sell elevated IV (306%) on both sides. Collect $2.82.")
    s = migrate_legacy_closures(conn, today="2026-06-09")
    assert s["candidates"] == 1 and s["migrated"] == 1
    row = dict(conn.execute("SELECT * FROM options_plays WHERE id = ?", (pid,)).fetchone())
    assert row["outcome"] == "win" and row["win"] == 1
    assert row["close_method"] == "settlement_v2_migrated"
    assert "legacy close: pnl_pct=-12.7" in row["notes"]
    # idempotent: already carries close_method → not a candidate again
    assert migrate_legacy_closures(conn, today="2026-06-09")["candidates"] == 0


def test_legacy_migration_dry_run_writes_nothing(conn):
    add_price(conn, "AAPL", "2026-06-04", 310.26)
    pid = add_play(conn, ticker="AAPL", strategy="Iron Condor",
                   strike="270/285/315/330", expiry="2026-06-05",
                   entry_price=300.71, status="closed", pnl_pct=-12.7,
                   notes="Collect $2.82.")
    migrate_legacy_closures(conn, today="2026-06-09", dry_run=True)
    row = dict(conn.execute("SELECT * FROM options_plays WHERE id = ?", (pid,)).fetchone())
    assert row["pnl_pct"] == -12.7 and row["close_method"] is None


# ── Conviction backfill (no look-ahead) ──────────────────────────────────────

def test_conviction_asof_uses_latest_scan_at_or_before_entry(conn):
    conn.execute("INSERT INTO scans (id, timestamp) VALUES (1, '2026-05-01 10:00:00')")
    conn.execute("INSERT INTO scans (id, timestamp) VALUES (2, '2026-05-01 13:00:00')")
    conn.execute("INSERT INTO scans (id, timestamp) VALUES (3, '2026-05-01 15:00:00')")
    conn.execute("INSERT INTO scores (scan_id, ticker, lt_score, opt_score) VALUES (1,'TST',50,60)")
    conn.execute("INSERT INTO scores (scan_id, ticker, lt_score, opt_score) VALUES (2,'TST',55,70)")
    conn.execute("INSERT INTO scores (scan_id, ticker, lt_score, opt_score) VALUES (3,'TST',90,90)")
    c = conviction_asof(conn, "TST", "2026-05-01 14:00:00")
    assert c["lt_score"] == 55 and c["opt_score"] == 70   # scan 3 (later) excluded
    assert c["conviction"] == pytest.approx(0.6 * 70 + 0.4 * 55)


def test_backfill_entry_conviction(conn):
    conn.execute("INSERT INTO scans (id, timestamp) VALUES (1, '2026-05-01 10:00:00')")
    conn.execute("INSERT INTO scores (scan_id, ticker, lt_score, opt_score) VALUES (1,'TST',50,75)")
    pid = add_play(conn)                                   # generated 14:00
    orphan = add_play(conn, ticker="NOSCORES")
    s = backfill_entry_conviction(conn)
    assert s["filled"] == 1 and s["no_scores_found"] == 1
    assert conn.execute("SELECT entry_conviction FROM options_plays WHERE id=?",
                        (pid,)).fetchone()[0] == pytest.approx(65.0)
    assert conn.execute("SELECT entry_conviction FROM options_plays WHERE id=?",
                        (orphan,)).fetchone()[0] is None


# ── Gate metrics over distinct plays ──────────────────────────────────────────

def test_distinct_closed_plays_dedups_to_earliest(conn):
    add_price(conn, "TST", "2026-06-01", 120.0)
    first = add_play(conn, expiry="2026-06-01", generated_at="2026-05-01 10:00:00")
    add_play(conn, expiry="2026-06-01", generated_at="2026-05-01 11:00:00")  # dup
    add_play(conn, expiry="2026-06-01", generated_at="2026-05-01 12:00:00")  # dup
    close_due_plays(conn, today="2026-06-03")
    distinct = distinct_closed_plays(conn)
    assert len(distinct) == 1 and distinct[0]["id"] == first


def test_gate_metrics_buckets_and_profit_factor(conn):
    add_price(conn, "W", "2026-06-01", 120.0)
    add_price(conn, "L", "2026-06-01", 90.0)
    add_play(conn, ticker="W", expiry="2026-06-01")        # +300% win
    add_play(conn, ticker="L", expiry="2026-06-01")        # -100% loss
    close_due_plays(conn, today="2026-06-03")
    conn.execute("UPDATE options_plays SET entry_conviction = 70 WHERE ticker='W'")
    conn.execute("UPDATE options_plays SET entry_conviction = 40 WHERE ticker='L'")
    m = gate_metrics(conn)
    assert m["overall"]["n_decided"] == 2
    assert m["overall"]["win_rate"] == pytest.approx(0.5)
    assert m["overall"]["profit_factor"] == pytest.approx(3.0)   # 3.0 / |-1.0|
    assert m["overall"]["expectancy"] == pytest.approx(1.0)      # (3.0 - 1.0)/2
    assert m["buckets"]["65-75"]["n_wins"] == 1
    assert m["buckets"]["<55"]["n_losses"] == 1


def test_gate_metrics_unresolvable_counted_not_silently_dropped(conn):
    add_play(conn, expiry="2026-06-01")                    # no price ever
    close_due_plays(conn, today="2026-06-15")              # → unresolvable
    m = gate_metrics(conn)
    assert m["overall"]["n_unresolvable"] == 1
    assert m["overall"]["n_decided"] == 0 and m["overall"]["win_rate"] is None


# ── SESSION-TEST-HARNESS additions ─────────────────────────────────────────────
# Long puts had no coverage (every other strategy did), and no single test swept
# the win/loss SIGN across all strategies — the exact failure mode of the legacy
# closure (directional x4 math booking condor wins as losses, PR #12).

def test_long_put_itm_win():
    o = compute_outcome({"strategy": "Long Put", "strike": 100.0, "entry_price": 5.0},
                        88.0, "2026-06-01")
    assert (o.status, o.outcome, o.win) == ("closed", "win", 1)
    assert o.realized_pnl == pytest.approx(7.0)       # max(100-88,0) - 5
    assert o.realized_return == pytest.approx(1.4)    # 7/5


def test_long_put_otm_total_loss():
    o = compute_outcome({"strategy": "Long Put", "strike": 100.0, "entry_price": 5.0},
                        105.0, "2026-06-01")
    assert (o.outcome, o.win, o.realized_return) == ("loss", 0, -1.0)


def test_long_put_partial_loss():
    # ITM but intrinsic < premium: value 3, debit 5 -> loss of 2 (-40%)
    o = compute_outcome({"strategy": "Long Put", "strike": 100.0, "entry_price": 5.0},
                        97.0, "2026-06-01")
    assert o.outcome == "loss"
    assert o.realized_pnl == pytest.approx(-2.0)
    assert o.realized_return == pytest.approx(-0.4)


# Sign sweep: (play, winning settlement, losing settlement) per strategy.
# A favorable move must NEVER book as a loss, nor an adverse move as a win —
# the sign-flip class that corrupted the 11 AAPL condors must be impossible
# for every strategy the generator can emit.
_SIGN_CASES = [
    ("Long Call",
     {"strategy": "Long Call", "strike": 100.0, "entry_price": 4.0}, 120.0, 90.0),
    ("Long Put",
     {"strategy": "Long Put", "strike": 100.0, "entry_price": 4.0}, 80.0, 110.0),
    ("Bull Call Spread",
     {"strategy": "Bull Call Spread", "strike": "100/110", "entry_price": 3.0},
     115.0, 95.0),
    ("Bear Put Spread",
     {"strategy": "Bear Put Spread", "strike": "110/100", "entry_price": 3.0},
     95.0, 115.0),
    ("Straddle",
     {"strategy": "Straddle", "strike": 100.0, "entry_price": 5.0}, 120.0, 101.0),
    ("Iron Condor",
     {"strategy": "Iron Condor", "strike": "85/90/110/115", "entry_price": 1.5},
     100.0, 120.0),
]


@pytest.mark.parametrize("name, play, win_px, loss_px", _SIGN_CASES,
                         ids=[c[0] for c in _SIGN_CASES])
def test_outcome_sign_matches_thesis(name, play, win_px, loss_px):
    won = compute_outcome(dict(play), win_px, "2026-06-01")
    lost = compute_outcome(dict(play), loss_px, "2026-06-01")
    assert (won.status, won.outcome, won.win) == ("closed", "win", 1), (
        f"{name}: favorable settlement {win_px} booked as {won.outcome}")
    assert won.realized_return > 0
    assert (lost.status, lost.outcome, lost.win) == ("closed", "loss", 0), (
        f"{name}: adverse settlement {loss_px} booked as {lost.outcome}")
    assert lost.realized_return < 0
