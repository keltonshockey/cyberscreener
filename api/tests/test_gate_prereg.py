"""
SESSION-GATE-PREREG — cohort derivation, Wilson CI, pre-registered pass/fail
rules, never-pooled reporting, and the read-only guarantee.
"""
import sqlite3

import pytest

from core import gate_report as gr


# ── fixtures ───────────────────────────────────────────────────────────────────

DDL = """
CREATE TABLE options_plays (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL, generated_at TEXT NOT NULL,
    horizon TEXT, strategy TEXT, strike TEXT, expiry TEXT, dte INTEGER,
    entry_price REAL, entry_iv_rank REAL, lt_score REAL, opt_score REAL,
    rc_score INTEGER, direction TEXT, outcome_price REAL, outcome_date TEXT,
    pnl_pct REAL, status TEXT DEFAULT 'open', notes TEXT,
    max_loss REAL, risk_reward_ratio REAL,
    closed_at TEXT, settlement_price REAL, settlement_date TEXT,
    realized_pnl REAL, realized_return REAL, outcome TEXT, win INTEGER,
    close_method TEXT, entry_conviction REAL, score_version TEXT
);
"""


@pytest.fixture
def conn():
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.executescript(DDL)
    return c


def add(conn, *, ticker, generated_at, conviction, win, ret, status="closed",
        score_version=None, strategy="Long Call", strike="100", expiry="2026-06-18"):
    conn.execute(
        "INSERT INTO options_plays (ticker, generated_at, strategy, strike, expiry,"
        " entry_price, status, entry_conviction, win, realized_return, score_version)"
        " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (ticker, generated_at, strategy, strike, expiry, 4.0, status,
         conviction, win, ret, score_version))


# ── cohort derivation (GATE_PREREG.md section 1) ───────────────────────────────

def test_cohort_a_before_boundary():
    assert gr.cohort_of({"generated_at": "2026-05-12 14:00:00"}) == "A"
    assert gr.cohort_of({"generated_at": "2026-06-09 03:59:59"}) == "A"


def test_cohort_a_includes_june_8_mixed_regime_rows():
    """6/8 evening rows (post-IV-fix, pre-directional-fix) are deliberately A."""
    assert gr.cohort_of({"generated_at": "2026-06-08 22:00:00"}) == "A"


def test_cohort_b_from_boundary():
    assert gr.cohort_of({"generated_at": "2026-06-09 04:00:00"}) == "B"
    assert gr.cohort_of({"generated_at": "2026-07-01 12:00:00"}) == "B"


def test_cohort_c_score_version_is_authoritative():
    """v2-baseline tags C regardless of timestamp (even a weird clock)."""
    assert gr.cohort_of({"generated_at": "2026-06-01 00:00:00",
                         "score_version": "v2-baseline"}) == "C"
    assert gr.cohort_of({"generated_at": "2026-08-01 00:00:00",
                         "score_version": "v2-baseline"}) == "C"


def test_cohort_handles_missing_score_version_column():
    """Pre-#14 databases have no score_version key at all."""
    assert gr.cohort_of({"generated_at": "2026-07-01 00:00:00"}) == "B"


# ── Wilson CI ──────────────────────────────────────────────────────────────────

def test_wilson_ci_known_value():
    """8/10 wins: Wilson 95% = (0.4902, 0.9433) (standard reference value)."""
    lo, hi = gr.wilson_ci(8, 10)
    assert lo == pytest.approx(0.4902, abs=0.001)
    assert hi == pytest.approx(0.9433, abs=0.001)


def test_wilson_ci_empty_and_bounds():
    assert gr.wilson_ci(0, 0) is None
    lo, hi = gr.wilson_ci(0, 5)
    assert lo == 0.0 and hi < 0.5
    lo, hi = gr.wilson_ci(5, 5)
    assert hi == 1.0 and lo > 0.5


# ── bucketing + never-pooled ───────────────────────────────────────────────────

def test_buckets_and_cohorts_never_pooled(conn):
    # cohort A: 1 winner at conviction 70; cohort B: 1 loser at 70
    add(conn, ticker="AAA", generated_at="2026-05-15 10:00:00",
        conviction=70, win=1, ret=0.5)
    add(conn, ticker="BBB", generated_at="2026-06-10 10:00:00",
        conviction=70, win=0, ret=-0.5)
    table = gr.gate_table(conn)
    assert table["A"]["65-75"]["n_decided"] == 1
    assert table["A"]["65-75"]["win_rate"] == 1.0
    assert table["B"]["65-75"]["n_decided"] == 1
    assert table["B"]["65-75"]["win_rate"] == 0.0
    assert table["C"][gr.GATE_AGG]["n_decided"] == 0
    # pooling A+B would read 0.5 — assert no such number appears anywhere
    for cohort in table.values():
        for m in cohort.values():
            assert m["win_rate"] != 0.5


def test_bucket_boundaries(conn):
    for conv, bucket in ((64.9, "<65"), (65.0, "65-75"), (74.9, "65-75"),
                         (75.0, "75-85"), (85.0, "85+")):
        conn.execute("DELETE FROM options_plays")
        add(conn, ticker="T", generated_at="2026-06-10 10:00:00",
            conviction=conv, win=1, ret=0.1)
        table = gr.gate_table(conn)
        assert table["B"][bucket]["n_decided"] == 1, (conv, bucket)


