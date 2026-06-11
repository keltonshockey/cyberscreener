"""
Migration: settlement_v2 closure columns on options_plays.

Adds the pre-registered outcome fields (api/core/FORWARD_TEST_SEMANTICS.md):
closed_at, settlement_price/date, realized_pnl, realized_return, outcome,
win, close_method, entry_conviction. Idempotent — safe to re-run.

Also adds score_version (SESSION-BASELINE-WEIGHTS): the scoring-regime cohort
tag stamped on each journal row at log time (e.g. 'v2-baseline'). Gate reads
are per-cohort; legacy rows stay NULL and report separately — historical
conviction values are never rewritten.
"""
import sqlite3
import os

DB_PATH = os.environ.get("CYBERSCREENER_DB", "/app/data/cyberscreener.db")

COLUMNS = [
    ("closed_at", "TEXT"),
    ("settlement_price", "REAL"),
    ("settlement_date", "TEXT"),
    ("realized_pnl", "REAL"),
    ("realized_return", "REAL"),
    ("outcome", "TEXT"),
    ("win", "INTEGER"),
    ("close_method", "TEXT"),
    ("entry_conviction", "REAL"),
    ("score_version", "TEXT"),
]


def run_migration(conn=None):
    own = conn is None
    if own:
        conn = sqlite3.connect(DB_PATH)
    existing = {row[1] for row in conn.execute("PRAGMA table_info(options_plays)")}
    added = []
    for name, coltype in COLUMNS:
        if name not in existing:
            conn.execute(f"ALTER TABLE options_plays ADD COLUMN {name} {coltype}")
            added.append(name)
    conn.commit()
    if own:
        conn.close()
    return added


if __name__ == "__main__":
    added = run_migration()
    print(f"Added columns: {added}" if added else "No changes — already migrated.")
