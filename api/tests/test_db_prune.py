"""
Tests for scripts/db_prune.py against a synthetic DB.

Verifies the retention policy, every protected-row invariant, idempotency,
and the VACUUM INTO swap — all on a throwaway database.
"""

import datetime as dt
import importlib.util
import os
import sqlite3
import sys

import pytest

SCRIPT = os.path.join(os.path.dirname(__file__), "..", "..", "scripts", "db_prune.py")
spec = importlib.util.spec_from_file_location("db_prune", SCRIPT)
db_prune = importlib.util.module_from_spec(spec)
spec.loader.exec_module(db_prune)

NOW = dt.datetime(2026, 6, 9, 12, 0, 0)
TICKERS = ["AAA", "BBB", "CCC"]


def _make_db(path):
    """400 days of history, 3 scans/day, 3 tickers, signals, plays, prices."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE scans (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT NOT NULL);
        CREATE TABLE scores (id INTEGER PRIMARY KEY AUTOINCREMENT, scan_id INTEGER,
                             ticker TEXT, lt_score REAL, opt_score REAL, iv_30d REAL);
        CREATE TABLE signals (id INTEGER PRIMARY KEY AUTOINCREMENT, scan_id INTEGER,
                              ticker TEXT, signal_text TEXT);
        CREATE TABLE prices (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT,
                             date TEXT, close_price REAL, UNIQUE(ticker, date));
        CREATE TABLE options_plays (id INTEGER PRIMARY KEY AUTOINCREMENT, ticker TEXT,
                                    generated_at TEXT, expiry TEXT, status TEXT);
        CREATE TABLE score_weights (id INTEGER PRIMARY KEY AUTOINCREMENT, timestamp TEXT,
                                    score_type TEXT, weights_json TEXT);
        CREATE INDEX idx_scores_scan ON scores(scan_id);
        CREATE INDEX idx_signals_scan ON signals(scan_id);
    """)
    for day in range(400, -1, -1):
        d = NOW - dt.timedelta(days=day)
        for hour in (10, 13, 16):
            ts = d.replace(hour=hour).strftime("%Y-%m-%d %H:%M:%S")
            cur = conn.execute("INSERT INTO scans (timestamp) VALUES (?)", (ts,))
            scan_id = cur.lastrowid
            for t in TICKERS:
                conn.execute(
                    "INSERT INTO scores (scan_id, ticker, lt_score, opt_score, iv_30d)"
                    " VALUES (?, ?, ?, ?, ?)",
                    (scan_id, t, 50 + day % 30, 40 + hour, 30.0 + day % 50))
                conn.execute(
                    "INSERT INTO signals (scan_id, ticker, signal_text) VALUES (?, ?, ?)",
                    (scan_id, t, f"sig d{day} h{hour}"))
        conn.execute(
            "INSERT OR IGNORE INTO prices (ticker, date, close_price) VALUES (?, ?, ?)",
            ("AAA", d.strftime("%Y-%m-%d"), 100.0 + day))
    for i, status in enumerate(["open"] * 5 + ["closed"] * 3):
        conn.execute(
            "INSERT INTO options_plays (ticker, generated_at, expiry, status)"
            " VALUES (?, ?, ?, ?)",
            (TICKERS[i % 3], "2026-05-01 10:00:00", "2026-07-17", status))
    conn.execute("INSERT INTO score_weights (timestamp, score_type, weights_json)"
                 " VALUES ('2026-06-06', 'lt', '{}')")
    conn.commit()
    conn.close()


@pytest.fixture
def cfg(tmp_path):
    db = str(tmp_path / "test.db")
    _make_db(db)
    c = dict(db_prune.DEFAULTS)
    c.update({
        "db_path": db,
        "backup_dir": str(tmp_path),
        "log_file": str(tmp_path / "prune.log"),
        "scanner_log": str(tmp_path / "missing.log"),
        "manage_services": False,
        "notify": False,
    })
    return c


def _counts(db):
    conn = sqlite3.connect(db)
    conn.row_factory = sqlite3.Row
    out = db_prune.all_table_counts(conn)
    conn.close()
    return out


def test_plan_is_pure_readonly(cfg):
    before = _counts(cfg["db_path"])
    conn = db_prune.get_conn(cfg["db_path"], ro=True)
    plan = db_prune.build_plan(conn, cfg, NOW)
    conn.close()
    assert _counts(cfg["db_path"]) == before
    assert plan["scores_delete"] > 0
    assert plan["signals_delete"] > 0


