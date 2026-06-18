"""
Narrative store — a SEPARATE SQLite database (`narratives.db`) that holds the
per-ticker LT/ST story panel and a lazy view queue.

Hard isolation guarantees (see NARRATIVE_LAYER_PLAN.md):
  * This file owns its own connection helper and DB path. It NEVER touches
    `cyberscreener.db` or `db.models`. Nothing here can move a score, a weight,
    or a journal row.
  * `narratives.db` is regenerable: it is safe to delete at any time. The
    pipeline (mill-side, separate session) repopulates it.
  * The only writes the droplet performs against this store are the lazy
    `record_view` inserts (so the pipeline learns what is being looked at) and
    the `upsert_narrative` used by the sync/pipeline. Reads are everything else.

Schema:
  narratives(ticker PRIMARY KEY, lt_story, st_story, sources(json),
             signal_snapshot(json), snapshot_hash, confidence, model,
             lt_generated_at, st_generated_at)
  view_queue(ticker PRIMARY KEY, last_viewed_at, requested DEFAULT 1)
"""

import os
import json
import sqlite3
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

# ── Narrative config block ──────────────────────────────────────────────────
# Module-level, env-overridable constants (the project's config-loader idiom —
# see DB_PATH in db/models.py and the JWT/password constants in deps.py). No
# secrets live here.
#
# ONE env var controls where narratives.db lives, end to end:
#
#     CYBERSCREENER_NARRATIVES_DB    absolute path to narratives.db
#
# It is the single knob the mill generator, the mill->droplet push wrapper
# (scripts/mill/push_narratives.sh), and the droplet router all read, so all
# three resolve the SAME file. When it is unset we default to CANONICAL_
# NARRATIVES_DB below — which is exactly the destination the sync wrapper
# (bin/narrative-rsync-only.sh) hard-pins. That makes a fresh `git pull` +
# restart serve the delivered file with NO systemd drop-in. narratives.db is a
# DISTINCT file from the prod DB so the two never share a connection or backup.

# Canonical droplet location for narratives.db. Must match DEST_DIR in
# bin/narrative-rsync-only.sh (the rsync forced-command destination) — the
# store's default and the sync target are deliberately one constant.
CANONICAL_NARRATIVES_DB = "/opt/cyberscreener/data/narratives/narratives.db"


def _default_narratives_path() -> str:
    """Default narratives.db path when CYBERSCREENER_NARRATIVES_DB is unset.

    Returns the canonical droplet location (the sync wrapper's pinned
    destination), NOT a path derived from the prod DB_PATH — so prod serves the
    delivered file directly, with no systemd drop-in to bridge a mismatch."""
    return CANONICAL_NARRATIVES_DB

# Freshness TTLs the router uses to compute the `stale` flag.
ST_TTL_HOURS = int(os.environ.get("NARRATIVE_ST_TTL_HOURS", "24"))   # short-term story
LT_TTL_DAYS = int(os.environ.get("NARRATIVE_LT_TTL_DAYS", "7"))      # long-term story

# Reference value; helpers re-read the env each call so tests can repoint the DB.
NARRATIVES_DB_PATH = os.environ.get("CYBERSCREENER_NARRATIVES_DB") or _default_narratives_path()


def _db_path() -> str:
    """Resolve the narratives DB path dynamically so tests can override via env."""
    return os.environ.get("CYBERSCREENER_NARRATIVES_DB") or _default_narratives_path()


def get_narratives_db() -> sqlite3.Connection:
    """A connection to `narratives.db` ONLY. Mirrors the prod helper's PRAGMAs
    (WAL + conservative memory) but against a wholly separate file."""
    path = _db_path()
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA cache_size=-8192")   # 8MB; the store is tiny
    conn.execute("PRAGMA mmap_size=0")        # keep RSS flat on the 1GB droplet
    conn.execute("PRAGMA temp_store=MEMORY")
    return conn


