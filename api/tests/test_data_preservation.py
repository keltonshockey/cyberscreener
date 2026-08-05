"""
Schema-preservation tripwire — REBUILD_PLAN section 0, enforcement #3.

Kelton's stated worst outcome is accidental deletion of collected signals and
learnings. This module is the mechanical version of that constraint: it fails the
suite if any table or column that exists today ever disappears, and if new
deletion logic appears anywhere outside the modules that legitimately delete.

Three guards:

1. INVENTORY — build a fresh DB through the repo's own bootstrap sequence and
   assert the FULL current table/column inventory by exact name. The inventory is
   hardcoded on purpose: it IS the contract. A migration that drops or renames a
   column fails here, by name of the column.
2. STATIC DESTRUCTIVE-STATEMENT GUARD — walk the source tree and assert that
   DROP TABLE / DROP COLUMN / DELETE FROM appear only in the whitelisted files
   that legitimately contain them today, at exactly the pinned count per file.
   New deletion logic anywhere else = red suite.
3. READ-ONLY DOOR — prove db.db.ro.connect_ro really cannot write, so later
   sessions have a trustworthy import instead of rolling their own connection.

Updating the inventory is allowed ONLY for additive changes (new table, new
column). If a change to this file removes a name, that is the tripwire firing —
stop and escalate, do not "fix" the test.
"""
import importlib
import os
import re
import sqlite3
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]


# ─────────────────────────────────────────────────────────────────────────────
# The contract: full table/column inventory as of 2026-08-04 (branch
# feat/r1-schema-guard off main @ 130ad89). Captured by introspecting a DB built
# through the production bootstrap sequence — NOT hand-transcribed from the DDL,
# because several columns arrive via ALTER TABLE migrations rather than CREATE.
# Column order is the sqlite PRAGMA table_info order (creation order).
# ─────────────────────────────────────────────────────────────────────────────
EXPECTED_SCHEMA = {
    "scans": [
        "id", "timestamp", "tickers_scanned", "duration_seconds", "config_json",
        "intel_layers",
    ],
    "scores": [
        "id", "scan_id", "ticker", "price", "market_cap_b",
        # composite
        "lt_score", "opt_score",
        # LT components
        "lt_rule_of_40", "lt_valuation", "lt_fcf_margin", "lt_trend",
        "lt_earnings_quality", "lt_discount_momentum",
        # Opt components
        "opt_earnings_catalyst", "opt_iv_context", "opt_directional",
        "opt_technical", "opt_liquidity", "opt_asymmetry",
        # raw fundamentals
        "revenue_growth_pct", "gross_margin_pct", "operating_margin_pct",
        "ps_ratio", "pe_ratio", "ev_revenue", "fcf_m", "fcf_margin_pct",
        "revenue_b",
        # raw technicals
        "rsi", "sma_20", "sma_50", "sma_200", "bb_width", "vol_ratio",
        "iv_30d", "iv_rank", "beta", "short_pct",
        # performance
        "perf_1y", "perf_3m", "perf_1m", "pct_from_52w_high", "days_to_earnings",
        # intel layers
        "sec_score", "sentiment_score", "sentiment_bull_pct", "whale_score",
        "pc_ratio", "insider_buys_30d", "insider_sells_30d",
        # breakdown JSON
        "lt_breakdown", "opt_breakdown",
        # timing intelligence
        "horizon", "horizon_reason", "horizon_confidence", "recommended_expiry",
        "recommended_dte", "timing_signals", "timing_debug",
        # added by migrations (short_delta, sectors, threat)
        "short_delta", "rc_score", "sector", "subsector", "scoring_profile",
        "threat_score", "outage_status", "breach_victim", "demand_signal",
        "iv_suspect", "sector_tags",
    ],
    "prices": ["id", "ticker", "date", "close_price"],
    "signals": [
        "id", "scan_id", "ticker", "signal_type", "signal_text", "impact",
        # section 6b relevance metadata
        "stack", "polarity", "sector_context", "dedupe_key", "timestamp",
    ],
    "score_weights": [
        "id", "timestamp", "score_type", "weights_json", "backtest_correlation",
        "backtest_quintile_spread", "data_points", "notes",
    ],
    "earnings_dates": [
        "ticker", "earnings_date", "report_time", "source", "updated_at",
    ],
    "watchlist": ["id", "ticker", "notes", "sector", "added_at"],
    "options_plays": [
        "id", "ticker", "generated_at", "horizon", "strategy", "strike",
        "expiry", "dte", "entry_price", "entry_iv_rank", "lt_score", "opt_score",
        "rc_score", "direction", "outcome_price", "outcome_date", "pnl_pct",
        "status", "notes", "max_loss", "risk_reward_ratio",
        # forward-test closure migration
        "closed_at", "settlement_price", "settlement_date", "realized_pnl",
        "realized_return", "outcome", "win", "close_method", "entry_conviction",
        "score_version",
    ],
    "users": [
        "id", "email", "email_verified", "password_hash", "augur_name",
        "created_at", "last_login", "is_admin",
    ],
    "augur_profiles": [
        "id", "user_id", "prudentia", "audacia", "sapientia", "fortuna",
        "prospectus", "liquiditas", "avatar_seed", "title", "xp", "level",
        "last_respec", "created_at", "updated_at", "last_daily_xp",
        "buildings_entered",
    ],
    "refresh_tokens": ["id", "user_id", "token_hash", "expires_at", "created_at"],
    "augur_presence": [
        "user_id", "augur_name", "level", "rank_idx", "tile_x", "tile_y",
        "stance_type", "stance_data", "last_heartbeat", "is_active",
    ],
}

