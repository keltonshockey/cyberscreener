import sqlite3
import os

DB_PATH = os.environ.get("DB_PATH", "/app/data/cyberscreener.db")

NEW_COLUMNS = [
    ("sector",          "TEXT DEFAULT 'cyber'"),
    ("subsector",       "TEXT"),
    ("scoring_profile", "TEXT DEFAULT 'saas'"),
]

EARNINGS_TABLE = """
CREATE TABLE IF NOT EXISTS earnings_dates (
    ticker TEXT PRIMARY KEY,
    earnings_date TEXT NOT NULL,
    report_time TEXT DEFAULT 'unknown',
    source TEXT DEFAULT 'manual',
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""

def run_migration():
    conn = sqlite3.connect(DB_PATH)
    added = 0
    for col, col_type in NEW_COLUMNS:
        try:
            conn.execute(f"ALTER TABLE scores ADD COLUMN {col} {col_type}")
            added += 1
            print(f"  + added column: scores.{col}")
        except Exception as e:
            if "duplicate column" in str(e).lower():
                pass
            else:
                print(f"  ! error adding {col}: {e}")
    try:
        conn.execute(EARNINGS_TABLE)
        print("  + earnings_dates table ensured")
    except Exception as e:
        print(f"  ! earnings_dates error: {e}")
    conn.commit()
    conn.close()
    print(f"Migration complete. {added} new columns added.")

if __name__ == "__main__":
    run_migration()