def init_narratives_db() -> None:
    """Create the narratives + view_queue tables if absent. Idempotent."""
    conn = get_narratives_db()
    try:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS narratives (
                ticker          TEXT PRIMARY KEY,
                lt_story        TEXT,
                st_story        TEXT,
                sources         TEXT,   -- JSON: [{"title","url"}, ...]
                signal_snapshot TEXT,   -- JSON: the signal dict the story explains
                snapshot_hash   TEXT,   -- hash of signal_snapshot for drift detection
                confidence      TEXT,   -- "ok" | "low" | ...
                model           TEXT,   -- generator id (e.g. "gemma3")
                lt_generated_at TEXT,   -- ISO timestamp
                st_generated_at TEXT    -- ISO timestamp
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS view_queue (
                ticker         TEXT PRIMARY KEY,
                last_viewed_at TEXT,
                requested      INTEGER DEFAULT 1
            )
        """)
        conn.commit()
    finally:
        conn.close()


def _loads(blob, default):
    if not blob:
        return default
    try:
        return json.loads(blob)
    except (ValueError, TypeError):
        return default


def get_narrative(ticker: str) -> dict | None:
    """Return the stored narrative row for `ticker` (JSON columns parsed), or
    None if no row exists. Read-only."""
    t = (ticker or "").upper()
    conn = get_narratives_db()
    try:
        row = conn.execute(
            "SELECT * FROM narratives WHERE ticker = ?", (t,)
        ).fetchone()
    finally:
        conn.close()
    if not row:
        return None
    d = dict(row)
    d["sources"] = _loads(d.get("sources"), [])
    d["signal_snapshot"] = _loads(d.get("signal_snapshot"), {})
    return d


def record_view(ticker: str) -> None:
    """Lazy trigger: stamp this ticker as viewed so the pipeline knows to
    generate/refresh it. Upsert into view_queue ONLY — never the prod DB."""
    t = (ticker or "").upper()
    if not t:
        return
    now = datetime.utcnow().isoformat(timespec="seconds")
    conn = get_narratives_db()
    try:
        conn.execute("""
            INSERT INTO view_queue (ticker, last_viewed_at, requested)
            VALUES (?, ?, 1)
            ON CONFLICT(ticker) DO UPDATE SET
                last_viewed_at = excluded.last_viewed_at,
                requested = 1
        """, (t, now))
        conn.commit()
    finally:
        conn.close()


def upsert_narrative(
    ticker: str,
    lt_story: str | None = None,
    st_story: str | None = None,
    sources=None,
    signal_snapshot=None,
    snapshot_hash: str | None = None,
    confidence: str = "ok",
    model: str | None = None,
    lt_generated_at: str | None = None,
    st_generated_at: str | None = None,
) -> None:
    """Write/replace a narrative row. Used by the mill-side pipeline/sync (defined
    here so the store owns its own write path). `sources`/`signal_snapshot` may be
    passed as Python objects (JSON-encoded here) or pre-encoded strings."""
    t = (ticker or "").upper()
    if not t:
        raise ValueError("upsert_narrative requires a ticker")

    def _enc(v):
        if v is None or isinstance(v, str):
            return v
        return json.dumps(v)

    conn = get_narratives_db()
    try:
        conn.execute("""
            INSERT INTO narratives (
                ticker, lt_story, st_story, sources, signal_snapshot,
                snapshot_hash, confidence, model, lt_generated_at, st_generated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(ticker) DO UPDATE SET
                lt_story = excluded.lt_story,
                st_story = excluded.st_story,
                sources = excluded.sources,
                signal_snapshot = excluded.signal_snapshot,
                snapshot_hash = excluded.snapshot_hash,
                confidence = excluded.confidence,
                model = excluded.model,
                lt_generated_at = excluded.lt_generated_at,
                st_generated_at = excluded.st_generated_at
        """, (
            t, lt_story, st_story, _enc(sources), _enc(signal_snapshot),
            snapshot_hash, confidence, model, lt_generated_at, st_generated_at,
        ))
        conn.commit()
    finally:
        conn.close()
