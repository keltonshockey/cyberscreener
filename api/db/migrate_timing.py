"""
Migration: add timing intelligence columns to scores table.
Safe to run multiple times (ALTER TABLE IF NOT EXISTS not supported in SQLite,
so we catch the OperationalError when column already exists).
"""
import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "/data/db/cyberscreener.db")

NEW_COLUMNS = [
    ("horizon",             "TEXT"),
    ("horizon_reason",      "TEXT"),
    ("horizon_confidence",  "REAL"),
    ("recommended_expiry",  "TEXT"),
    ("recommended_dte",     "INTEGER"),
    ("timing_signals",      "TEXT"),   # JSON list
    ("timing_debug",        "TEXT"),   # JSON dict
]

def run_migration():
    conn = sqlite3.connect(DB_PATH)
    added = 0
    for col, col_type in NEW_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE scores ADD COLUMN {col} {col_type}")
            added += 1
            print(f"  + added column: {col}")
        except Exception as e:
            if "duplicate column" in str(e).lower():
                pass  # Already exists, fine
            else:
                print(f"  ! error adding {col}: {e}")
    conn.commit()
    conn.close()
    print(f"Migration complete. {added} new columns added.")

if __name__ == "__main__":
    run_migration()