def test_duplicates_not_pseudo_replicated(conn):
    """Same (ticker,strategy,strike,expiry) logged twice counts once
    (FORWARD_TEST_SEMANTICS dedup, inherited)."""
    for _ in range(3):
        add(conn, ticker="DUP", generated_at="2026-06-10 10:00:00",
            conviction=70, win=1, ret=0.2)
    table = gr.gate_table(conn)
    assert table["B"]["65-75"]["n_decided"] == 1


def test_unresolvable_reported_not_dropped(conn):
    add(conn, ticker="UNR", generated_at="2026-06-10 10:00:00",
        conviction=70, win=None, ret=None, status="unresolvable")
    m = gr.gate_table(conn)["B"]["65-75"]
    assert m["n_unresolvable"] == 1 and m["n_decided"] == 0


# ── pre-registered rules (sections 3-4) ────────────────────────────────────────

def _seed_cohort_c(conn, n_win, n_loss, win_ret=0.6, loss_ret=-0.4):
    for i in range(n_win):
        add(conn, ticker=f"W{i}", generated_at="2026-08-01 10:00:00",
            conviction=70, win=1, ret=win_ret, score_version="v2-baseline",
            strike=str(100 + i))
    for i in range(n_loss):
        add(conn, ticker=f"L{i}", generated_at="2026-08-01 10:00:00",
            conviction=70, win=0, ret=loss_ret, score_version="v2-baseline",
            strike=str(500 + i))


def test_underpowered_hot_streak_is_not_a_pass(conn):
    """60% win on n=50 with payoff 1.5: directional, never a pass."""
    _seed_cohort_c(conn, 30, 20)
    table = gr.gate_table(conn)
    ev = gr.evaluate(table)
    assert table["C"][gr.GATE_AGG]["significance"] == "DIRECTIONAL, NOT SIGNIFICANT"
    assert ev["pass_bar_met"] is False
    assert "NO VERDICT" in ev["verdict"]


def test_pass_bar_met_only_at_powered_n(conn):
    """58% win, payoff 1.5, n=400 -> pass."""
    _seed_cohort_c(conn, 232, 168)
    ev = gr.evaluate(gr.gate_table(conn))
    assert ev["pass_bar_met"] is True
    assert "PASS BAR MET" in ev["verdict"]


def test_fail_rule_triggers_at_80_under_50(conn):
    """Cohort C win 45% at n=80 -> mechanical stop-work trigger."""
    _seed_cohort_c(conn, 36, 44)
    ev = gr.evaluate(gr.gate_table(conn))
    assert ev["fail_rule_triggered"] is True
    assert "FAIL RULE TRIGGERED" in ev["verdict"]


def test_fail_rule_not_armed_below_80(conn):
    _seed_cohort_c(conn, 35, 44)   # n=79, win 44%
    ev = gr.evaluate(gr.gate_table(conn))
    assert ev["fail_rule_triggered"] is False


def test_cohort_ab_results_cannot_trigger_rules(conn):
    """A/B are context: even a catastrophic B read leaves the verdict on C."""
    for i in range(100):
        add(conn, ticker=f"B{i}", generated_at="2026-06-10 10:00:00",
            conviction=70, win=0, ret=-0.5, strike=str(i))
    ev = gr.evaluate(gr.gate_table(conn))
    assert ev["fail_rule_triggered"] is False and ev["pass_bar_met"] is False


# ── rendering + summary ────────────────────────────────────────────────────────

def test_markdown_is_ascii_and_carries_significance(conn):
    _seed_cohort_c(conn, 3, 1)
    table = gr.gate_table(conn)
    md = gr.render_markdown(table, gr.evaluate(table), "x.db", "2026-06-21")
    md.encode("ascii")   # raises if any non-ASCII slipped in
    assert "DIRECTIONAL, NOT SIGNIFICANT" in md
    assert "THE GATING COHORT" in md


def test_summary_line_prefers_c_falls_back_to_b(conn):
    add(conn, ticker="BBB", generated_at="2026-06-10 10:00:00",
        conviction=70, win=1, ret=0.3)
    table = gr.gate_table(conn)
    line = gr.summary_line(table, gr.evaluate(table), "2026-06-21")
    assert "cohort B (context - no C plays yet)" in line

    _seed_cohort_c(conn, 2, 1)
    table = gr.gate_table(conn)
    line = gr.summary_line(table, gr.evaluate(table), "2026-06-21")
    assert line.startswith("Gate 2026-06-21 cohort C:")


# ── read-only guarantee ────────────────────────────────────────────────────────

def test_open_ro_cannot_write(tmp_path):
    db = tmp_path / "ro.db"
    c = sqlite3.connect(db)
    c.executescript(DDL)
    c.commit()
    c.close()

    ro = gr.open_ro(str(db))
    with pytest.raises(sqlite3.OperationalError):
        ro.execute("INSERT INTO options_plays (ticker, generated_at) VALUES ('X','2026-01-01')")
    ro.close()


def test_pushover_skips_without_keys(monkeypatch, capsys):
    monkeypatch.delenv("PUSHOVER_TOKEN", raising=False)
    monkeypatch.delenv("PUSHOVER_USER", raising=False)
    assert gr.send_pushover("test") is False