# Pinned counts, asserted independently so a careless edit to the lists above
# (a deleted line that still leaves valid Python) is caught as a count change.
EXPECTED_TABLE_COUNT = 12
EXPECTED_SCORES_COLUMNS = 70
EXPECTED_OPTIONS_PLAYS_COLUMNS = 31


# ─────────────────────────────────────────────────────────────────────────────
# Fixture: a fresh DB built the way production builds one.
#
# init_db() alone yields only 7 tables; the remaining 5 (earnings_dates, users,
# augur_profiles, refresh_tokens, augur_presence) and 11 of the scores columns
# arrive via the migration modules that main.py runs at import. Replicating that
# whole sequence is the point — the contract covers the schema a real deploy has.
# ─────────────────────────────────────────────────────────────────────────────
MIGRATION_MODULES = [
    "db.migrate_timing",
    "db.migrate_sectors",
    "db.migrate_threat",
    "db.migrate_watchlist",
    "db.migrate_options_plays",
    "db.migrate_short_delta",
    "db.migrate_augur",
    "db.migrate_presence",
]


@pytest.fixture
def fresh_db(tmp_path, monkeypatch):
    """Path to a fully-bootstrapped fresh DB (init_db + every main.py migration)."""
    db_path = tmp_path / "preservation.db"
    # Migration modules read their own DB_PATH at import; models.py reads
    # CYBERSCREENER_DB. Set both, then reload so the constants re-resolve.
    monkeypatch.setenv("CYBERSCREENER_DB", str(db_path))
    monkeypatch.setenv("DB_PATH", str(db_path))

    import db.models as models
    importlib.reload(models)
    models.init_db()

    for mod_name in MIGRATION_MODULES:
        mod = importlib.import_module(mod_name)
        importlib.reload(mod)
        mod.run_migration()

    return db_path


def _inventory(db_path):
    conn = sqlite3.connect(str(db_path))
    try:
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND name NOT LIKE 'sqlite_%' ORDER BY name"
            )
        ]
        return {
            t: [r[1] for r in conn.execute(f"PRAGMA table_info({t})")]
            for t in tables
        }
    finally:
        conn.close()


# ── Guard 1: inventory ───────────────────────────────────────────────────────

def test_every_expected_table_exists(fresh_db):
    """No table may disappear. Extra (new) tables are allowed — additive only."""
    actual = set(_inventory(fresh_db))
    missing = sorted(set(EXPECTED_SCHEMA) - actual)
    assert not missing, (
        f"SCHEMA REGRESSION — table(s) vanished from the bootstrap: {missing}. "
        "Data-preservation contract broken; do not edit this test to pass."
    )


