"""
migrate_watchlist.py — Creates the watchlist table for custom ticker tracking.
Safe to run multiple times (checks before altering).
"""

from db.models import get_db


def run_migration():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS watchlist (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT    NOT NULL UNIQUE,
            notes       TEXT    DEFAULT '',
            sector      TEXT    DEFAULT 'unknown',
            added_at    TEXT    NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_watchlist_ticker ON watchlist(ticker);
    """)
    conn.commit()
    conn.close()
    print("✅ Watchlist migration: table ready")


if __name__ == "__main__":
    run_migration()
