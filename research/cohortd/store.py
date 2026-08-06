"""
Cohort D storage — a NEW database, wholly separate from the app's.

PREREG_COHORT_D.md §11 (isolation): this lane never opens `cyberscreener.db`,
not even read-only. It writes only `~/cs-research/cohortD.db`, which nothing
else reads or writes.

Append-only by construction (§11):
  * entries deduplicate on `cycle_date` via INSERT OR IGNORE,
  * settlement fills only NULL fields via `WHERE settlement_price IS NULL`,
so a re-run can add rows and complete settlements but can never alter a value
already recorded. `api/tests/test_cohortd.py` proves this by hashing the DB.

SKIPPED cycles are stored too. A filter whose rejections are not recorded cannot
be audited, and the rejection rate is a reported statistic (§7).
"""

from __future__ import annotations

import os
import sqlite3

DEFAULT_DB = "~/cs-research/cohortD.db"

# Bumped only by a NEW pre-registration (§10). Never reused across rule changes.
COHORT_VERSION = "D1"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cycles (
    cycle_date          TEXT PRIMARY KEY,
    cohort_version      TEXT NOT NULL,
    decision            TEXT NOT NULL,          -- ENTER | SKIP
    spot                REAL,
    iv30                REAL,
    har_forecast        REAL,
    garch_forecast      REAL,
    spread              REAL,                   -- iv30 - har_forecast, vol points
    threshold           REAL NOT NULL,
    expiry              TEXT,
    dte                 INTEGER,
    short_put           REAL,
    long_put            REAL,
    short_call          REAL,
    long_call           REAL,
    credit              REAL,
    put_width           REAL,
    call_width          REAL,
    defined_risk        REAL,
    settlement_price    REAL,
    pnl                 REAL,
    r_multiple          REAL,
    win                 INTEGER,
    entered_at          TEXT,
    settled_at          TEXT,
    notes               TEXT
);
CREATE INDEX IF NOT EXISTS idx_cycles_expiry ON cycles(expiry);
CREATE INDEX IF NOT EXISTS idx_cycles_decision ON cycles(decision);
"""

ENTRY_FIELDS = [
    "cycle_date", "cohort_version", "decision", "spot", "iv30", "har_forecast",
    "garch_forecast", "spread", "threshold", "expiry", "dte", "short_put",
    "long_put", "short_call", "long_call", "credit", "put_width", "call_width",
    "defined_risk", "entered_at", "notes",
]


def db_path(path: str | None = None) -> str:
    return os.path.abspath(os.path.expanduser(path or DEFAULT_DB))


def connect(path: str | None = None) -> sqlite3.Connection:
    """
    Open (creating if needed) the cohort D database.

    Deliberately NOT a read-only door: this lane owns this file outright. What
    it must never touch is `cyberscreener.db`, and it has no code path that
    names it.
    """
    p = db_path(path)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def record_cycle(conn, row: dict) -> bool:
    """
    Insert a cycle. Returns True if it was new, False if the date already existed.

    `INSERT OR IGNORE` is the dedup: re-running the same cycle date is a no-op,
    never an update. This is what makes a daily launchd job safe to re-run.
    """
    payload = {k: row.get(k) for k in ENTRY_FIELDS}
    payload["cohort_version"] = payload.get("cohort_version") or COHORT_VERSION
    cols = ",".join(ENTRY_FIELDS)
    marks = ",".join("?" for _ in ENTRY_FIELDS)
    cur = conn.execute(f"INSERT OR IGNORE INTO cycles ({cols}) VALUES ({marks})",
                       [payload[k] for k in ENTRY_FIELDS])
    conn.commit()
    return cur.rowcount == 1


def settle_cycle(conn, cycle_date: str, settlement: dict, settled_at: str) -> bool:
    """
    Fill settlement fields, once.

    The `settlement_price IS NULL` guard means a second settlement attempt
    cannot overwrite the first — a re-run, a corrected price feed, or a
    duplicate launchd firing all leave the original record intact.
    """
    cur = conn.execute(
        """UPDATE cycles
              SET settlement_price = ?, pnl = ?, r_multiple = ?, win = ?, settled_at = ?
            WHERE cycle_date = ?
              AND decision = 'ENTER'
              AND settlement_price IS NULL""",
        (settlement["settlement_price"], settlement["pnl"], settlement["r_multiple"],
         1 if settlement["win"] else 0, settled_at, cycle_date))
    conn.commit()
    return cur.rowcount == 1


def open_positions(conn, on_or_before: str):
    """Entered cycles awaiting settlement whose expiry has arrived."""
    return conn.execute(
        """SELECT * FROM cycles
            WHERE decision = 'ENTER' AND settlement_price IS NULL
              AND expiry IS NOT NULL AND expiry <= ?
            ORDER BY expiry""", (on_or_before,)).fetchall()


def has_cycle(conn, cycle_date: str) -> bool:
    return conn.execute("SELECT 1 FROM cycles WHERE cycle_date = ?",
                        (cycle_date,)).fetchone() is not None


def settled_rows(conn):
    return conn.execute(
        """SELECT * FROM cycles
            WHERE decision = 'ENTER' AND settlement_price IS NOT NULL
            ORDER BY cycle_date""").fetchall()


def counts(conn) -> dict:
    q = lambda sql: conn.execute(sql).fetchone()[0]  # noqa: E731
    return {
        "cycles": q("SELECT COUNT(*) FROM cycles"),
        "entered": q("SELECT COUNT(*) FROM cycles WHERE decision='ENTER'"),
        "skipped": q("SELECT COUNT(*) FROM cycles WHERE decision='SKIP'"),
        "settled": q("SELECT COUNT(*) FROM cycles WHERE settlement_price IS NOT NULL"),
    }