def test_table_count_pinned(fresh_db):
    assert len(_inventory(fresh_db)) == EXPECTED_TABLE_COUNT


@pytest.mark.parametrize("table", sorted(EXPECTED_SCHEMA))
def test_every_expected_column_exists(fresh_db, table):
    """No column may disappear or be renamed, in any table."""
    actual = _inventory(fresh_db).get(table, [])
    missing = [c for c in EXPECTED_SCHEMA[table] if c not in actual]
    assert not missing, (
        f"SCHEMA REGRESSION — {table} lost column(s): {missing}. "
        f"Present: {actual}. Data-preservation contract broken."
    )


def test_scores_column_count_pinned(fresh_db):
    """69 in the R1 brief; reality at 130ad89 is 70 (sector_tags was the delta)."""
    cols = _inventory(fresh_db)["scores"]
    assert len(cols) == EXPECTED_SCORES_COLUMNS
    assert len(EXPECTED_SCHEMA["scores"]) == EXPECTED_SCORES_COLUMNS


def test_options_plays_columns_through_score_version(fresh_db):
    cols = _inventory(fresh_db)["options_plays"]
    assert len(cols) == EXPECTED_OPTIONS_PLAYS_COLUMNS
    assert cols[-1] == "score_version", (
        "options_plays must still carry the forward-test closure columns "
        f"through score_version; got tail {cols[-3:]}"
    )


