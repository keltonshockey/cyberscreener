"""
migrate_threat.py — Adds threat_score and outage_status columns to scores table.
Safe to run multiple times (checks before altering).
"""

from db.models import get_db


def run_migration():
    conn = get_db()
    existing = {r[1] for r in conn.execute("PRAGMA table_info(scores)").fetchall()}
    added = []
    if "threat_score" not in existing:
        conn.execute("ALTER TABLE scores ADD COLUMN threat_score REAL DEFAULT 100")
        added.append("threat_score")
    if "outage_status" not in existing:
        conn.execute("ALTER TABLE scores ADD COLUMN outage_status TEXT DEFAULT 'none'")
        added.append("outage_status")
    if "breach_victim" not in existing:
        conn.execute("ALTER TABLE scores ADD COLUMN breach_victim INTEGER DEFAULT 0")
        added.append("breach_victim")
    if "demand_signal" not in existing:
        conn.execute("ALTER TABLE scores ADD COLUMN demand_signal INTEGER DEFAULT 0")
        added.append("demand_signal")
    conn.commit()
    conn.close()
    if added:
        print(f"✅ Threat migration: added columns {added}")
    else:
        print("✅ Threat migration: columns already exist")


if __name__ == "__main__":
    run_migration()
