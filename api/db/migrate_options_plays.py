"""
Migration: Create options_plays table for P&L tracking.
Tracks every generated play (RC >= 70) and closes them at expiry.
"""
import sqlite3
import os

DB_PATH = os.environ.get("CYBERSCREENER_DB", "/app/data/cyberscreener.db")


def run_migration():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS options_plays (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker          TEXT    NOT NULL,
                generated_at    TEXT    NOT NULL,
                horizon         TEXT,
                strategy        TEXT,
                strike          REAL,
                expiry          TEXT,
                dte             INTEGER,
                entry_price     REAL,
                entry_iv_rank   REAL,
                lt_score        REAL,
                opt_score       REAL,
                rc_score        INTEGER,
                direction       TEXT    DEFAULT 'bullish',
                outcome_price   REAL,
                outcome_date    TEXT,
                pnl_pct         REAL,
                status          TEXT    DEFAULT 'open',
                notes           TEXT
            )
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plays_ticker ON options_plays(ticker)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plays_status ON options_plays(status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_plays_expiry ON options_plays(expiry)")
        conn.commit()
        print("✅ options_plays table ready")
    except Exception as e:
        print(f"⚠️  options_plays migration error: {e}")
    finally:
        conn.close()


if __name__ == "__main__":
    run_migration()