def test_inventory_column_order_matches_contract(fresh_db):
    """Exact order too — catches a drop-and-recreate that preserves names only."""
    actual = _inventory(fresh_db)
    for table, expected_cols in EXPECTED_SCHEMA.items():
        assert actual[table] == expected_cols, (
            f"{table} column list drifted from the pinned contract.\n"
            f"expected: {expected_cols}\nactual:   {actual[table]}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Guard 2: static destructive-statement guard.
#
# Scope is api/ (the brief's wording) PLUS scripts/, because the "DB-prune
# module" the brief names as a whitelist entry actually lives at
# scripts/db_prune.py — leaving scripts/ unscanned would leave the single
# largest deletion surface in the repo unguarded.
#
# Counts are pinned per file so that ADDING deletion logic to an
# already-whitelisted file also fails, not just adding it to a new file.
# ─────────────────────────────────────────────────────────────────────────────
SCAN_DIRS = ["api", "scripts"]

DESTRUCTIVE_RE = re.compile(r"\b(DROP\s+TABLE|DROP\s+COLUMN|DELETE\s+FROM)\b", re.IGNORECASE)

DESTRUCTIVE_WHITELIST = {
    # The 30-min scheduler's inline prune: ages out old score/signal rows.
    "api/scheduler.py": 3,
    # User-facing CRUD: watchlist removal + refresh-token revocation. Touches no
    # collected market data.
    "api/db/models.py": 3,
    # Narrative view_queue dedup — operates on the regenerable narratives.db,
    # never on cyberscreener.db.
    "api/jobs/narrative_pipeline.py": 1,
    # The standalone prune job (scripts/DB_PRUNE_RUNBOOK.md).
    "scripts/db_prune.py": 2,
}


# Third-party code vendored into the tree is not ours to police. A virtualenv at
# api/venv (the layout the Makefile names FIRST) puts pandas, peewee and friends
# under a SCAN_DIR, and they legitimately contain DROP TABLE / DELETE FROM — so
# the guard would fail on vendored source instead of on our own.
#
# R1 did not hit this only because its api/venv was a symlink and Path.rglob does
# not descend into symlinked directories; a real `python3.11 -m venv api/venv`
# turns the guard red. Excluding these restores the guard's intended scope
# (first-party api/ + scripts/) and narrows nothing about our own code.
VENDOR_MARKERS = ("site-packages", "dist-packages", "/venv/", "/.venv/", "node_modules")


def _iter_sources():
    for d in SCAN_DIRS:
        for path in sorted((REPO_ROOT / d).rglob("*.py")):
            rel = path.relative_to(REPO_ROOT).as_posix()
            if "/tests/" in f"/{rel}" or "__pycache__" in rel:
                continue
            if any(m in f"/{rel}" for m in VENDOR_MARKERS):
                continue
            yield rel, path


def _destructive_hits(path):
    """Count destructive statements, ignoring whole-line comments."""
    hits = []
    for lineno, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
        if line.lstrip().startswith("#"):
            continue
        if DESTRUCTIVE_RE.search(line):
            hits.append((lineno, line.strip()))
    return hits


def test_no_new_destructive_statements():
    """New DROP/DELETE logic outside the whitelist fails the suite."""
    offenders = {
        rel: _destructive_hits(path)
        for rel, path in _iter_sources()
        if _destructive_hits(path) and rel not in DESTRUCTIVE_WHITELIST
    }
    assert not offenders, (
        "NEW destructive SQL outside the whitelist — REBUILD_PLAN section 0 "
        f"forbids new deletion logic:\n{offenders}\n"
        "If this is genuinely required, it needs a plan-level decision, not a "
        "test edit."
    )


@pytest.mark.parametrize("rel,expected", sorted(DESTRUCTIVE_WHITELIST.items()))
def test_whitelisted_destructive_counts_pinned(rel, expected):
    """Whitelisted files may not GROW new deletion statements either."""
    path = REPO_ROOT / rel
    assert path.exists(), f"whitelisted file vanished: {rel}"
    hits = _destructive_hits(path)
    assert len(hits) == expected, (
        f"{rel} destructive-statement count changed: expected {expected}, "
        f"found {len(hits)} -> {hits}"
    )


def test_no_drop_table_or_column_anywhere():
    """Nothing in the tree may DROP a table or column, whitelisted or not."""
    drop_re = re.compile(r"\b(DROP\s+TABLE|DROP\s+COLUMN)\b", re.IGNORECASE)
    offenders = {}
    for rel, path in _iter_sources():
        bad = [
            (n, l.strip())
            for n, l in enumerate(path.read_text(errors="replace").splitlines(), 1)
            if not l.lstrip().startswith("#") and drop_re.search(l)
        ]
        if bad:
            offenders[rel] = bad
    assert not offenders, f"DROP TABLE/COLUMN found: {offenders}"


# ─────────────────────────────────────────────────────────────────────────────
# Guard 3: the read-only door.
# ─────────────────────────────────────────────────────────────────────────────

def test_connect_ro_reads(fresh_db):
    from db.ro import connect_ro
    conn = connect_ro(str(fresh_db))
    try:
        names = {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        assert "scores" in names
    finally:
        conn.close()


def test_connect_ro_rejects_insert(fresh_db):
    from db.ro import connect_ro
    conn = connect_ro(str(fresh_db))
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only|query_only"):
            conn.execute(
                "INSERT INTO watchlist (ticker, added_at) VALUES ('EVIL', '2026-08-04')")
            conn.commit()
    finally:
        conn.close()


@pytest.mark.parametrize("stmt", [
    "DELETE FROM scores",
    "UPDATE scores SET lt_score = 0",
    "DROP TABLE scores",
    "CREATE TABLE evil (id INTEGER)",
])
def test_connect_ro_rejects_every_write(fresh_db, stmt):
    from db.ro import connect_ro
    conn = connect_ro(str(fresh_db))
    try:
        with pytest.raises(sqlite3.OperationalError):
            conn.execute(stmt)
            conn.commit()
    finally:
        conn.close()


def test_connect_ro_does_not_create_missing_db(tmp_path):
    """mode=ro must never conjure an empty DB from a typo'd path."""
    from db.ro import connect_ro
    missing = tmp_path / "nope.db"
    with pytest.raises(sqlite3.OperationalError):
        connect_ro(str(missing))
    assert not missing.exists()


def test_research_dir_forbids_write_imports():
    """research/ may not import the write-path module (research/README.md rule 3)."""
    research = REPO_ROOT / "research"
    if not research.exists():
        pytest.skip("research/ not present")
    offenders = []
    for path in sorted(research.rglob("*.py")):
        text = path.read_text(errors="replace")
        if re.search(r"^\s*from\s+db\.models\s+import|^\s*import\s+db\.models",
                     text, re.MULTILINE):
            offenders.append(path.relative_to(REPO_ROOT).as_posix())
    assert not offenders, (
        f"research/ must read via db.ro.connect_ro, not db.models: {offenders}")
