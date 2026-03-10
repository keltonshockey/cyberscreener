"""
Migration: Add short_delta column to scores table.
short_delta = change in short_pct over last 60 days (negative = covering = squeeze setup).
"""
import sqlite3
import os

DB_PATH = os.environ.get("CYBERSCREENER_DB", "/app/data/cyberscreener.db")


def run_migration():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("ALTER TABLE scores ADD COLUMN short_delta REAL DEFAULT NULL")
        conn.commit()
        print("✅ short_delta column added to scores")
    except Exception as e:
        if "duplicate column" in str(e).lower():
            print("ℹ️  short_delta column already exists")
        else:
            print(f"⚠️  short_delta migration error: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    run_migration()