def test_policy_windows(cfg):
    conn = db_prune.get_conn(cfg["db_path"])
    stats = db_prune.execute_prune(conn, cfg, NOW)
    cuts = stats["cutoffs"]

    # Full window: every scan in the last 30 days keeps all 3 daily scans
    full = conn.execute(
        "SELECT COUNT(DISTINCT scan_id) FROM scores WHERE scan_id IN"
        " (SELECT id FROM scans WHERE timestamp >= ?)", (cuts["full_cutoff_ts"],)
    ).fetchone()[0]
    # 30 full days x 3 scans + 2 scans on the boundary day (its 10:00 scan is
    # before the cutoff and survives as that day's daily keeper instead)
    assert full == 30 * 3 + 2

    # Daily band: exactly one scan per day retains scores
    rows = conn.execute("""
        SELECT date(sc.timestamp) AS d, COUNT(DISTINCT s.scan_id) AS n
        FROM scores s JOIN scans sc ON s.scan_id = sc.id
        WHERE sc.timestamp >= ? AND sc.timestamp < ?
        GROUP BY d
    """, (cuts["daily_cutoff_ts"], cuts["full_cutoff_ts"])).fetchall()
    assert len(rows) == 336  # every day in the band still represented (incl. both boundary days)
    assert all(r[1] == 1 for r in rows)
    # ... and it is the LAST scan of each day (hour 16), except the boundary day
    # whose later scans belong to the full window (its keeper is the 10:00 scan)
    hours = conn.execute("""
        SELECT strftime('%H', sc.timestamp) AS h, COUNT(DISTINCT date(sc.timestamp))
        FROM scores s JOIN scans sc ON s.scan_id = sc.id
        WHERE sc.timestamp >= ? AND sc.timestamp < ?
        GROUP BY h ORDER BY h
    """, (cuts["daily_cutoff_ts"], cuts["full_cutoff_ts"])).fetchall()
    assert dict(hours) == {"10": 1, "16": 335}

    # Weekly band: at most one scan per ISO week, every week represented
    rows = conn.execute("""
        SELECT strftime('%Y-%W', sc.timestamp) AS w, COUNT(DISTINCT s.scan_id) AS n
        FROM scores s JOIN scans sc ON s.scan_id = sc.id
        WHERE sc.timestamp < ?
        GROUP BY w
    """, (cuts["daily_cutoff_ts"],)).fetchall()
    assert rows and all(r[1] == 1 for r in rows)

    # Signals: nothing older than the signal window survives
    oldest = conn.execute(
        "SELECT MIN(sc.timestamp) FROM signals sg JOIN scans sc ON sg.scan_id = sc.id"
    ).fetchone()[0]
    assert oldest >= cuts["signals_cutoff_ts"]
    conn.close()


def test_protected_tables_untouched(cfg):
    before = _counts(cfg["db_path"])
    conn = db_prune.get_conn(cfg["db_path"])
    db_prune.execute_prune(conn, cfg, NOW)
    conn.close()
    after = _counts(cfg["db_path"])
    for table in before:
        if table in db_prune.PRUNABLE_TABLES:
            continue
        assert after[table] == before[table], f"{table} changed"


def test_idempotent(cfg):
    conn = db_prune.get_conn(cfg["db_path"])
    first = db_prune.execute_prune(conn, cfg, NOW)
    second = db_prune.execute_prune(conn, cfg, NOW)
    conn.close()
    assert first["scores_deleted"] > 0
    assert second["scores_deleted"] == 0
    assert second["signals_deleted"] == 0


def test_assertion_rolls_back(cfg, monkeypatch):
    """If any protected invariant trips, the whole prune must roll back."""
    real_fp = db_prune.protected_fingerprint
    calls = {"n": 0}

    def corrupted(conn):
        calls["n"] += 1
        fp = real_fp(conn)
        if calls["n"] > 1:  # post-delete check sees a 'changed' journal
            fp["_options_plays_checksum"] = (0, 0, 0)
        return fp

    monkeypatch.setattr(db_prune, "protected_fingerprint", corrupted)
    before = _counts(cfg["db_path"])
    conn = db_prune.get_conn(cfg["db_path"])
    with pytest.raises(db_prune.PruneAssertionError):
        db_prune.execute_prune(conn, cfg, NOW)
    conn.close()
    assert _counts(cfg["db_path"]) == before  # rolled back, nothing deleted


def test_backup_and_restore(cfg):
    backup = db_prune.make_backup(cfg["db_path"], cfg["backup_dir"])
    ok, why = db_prune.verify_backup(backup, 8)
    assert ok, why
    before = _counts(cfg["db_path"])

    conn = db_prune.get_conn(cfg["db_path"])
    db_prune.execute_prune(conn, cfg, NOW)
    conn.close()
    assert _counts(cfg["db_path"]) != before

    # Restore = copy the backup over the pruned DB; contents must match original
    import shutil
    shutil.copy(backup, cfg["db_path"])
    assert _counts(cfg["db_path"]) == before


def test_vacuum_swap_shrinks_and_preserves(cfg):
    conn = db_prune.get_conn(cfg["db_path"])
    db_prune.execute_prune(conn, cfg, NOW)
    conn.close()

    conn = db_prune.get_conn(cfg["db_path"], ro=True)
    expected = db_prune.all_table_counts(conn)
    conn.close()

    size_before = os.path.getsize(cfg["db_path"])
    old, new = db_prune.vacuum_swap(cfg, expected)
    assert new < size_before
    assert _counts(cfg["db_path"]) == expected


def test_guard_scan_in_flight(tmp_path, cfg):
    logf = tmp_path / "scanner.log"
    logf.write_text("2026-06-09 11:50:00 [INFO] Starting scan of 526 tickers...\n")
    busy, _ = db_prune.scan_in_flight(str(logf))
    assert busy
    logf.write_text(
        "2026-06-09 11:50:00 [INFO] Starting scan of 526 tickers...\n"
        "2026-06-09 12:20:00 [INFO] Scan #99 complete: 479 tickers in 1800.0s\n")
    busy, _ = db_prune.scan_in_flight(str(logf))
    assert not busy
    # Unreadable log must fail CLOSED (treated as in-flight)
    busy, _ = db_prune.scan_in_flight(str(tmp_path / "nope.log"))
    assert busy


def test_guard_idle_window(cfg):
    ok, _ = db_prune.in_idle_window(cfg, dt.datetime(2026, 6, 10, 3, 0))   # Wed 03:00
    assert ok
    ok, _ = db_prune.in_idle_window(cfg, dt.datetime(2026, 6, 10, 14, 0))  # Wed 14:00
    assert not ok
    ok, _ = db_prune.in_idle_window(cfg, dt.datetime(2026, 6, 13, 14, 0))  # Saturday
    assert ok
