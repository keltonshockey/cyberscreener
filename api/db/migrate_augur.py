"""
Migration: Add multi-user auth + Augur character tables.
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

    # ── Users table ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE,
            email_verified INTEGER DEFAULT 0,
            password_hash TEXT NOT NULL,
            augur_name TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL,
            last_login TEXT
        )
    """)

    # ── Augur profiles (character attributes) ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS augur_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL UNIQUE REFERENCES users(id),
            prudentia INTEGER NOT NULL DEFAULT 6,
            audacia INTEGER NOT NULL DEFAULT 6,
            sapientia INTEGER NOT NULL DEFAULT 6,
            fortuna INTEGER NOT NULL DEFAULT 6,
            prospectus INTEGER NOT NULL DEFAULT 6,
            liquiditas INTEGER NOT NULL DEFAULT 6,
            avatar_seed TEXT,
            title TEXT DEFAULT 'Novice Augur',
            xp INTEGER DEFAULT 0,
            level INTEGER DEFAULT 1,
            last_respec TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT
        )
    """)

    # ── Refresh tokens for JWT auth ──
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS refresh_tokens (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id),
            token_hash TEXT NOT NULL UNIQUE,
            expires_at TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
    """)

    # ── Indexes ──
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_email ON users(email)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_users_augur_name ON users(augur_name)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_augur_user ON augur_profiles(user_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_refresh_token ON refresh_tokens(token_hash)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_refresh_user ON refresh_tokens(user_id)")

    # ── Add is_admin column (idempotent) ──
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN is_admin INTEGER DEFAULT 0")
        logger.info("Added is_admin column to users")
    except sqlite3.OperationalError:
        pass  # Column already exists

    # ── Add XP tracking columns (idempotent) ──
    try:
        cursor.execute("ALTER TABLE augur_profiles ADD COLUMN last_daily_xp TEXT")
        logger.info("Added last_daily_xp column to augur_profiles")
    except sqlite3.OperationalError:
        pass  # Column already exists

    try:
        cursor.execute("ALTER TABLE augur_profiles ADD COLUMN buildings_entered TEXT DEFAULT '{}'")
        logger.info("Added buildings_entered column to augur_profiles")
    except sqlite3.OperationalError:
        pass  # Column already exists

    conn.commit()
    conn.close()
    logger.info("✅ Augur migration complete (users, augur_profiles, refresh_tokens)")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    run_migration()
