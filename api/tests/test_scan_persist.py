"""
Regression test for the scan-persist column/value-count mismatch that froze
production scans at #1412 (2026-06-04 → 2026-06-08).

Root cause: save_scan()'s `scores` INSERT listed 67 columns (rc_score had been
appended) but supplied only 66 `?` placeholders, so SQLite raised
"66 values for 67 columns" at parse time and aborted the entire scan persist
every 30-min cycle — scan_id never advanced past 1412.

These tests run save_scan() against a temp SQLite built from the REAL production
schema (fixtures/scores_schema.sql, captured read-only from the droplet) rather
than the legacy CREATE TABLE in models.py, and assert:
  1. a representative scan persists and scan_id increments;
  2. rc_score (the previously-missing column) is written;
  3. one malformed row no longer nukes the whole scan (the new guardrail).
"""
import os
import sys
import sqlite3
import importlib
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

SCHEMA = Path(__file__).parent / "fixtures" / "scores_schema.sql"


@pytest.fixture
def models(tmp_path, monkeypatch):
    """A db.models module bound to a fresh temp DB with the real prod schema."""
    db_file = tmp_path / "test_cyberscreener.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(SCHEMA.read_text())
    conn.commit()
    conn.close()

    monkeypatch.setenv("CYBERSCREENER_DB", str(db_file))
    import db.models as m
    importlib.reload(m)  # re-read module-level DB_PATH from the patched env
    return m


def _row(ticker="ACME", **kw):
    """A representative scored-ticker result dict (the shape run_scan emits)."""
    base = dict(
        ticker=ticker, price=100.0, market_cap_b=12.3,
        lt_score=72.0, opt_score=64.0, rc_score=58,
        rsi=55.0, sma_20=98.0, iv_30d=45.0,
        sector="cyber", subsector="saas", scoring_profile="saas",
        lt_breakdown={"rule_of_40": {"points": 20}},
        opt_breakdown={"iv_context": {"points": 18}},
        lt_reasons=["🚀 strong growth"], opt_reasons=["⚠️ elevated IV"],
    )
    base.update(kw)
    return base


def test_save_scan_persists_and_increments(models):
    """The full INSERT binds and commits; scan_id advances across scans."""
    sid1, _ = models.save_scan(
        [_row("ACME"), _row("BETA")],
        intel_layers=["sec", "sentiment"], duration_seconds=12.3,
    )
    assert sid1 == 1

    conn = models.get_db()
    count = conn.execute(
        "SELECT COUNT(*) FROM scores WHERE scan_id=?", (sid1,)
    ).fetchone()[0]
    rc = conn.execute(
        "SELECT rc_score FROM scores WHERE scan_id=? AND ticker='ACME'", (sid1,)
    ).fetchone()[0]
    conn.close()

    assert count == 2
    assert rc == 58  # the previously-missing column actually persisted

    # A second scan must increment the id (was frozen at #1412 in prod).
    sid2, _ = models.save_scan([_row("ACME")])
    assert sid2 == sid1 + 1


def test_one_bad_row_does_not_drop_whole_scan(models):
    """Guardrail: a single unbindable row is logged + skipped, scan still commits."""
    good = _row("GOOD")
    bad = _row("BAD")
    bad["price"] = object()  # unbindable type → this row's INSERT raises

    sid, _ = models.save_scan([good, bad])

    conn = models.get_db()
    tickers = [
        r[0] for r in conn.execute(
            "SELECT ticker FROM scores WHERE scan_id=?", (sid,)
        ).fetchall()
    ]
    conn.close()

    assert "GOOD" in tickers      # healthy row committed despite the bad sibling
    assert "BAD" not in tickers   # bad row dropped, not the entire scan


def test_total_wipeout_rolls_back_and_raises(models):
    """If EVERY row fails (a systemic mismatch, like the #1412 freeze), save_scan
    must NOT commit a hollow scan that bumps scan_id while holding zero scores —
    that would make /health look fresh and hide the failure. It rolls back and
    raises instead, keeping the breakage loud and visible."""
    rows = [_row("X1"), _row("X2")]
    for r in rows:
        r["price"] = object()  # every row unbindable → total failure

    with pytest.raises(RuntimeError):
        models.save_scan(rows)

    conn = models.get_db()
    scans = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    scores = conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    conn.close()
    assert scans == 0   # the scans row was rolled back, not committed
    assert scores == 0


def test_init_db_schema_supports_save_scan(tmp_path, monkeypatch):
    """Migration agreement / fresh-deploy guard: a scores table built purely by
    init_db() (no historical ALTERs) must carry every column save_scan writes —
    including sector/threat/rc_score. The old migrate-before-create order left a
    fresh DB missing them, which would re-break scans on any disaster recovery."""
    monkeypatch.setenv("CYBERSCREENER_DB", str(tmp_path / "fresh.db"))
    import db.models as m
    importlib.reload(m)
    m.init_db()

    sid, _ = m.save_scan([_row("FRESH")])

    conn = m.get_db()
    row = conn.execute(
        "SELECT rc_score, sector, scoring_profile FROM scores WHERE scan_id=?", (sid,)
    ).fetchone()
    conn.close()
    assert row[0] == 58
    assert row[1] == "cyber"
    assert row[2] == "saas"
