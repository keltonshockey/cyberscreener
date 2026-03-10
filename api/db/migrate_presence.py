"""
Migration: Add augur_presence table for social presence in the world.
One row per user, upserted on heartbeat. No unbounded growth.
Run once — idempotent (uses CREATE TABLE IF NOT EXISTS).
"""
import sqlite3
import os
import logging

logger = logging.getLogger(__name__)

DB_PATH = os.environ.get("DB_PATH", os.environ.get("CYBERSCREENER_DB", "/app/data/cyberscreener.db"))


def run_migration():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # ── Augur Presence table ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS augur_presence (
            user_id INTEGER PRIMARY KEY REFERENCES users(id),
            augur_name TEXT NOT NULL,
            level INTEGER DEFAULT 1,
            rank_idx INTEGER DEFAULT 0,
            tile_x INTEGER DEFAULT 40,
            tile_y INTEGER DEFAULT 25,
            stance_type TEXT,
            stance_data TEXT,
            last_heartbeat TEXT,
            is_active INTEGER DEFAULT 1
        )
    """)

    # ── Indexes ──
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_presence_active ON augur_presence(is_active)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_presence_heartbeat ON augur_presence(last_heartbeat)")

    conn.commit()
    conn.close()
    logger.info("✅ Presence migration complete (augur_presence table)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
