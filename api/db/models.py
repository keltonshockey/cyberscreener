"""
Database models — SQLite schema + data access layer.
Tables: scans, scores, prices, signals, score_weights (NEW: for self-calibration)
"""

import sqlite3
import os
import json
import hashlib
import secrets
from datetime import datetime, timedelta

DB_PATH = os.environ.get("CYBERSCREENER_DB", "/app/data/cyberscreener.db")

def get_db():
    """Get a database connection with row factory."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    return conn


def _migrate_scores_table(conn):
    """Add v2 columns to existing scores table if they don't exist."""
    # Get existing columns
    try:
        cursor = conn.execute("PRAGMA table_info(scores)")
        existing_cols = {row[1] for row in cursor.fetchall()}
    except Exception:
        return  # Table doesn't exist yet, CREATE TABLE will handle it

    if not existing_cols:
        return

    # New v2 columns to add
    new_columns = [
        ("lt_rule_of_40", "REAL"),
        ("lt_valuation", "REAL"),
        ("lt_fcf_margin", "REAL"),
        ("lt_trend", "REAL"),
        ("lt_earnings_quality", "REAL"),
        ("lt_discount_momentum", "REAL"),
        ("opt_earnings_catalyst", "REAL"),
        ("opt_iv_context", "REAL"),
        ("opt_directional", "REAL"),
        ("opt_technical", "REAL"),
        ("opt_liquidity", "REAL"),
        ("opt_asymmetry", "REAL"),
        ("operating_margin_pct", "REAL"),
        ("ev_revenue", "REAL"),
        ("fcf_margin_pct", "REAL"),
        ("revenue_b", "REAL"),
        ("iv_rank", "REAL"),
        ("perf_1m", "REAL"),
        ("lt_breakdown", "TEXT"),
        ("opt_breakdown", "TEXT"),
        ("short_delta", "REAL"),  # P5: change in short interest over 60d
    ]

    for col_name, col_type in new_columns:
        if col_name not in existing_cols:
            try:
                conn.execute(f"ALTER TABLE scores ADD COLUMN {col_name} {col_type}")
            except Exception:
                pass  # Column might already exist from a partial migration

    conn.commit()


def init_db():
    """Initialize all tables + migrate schema if needed."""
    conn = get_db()

    # ── Schema migration: add new v2 columns to existing scores table ──
    _migrate_scores_table(conn)

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            tickers_scanned INTEGER DEFAULT 0,
            duration_seconds REAL,
            config_json TEXT,
            intel_layers TEXT DEFAULT 'base'
        );

        CREATE TABLE IF NOT EXISTS scores (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER NOT NULL,
            ticker TEXT NOT NULL,
            price REAL,
            market_cap_b REAL,

            -- Composite scores
            lt_score REAL DEFAULT 0,
            opt_score REAL DEFAULT 0,

            -- LT score components (v2)
            lt_rule_of_40 REAL,
            lt_valuation REAL,
            lt_fcf_margin REAL,
            lt_trend REAL,
            lt_earnings_quality REAL,
            lt_discount_momentum REAL,

            -- Opt score components (v2)
            opt_earnings_catalyst REAL,
            opt_iv_context REAL,
            opt_directional REAL,
            opt_technical REAL,
            opt_liquidity REAL,
            opt_asymmetry REAL,

            -- Raw fundamentals
            revenue_growth_pct REAL,
            gross_margin_pct REAL,
            operating_margin_pct REAL,
            ps_ratio REAL,
            pe_ratio REAL,
            ev_revenue REAL,
            fcf_m REAL,
            fcf_margin_pct REAL,
            revenue_b REAL,

            -- Raw technicals
            rsi REAL,
            sma_20 REAL,
            sma_50 REAL,
            sma_200 REAL,
            bb_width REAL,
            vol_ratio REAL,
            iv_30d REAL,
            iv_rank REAL,
            beta REAL,
            short_pct REAL,

            -- Performance
            perf_1y REAL,
            perf_3m REAL,
            perf_1m REAL,
            pct_from_52w_high REAL,
            days_to_earnings INTEGER,

            -- Intelligence layer scores
            sec_score REAL DEFAULT 0,
            sentiment_score REAL DEFAULT 0,
            sentiment_bull_pct REAL,
            whale_score REAL DEFAULT 0,
            pc_ratio REAL,
            insider_buys_30d INTEGER DEFAULT 0,
            insider_sells_30d INTEGER DEFAULT 0,

            -- LT score component breakdown (JSON for dashboard)
            lt_breakdown TEXT,
            opt_breakdown TEXT,

            -- Timing intelligence
            horizon TEXT,
            horizon_reason TEXT,
            horizon_confidence REAL,
            recommended_expiry TEXT,
            recommended_dte INTEGER,
            timing_signals TEXT,
            timing_debug TEXT,

            FOREIGN KEY (scan_id) REFERENCES scans(id)
        );

        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker TEXT NOT NULL,
            date TEXT NOT NULL,
            close_price REAL NOT NULL,
            UNIQUE(ticker, date)
        );

        CREATE TABLE IF NOT EXISTS signals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id INTEGER,
            ticker TEXT NOT NULL,
            signal_type TEXT,
            signal_text TEXT,
            impact TEXT,
            timestamp TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        );

        -- NEW: Score weight history for self-calibration
        CREATE TABLE IF NOT EXISTS score_weights (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL,
            score_type TEXT NOT NULL,  -- 'lt' or 'opt'
            weights_json TEXT NOT NULL,  -- JSON dict of component -> weight
            backtest_correlation REAL,   -- overall score-return correlation
            backtest_quintile_spread REAL,  -- Q5 avg return - Q1 avg return
            data_points INTEGER,
            notes TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_scores_scan ON scores(scan_id);
        CREATE INDEX IF NOT EXISTS idx_scores_ticker ON scores(ticker);
        CREATE INDEX IF NOT EXISTS idx_scores_ticker_scan ON scores(ticker, scan_id DESC);
        CREATE INDEX IF NOT EXISTS idx_prices_ticker_date ON prices(ticker, date);
        CREATE INDEX IF NOT EXISTS idx_signals_scan ON signals(scan_id);
        CREATE INDEX IF NOT EXISTS idx_scans_timestamp ON scans(timestamp);

        -- Watchlist: custom tickers added by the user
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


def save_scan(results, intel_layers=None, duration_seconds=None, **kwargs):
    """Save a complete scan to the database. Returns scan_id."""
    conn = get_db()

    layers_str = ",".join(intel_layers) if intel_layers else "base"
    cursor = conn.execute(
        "INSERT INTO scans (timestamp, tickers_scanned, duration_seconds, intel_layers) VALUES (?, ?, ?, ?)",
        (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), len(results), duration_seconds, layers_str)
    )
    scan_id = cursor.lastrowid

    for r in results:
        # Save score record
        lt_breakdown = json.dumps(r.get("lt_breakdown", {}))
        opt_breakdown = json.dumps(r.get("opt_breakdown", {}))

        conn.execute("""
            INSERT INTO scores (
                scan_id, ticker, price, market_cap_b,
                lt_score, opt_score,
                lt_rule_of_40, lt_valuation, lt_fcf_margin, lt_trend, lt_earnings_quality, lt_discount_momentum,
                opt_earnings_catalyst, opt_iv_context, opt_directional, opt_technical, opt_liquidity, opt_asymmetry,
                revenue_growth_pct, gross_margin_pct, operating_margin_pct,
                ps_ratio, pe_ratio, ev_revenue, fcf_m, fcf_margin_pct, revenue_b,
                rsi, sma_20, sma_50, sma_200, bb_width, vol_ratio, iv_30d, iv_rank, beta, short_pct,
                perf_1y, perf_3m, perf_1m, pct_from_52w_high, days_to_earnings,
                sec_score, sentiment_score, sentiment_bull_pct, whale_score, pc_ratio,
                insider_buys_30d, insider_sells_30d,
                lt_breakdown, opt_breakdown,
                horizon, horizon_reason, horizon_confidence,
                recommended_expiry, recommended_dte,
                timing_signals, timing_debug,
                sector, subsector, scoring_profile,
                threat_score, outage_status, breach_victim, demand_signal,
                short_delta
            ) VALUES (
                ?,?,?,?,
                ?,?,
                ?,?,?,?,?,?,
                ?,?,?,?,?,?,
                ?,?,?,
                ?,?,?,?,?,?,
                ?,?,?,?,?,?,?,?,?,?,
                ?,?,?,?,?,
                ?,?,?,?,?,
                ?,?,
                ?,?,
                ?,?,?,
                ?,?,
                ?,?,
                ?,?,?,
                ?,?,?,?,
                ?
            )
        """, (
            scan_id, r["ticker"], r.get("price"), r.get("market_cap_b"),
            r.get("lt_score", 0), r.get("opt_score", 0),
            r.get("lt_rule_of_40"), r.get("lt_valuation"), r.get("lt_fcf_margin"),
            r.get("lt_trend"), r.get("lt_earnings_quality"), r.get("lt_discount_momentum"),
            r.get("opt_earnings_catalyst"), r.get("opt_iv_context"), r.get("opt_directional"),
            r.get("opt_technical"), r.get("opt_liquidity"), r.get("opt_asymmetry"),
            r.get("revenue_growth_pct"), r.get("gross_margin_pct"), r.get("operating_margin_pct"),
            r.get("ps_ratio"), r.get("pe_ratio"), r.get("ev_revenue"),
            r.get("fcf_m"), r.get("fcf_margin_pct"), r.get("revenue_b"),
            r.get("rsi"), r.get("sma_20"), r.get("sma_50"), r.get("sma_200"),
            r.get("bb_width"), r.get("vol_ratio"), r.get("iv_30d"), r.get("iv_rank"),
            r.get("beta"), r.get("short_pct"),
            r.get("perf_1y"), r.get("perf_3m"), r.get("perf_1m"),
            r.get("pct_from_52w_high"), r.get("days_to_earnings"),
            r.get("sec_score", 0), r.get("sentiment_score", 0), r.get("sentiment_bull_pct"),
            r.get("whale_score", 0), r.get("pc_ratio"),
            r.get("insider_buys_30d", 0), r.get("insider_sells_30d", 0),
            lt_breakdown, opt_breakdown,
            r.get("horizon"), r.get("horizon_reason"), r.get("horizon_confidence"),
            r.get("recommended_expiry"), r.get("recommended_dte"),
            json.dumps(r.get("timing_signals", [])),
            json.dumps(r.get("timing_debug", {})),
            r.get("sector", "cyber"), r.get("subsector", ""), r.get("scoring_profile", "saas"),
            r.get("threat_score", 100), r.get("outage_status", "none"),
            1 if r.get("breach_victim") else 0,
            1 if r.get("demand_signal") else 0,
            r.get("short_delta"),
        ))

        # Save price snapshot
        today_str = datetime.now().strftime("%Y-%m-%d")
        if r.get("price"):
            conn.execute(
                "INSERT OR IGNORE INTO prices (ticker, date, close_price) VALUES (?, ?, ?)",
                (r["ticker"], today_str, r["price"])
            )

        # Save signals
        for reason in r.get("lt_reasons", []) + r.get("opt_reasons", []):
            impact = "positive" if any(e in reason for e in ["🚀", "💎", "💰", "🎯", "🌋"]) else \
                     "negative" if any(e in reason for e in ["⚠️", "🔴", "💸"]) else "neutral"
            conn.execute(
                "INSERT INTO signals (scan_id, ticker, signal_type, signal_text, impact) VALUES (?, ?, ?, ?, ?)",
                (scan_id, r["ticker"], "score", reason, impact)
            )

    # Momentum detection — compare new scores to previous scan
    momentum_events = _detect_and_save_momentum(scan_id, results, conn)

    conn.commit()
    conn.close()
    return scan_id, momentum_events


def _detect_and_save_momentum(scan_id: int, results: list, conn) -> list:
    """
    Compare each ticker's new scores to its most recent previous scan scores.
    Write momentum signals (signal_type='momentum') and return a list of events
    for email notification.

    Returns: [{ticker, score_type, delta, old_score, new_score, text, impact}, ...]
    """
    events = []
    THRESHOLD = 8  # minimum point change to count as a momentum event

    for r in results:
        ticker = r.get("ticker")
        new_lt  = r.get("lt_score")
        new_opt = r.get("opt_score")
        if not ticker or new_lt is None or new_opt is None:
            continue

        # Fetch previous scan scores (the scan just before this one)
        prev = conn.execute("""
            SELECT lt_score, opt_score FROM scores
            WHERE ticker = ? AND scan_id < ?
            ORDER BY scan_id DESC LIMIT 1
        """, (ticker, scan_id)).fetchone()
        if not prev:
            continue

        prev_lt, prev_opt = prev["lt_score"], prev["opt_score"]
        if prev_lt is None or prev_opt is None:
            continue

        for score_type, new_val, prev_val in [
            ("lt", new_lt, prev_lt),
            ("opt", new_opt, prev_opt),
        ]:
            delta = round(new_val - prev_val, 1)
            if abs(delta) < THRESHOLD:
                continue

            direction = "📈" if delta > 0 else "📉"
            label = "LT" if score_type == "lt" else "Opt"
            sign  = "+" if delta > 0 else ""
            text  = f"{direction} {label} score {sign}{delta:.0f} ({prev_val:.0f}→{new_val:.0f})"
            impact = "positive" if delta > 0 else "negative"

            conn.execute(
                "INSERT INTO signals (scan_id, ticker, signal_type, signal_text, impact) VALUES (?, ?, ?, ?, ?)",
                (scan_id, ticker, "momentum", text, impact)
            )
            events.append({
                "ticker":     ticker,
                "score_type": score_type,
                "delta":      delta,
                "old_score":  prev_val,
                "new_score":  new_val,
                "text":       text,
                "impact":     impact,
            })

    return events


def get_score_history(ticker, days=90):
    """Get historical scores for a ticker."""
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT s.*, sc.timestamp as scan_date
        FROM scores s
        JOIN scans sc ON s.scan_id = sc.id
        WHERE s.ticker = ? AND sc.timestamp >= ?
        ORDER BY sc.timestamp ASC
    """, (ticker, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_scores_for_backtest(days=180):
    """Get all score records with timestamps for backtesting."""
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    # Filter by scan_id range — uses idx_scores_scan + idx_scans_timestamp,
    # avoids full-table join on 400K+ rows
    rows = conn.execute("""
        SELECT s.*, sc.timestamp as scan_date
        FROM scores s
        JOIN scans sc ON s.scan_id = sc.id
        WHERE s.scan_id >= (SELECT COALESCE(MIN(id), 0) FROM scans WHERE timestamp >= ?)
        ORDER BY s.scan_id ASC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_price(ticker, date_str):
    """Get a specific price snapshot. Returns float or None."""
    conn = get_db()
    row = conn.execute(
        "SELECT close_price FROM prices WHERE ticker = ? AND date = ?",
        (ticker, date_str)
    ).fetchone()
    conn.close()
    return row["close_price"] if row else None


def get_nearest_price(ticker, target_date_str, window_days=5):
    """Get the nearest price to a target date within a window."""
    conn = get_db()
    target = datetime.strptime(target_date_str, "%Y-%m-%d")
    start = (target - timedelta(days=window_days)).strftime("%Y-%m-%d")
    end = (target + timedelta(days=window_days)).strftime("%Y-%m-%d")

    row = conn.execute("""
        SELECT close_price, date,
               ABS(julianday(date) - julianday(?)) as day_diff
        FROM prices
        WHERE ticker = ? AND date BETWEEN ? AND ?
        ORDER BY day_diff ASC LIMIT 1
    """, (target_date_str, ticker, start, end)).fetchone()
    conn.close()
    return row["close_price"] if row else None


def save_score_weights(score_type, weights, correlation=None, quintile_spread=None, data_points=None, notes=None):
    """Save a weight configuration for self-calibration tracking."""
    conn = get_db()
    conn.execute("""
        INSERT INTO score_weights (timestamp, score_type, weights_json, backtest_correlation, backtest_quintile_spread, data_points, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        score_type,
        json.dumps(weights),
        correlation,
        quintile_spread,
        data_points,
        notes,
    ))
    conn.commit()
    conn.close()


def get_latest_weights(score_type):
    """Get the most recent weight configuration."""
    conn = get_db()
    row = conn.execute("""
        SELECT * FROM score_weights
        WHERE score_type = ?
        ORDER BY id DESC LIMIT 1
    """, (score_type,)).fetchone()
    conn.close()
    if row:
        result = dict(row)
        result["weights"] = json.loads(result["weights_json"])
        return result
    return None


def get_scan_count():
    """Get total number of scans."""
    conn = get_db()
    count = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    conn.close()
    return count


# ── Watchlist CRUD ────────────────────────────────────────────────────────────

def get_watchlist():
    """Return all watchlist items."""
    conn = get_db()
    rows = conn.execute("SELECT * FROM watchlist ORDER BY added_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_to_watchlist(ticker: str, notes: str = "", sector: str = "unknown"):
    """Add a ticker to the watchlist. Returns True if added, False if already exists."""
    conn = get_db()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO watchlist (ticker, notes, sector, added_at) VALUES (?, ?, ?, ?)",
            (ticker.upper(), notes, sector, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        changed = conn.execute("SELECT changes()").fetchone()[0]
        conn.commit()
        return changed > 0
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def remove_from_watchlist(ticker: str):
    """Remove a ticker from the watchlist."""
    conn = get_db()
    conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper(),))
    conn.commit()
    conn.close()


def get_watchlist_tickers() -> list:
    """Return just the ticker symbols from the watchlist."""
    conn = get_db()
    rows = conn.execute("SELECT ticker FROM watchlist").fetchall()
    conn.close()
    return [r["ticker"] for r in rows]


# ── Backward-compatible aliases for old code (scheduler.py, db/__init__.py) ──
get_price_on_date = get_nearest_price


# ─────────────────────────────────────────────────────────────────────────────
# P1: IV History — real 52-week IV range from stored scan data
# ─────────────────────────────────────────────────────────────────────────────

def get_iv_history(ticker: str, days: int = 365) -> list:
    """
    Return list of (scan_date, iv_30d) tuples for a ticker over the last N days.
    Used to compute real IV rank (actual 52-week IV min/max).
    """
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT sc.timestamp as scan_date, s.iv_30d
        FROM scores s
        JOIN scans sc ON s.scan_id = sc.id
        WHERE s.ticker = ? AND sc.timestamp >= ? AND s.iv_30d IS NOT NULL
        ORDER BY sc.timestamp ASC
    """, (ticker, cutoff)).fetchall()
    conn.close()
    return [(r["scan_date"], r["iv_30d"]) for r in rows]


# ─────────────────────────────────────────────────────────────────────────────
# P5: Short Interest Trend — delta over last 60 days
# ─────────────────────────────────────────────────────────────────────────────

def get_short_interest_trend(ticker: str, days: int = 60) -> dict:
    """
    Return short interest trend for a ticker over the last N days.
    Returns dict with: latest, oldest, delta, observation_count.
    delta < 0 means shorts are covering (squeeze setup), delta > 0 means building.
    """
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT sc.timestamp as scan_date, s.short_pct
        FROM scores s
        JOIN scans sc ON s.scan_id = sc.id
        WHERE s.ticker = ? AND sc.timestamp >= ? AND s.short_pct IS NOT NULL AND s.short_pct > 0
        ORDER BY sc.timestamp ASC
    """, (ticker, cutoff)).fetchall()
    conn.close()

    if len(rows) < 2:
        return {"latest": None, "oldest": None, "delta": None, "n": len(rows)}

    latest = rows[-1]["short_pct"]
    oldest = rows[0]["short_pct"]
    delta = round(latest - oldest, 2)  # positive = shorts building, negative = covering
    return {"latest": latest, "oldest": oldest, "delta": delta, "n": len(rows)}


# ─────────────────────────────────────────────────────────────────────────────
# P2: Options Play P&L Tracking
# ─────────────────────────────────────────────────────────────────────────────

def log_play(ticker: str, horizon: str, strategy: str, strike: float,
             expiry: str, dte: int, entry_price: float, entry_iv_rank: float,
             lt_score: float, opt_score: float, rc_score: int,
             direction: str = "bullish", notes: str = "") -> int:
    """
    Log a generated play to options_plays for P&L tracking.
    Returns the new play ID.
    """
    conn = get_db()
    cursor = conn.execute("""
        INSERT INTO options_plays
            (ticker, generated_at, horizon, strategy, strike, expiry, dte,
             entry_price, entry_iv_rank, lt_score, opt_score, rc_score,
             direction, status, notes)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
    """, (
        ticker, datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        horizon, strategy, strike, expiry, dte,
        entry_price, entry_iv_rank, lt_score, opt_score, rc_score,
        direction, notes,
    ))
    play_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return play_id


def get_open_plays(days_old: int = 90) -> list:
    """Return all open (unexpired) plays generated within the last N days."""
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days_old)).strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT * FROM options_plays
        WHERE status = 'open' AND generated_at >= ?
        ORDER BY generated_at DESC
    """, (cutoff,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def close_play(play_id: int, outcome_price: float, pnl_pct: float,
               outcome_date: str = None) -> None:
    """Mark a play as closed with P&L outcome."""
    conn = get_db()
    outcome_date = outcome_date or datetime.now().strftime("%Y-%m-%d")
    conn.execute("""
        UPDATE options_plays
        SET status = 'closed', outcome_price = ?, outcome_date = ?, pnl_pct = ?
        WHERE id = ?
    """, (outcome_price, outcome_date, pnl_pct, play_id))
    conn.commit()
    conn.close()


def get_play_history(ticker: str = None, limit: int = 50) -> list:
    """
    Return closed plays for P&L review.
    Optionally filtered by ticker.
    """
    conn = get_db()
    if ticker:
        rows = conn.execute("""
            SELECT * FROM options_plays
            WHERE status = 'closed' AND ticker = ?
            ORDER BY outcome_date DESC LIMIT ?
        """, (ticker.upper(), limit)).fetchall()
    else:
        rows = conn.execute("""
            SELECT * FROM options_plays
            WHERE status = 'closed'
            ORDER BY outcome_date DESC LIMIT ?
        """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_play_stats() -> dict:
    """
    Return aggregate P&L stats across all closed plays.
    Returns: total_closed, win_rate, avg_pnl, best_play, worst_play
    """
    conn = get_db()
    rows = conn.execute("""
        SELECT pnl_pct, ticker, expiry, strategy
        FROM options_plays WHERE status = 'closed' AND pnl_pct IS NOT NULL
    """).fetchall()
    conn.close()

    if not rows:
        return {"total_closed": 0, "win_rate": None, "avg_pnl": None,
                "best_play": None, "worst_play": None}

    pnls = [r["pnl_pct"] for r in rows]
    wins = [p for p in pnls if p > 0]
    return {
        "total_closed": len(pnls),
        "win_rate": round(len(wins) / len(pnls) * 100, 1),
        "avg_pnl": round(sum(pnls) / len(pnls), 1),
        "best_play": dict(rows[pnls.index(max(pnls))]),
        "worst_play": dict(rows[pnls.index(min(pnls))]),
    }


# ─────────────────────────────────────────────
# USER & AUGUR PROFILE FUNCTIONS
# ─────────────────────────────────────────────

def create_user(email: str, password_hash: str, augur_name: str) -> int:
    """Create a new user. Returns user ID. Raises sqlite3.IntegrityError on duplicate."""
    conn = get_db()
    try:
        cursor = conn.execute(
            "INSERT INTO users (email, password_hash, augur_name, created_at) VALUES (?, ?, ?, ?)",
            (email.lower().strip(), password_hash, augur_name.strip(), datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        user_id = cursor.lastrowid
        conn.commit()
        return user_id
    finally:
        conn.close()


def get_user_by_email(email: str) -> dict | None:
    """Look up a user by email. Returns dict or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower().strip(),)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    """Look up a user by ID. Returns dict or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_user_last_login(user_id: int):
    """Update last_login timestamp."""
    conn = get_db()
    conn.execute("UPDATE users SET last_login = ? WHERE id = ?",
                 (datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id))
    conn.commit()
    conn.close()


def create_augur_profile(user_id: int, attrs: dict) -> int:
    """
    Create an Augur character profile.
    attrs: {prudentia, audacia, sapientia, fortuna, prospectus, liquiditas}
    Returns profile ID.
    """
    avatar_seed = secrets.token_hex(8)
    conn = get_db()
    try:
        cursor = conn.execute("""
            INSERT INTO augur_profiles (
                user_id, prudentia, audacia, sapientia, fortuna, prospectus, liquiditas,
                avatar_seed, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            user_id,
            attrs["prudentia"], attrs["audacia"], attrs["sapientia"],
            attrs["fortuna"], attrs["prospectus"], attrs["liquiditas"],
            avatar_seed,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ))
        profile_id = cursor.lastrowid
        conn.commit()
        return profile_id
    finally:
        conn.close()


def get_augur_profile(user_id: int) -> dict | None:
    """Get a user's Augur profile. Returns dict or None."""
    conn = get_db()
    row = conn.execute("SELECT * FROM augur_profiles WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_augur_profile_by_id(profile_id: int) -> dict | None:
    """Get an Augur profile by its own ID (for public view)."""
    conn = get_db()
    row = conn.execute("""
        SELECT ap.*, u.augur_name FROM augur_profiles ap
        JOIN users u ON ap.user_id = u.id
        WHERE ap.id = ?
    """, (profile_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_augur_profile(user_id: int, attrs: dict) -> bool:
    """Update Augur attributes (respec). Returns True if updated."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor = conn.execute("""
        UPDATE augur_profiles SET
            prudentia = ?, audacia = ?, sapientia = ?,
            fortuna = ?, prospectus = ?, liquiditas = ?,
            updated_at = ?, last_respec = ?
        WHERE user_id = ?
    """, (
        attrs["prudentia"], attrs["audacia"], attrs["sapientia"],
        attrs["fortuna"], attrs["prospectus"], attrs["liquiditas"],
        now, now, user_id,
    ))
    conn.commit()
    updated = cursor.rowcount > 0
    conn.close()
    return updated


def save_refresh_token(user_id: int, token_hash: str, expires_at: str):
    """Store a hashed refresh token."""
    conn = get_db()
    conn.execute(
        "INSERT INTO refresh_tokens (user_id, token_hash, expires_at, created_at) VALUES (?, ?, ?, ?)",
        (user_id, token_hash, expires_at, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    )
    conn.commit()
    conn.close()


def validate_refresh_token(token_hash: str) -> dict | None:
    """Look up a refresh token. Returns {user_id, expires_at} or None."""
    conn = get_db()
    row = conn.execute(
        "SELECT user_id, expires_at FROM refresh_tokens WHERE token_hash = ?",
        (token_hash,)
    ).fetchone()
    conn.close()
    if not row:
        return None
    result = dict(row)
    if datetime.strptime(result["expires_at"], "%Y-%m-%d %H:%M:%S") < datetime.now():
        return None  # expired
    return result


def delete_refresh_token(token_hash: str):
    """Delete a refresh token (logout)."""
    conn = get_db()
    conn.execute("DELETE FROM refresh_tokens WHERE token_hash = ?", (token_hash,))
    conn.commit()
    conn.close()


def delete_user_refresh_tokens(user_id: int):
    """Delete all refresh tokens for a user."""
    conn = get_db()
    conn.execute("DELETE FROM refresh_tokens WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def get_all_augur_profiles(limit: int = 50) -> list:
    """Get all Augur profiles with user names (for community/leaderboard)."""
    conn = get_db()
    rows = conn.execute("""
        SELECT ap.*, u.augur_name, u.email
        FROM augur_profiles ap
        JOIN users u ON ap.user_id = u.id
        ORDER BY ap.xp DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_user_admin(user_id: int, is_admin: bool = True):
    """Grant or revoke admin privileges."""
    conn = get_db()
    conn.execute("UPDATE users SET is_admin = ? WHERE id = ?", (1 if is_admin else 0, user_id))
    conn.commit()
    conn.close()


def is_user_admin(user_id: int) -> bool:
    """Check if user has admin flag."""
    conn = get_db()
    row = conn.execute("SELECT is_admin FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return bool(row and row["is_admin"])


def update_augur_xp(user_id: int, xp_gained: int) -> dict:
    """
    Grant XP to a user, leveling up if threshold crossed.
    Level formula: cost from L to L+1 = L * 100
    Total XP to reach level L = 100 * L * (L-1) / 2
    Returns dict with xp_gained, total_xp, level, old_level, leveled_up, xp_into_level, xp_for_next.
    """
    conn = get_db()
    row = conn.execute("SELECT xp, level FROM augur_profiles WHERE user_id = ?", (user_id,)).fetchone()
    if not row:
        conn.close()
        return None

    old_xp = row["xp"] or 0
    old_level = row["level"] or 1
    new_xp = old_xp + xp_gained

    # Calculate new level
    new_level = old_level
    while True:
        xp_for_next = 100 * new_level * (new_level + 1) // 2  # total XP to reach next level
        if new_xp >= xp_for_next:
            new_level += 1
        else:
            break

    # XP into current level and XP needed for next
    xp_at_current = 100 * new_level * (new_level - 1) // 2
    xp_at_next = 100 * (new_level + 1) * new_level // 2
    xp_into_level = new_xp - xp_at_current
    xp_for_next = xp_at_next - xp_at_current

    # Determine rank
    ranks = [
        {"id": "plebeian",  "minLevel": 1,  "name": "Plebeian"},
        {"id": "equite",    "minLevel": 6,  "name": "Equite"},
        {"id": "quaestor",  "minLevel": 16, "name": "Quaestor"},
        {"id": "master",    "minLevel": 31, "name": "Master"},
        {"id": "senator",   "minLevel": 51, "name": "Senator"},
    ]
    old_rank = ranks[0]
    new_rank = ranks[0]
    for r in ranks:
        if old_level >= r["minLevel"]:
            old_rank = r
        if new_level >= r["minLevel"]:
            new_rank = r

    conn.execute(
        "UPDATE augur_profiles SET xp = ?, level = ?, updated_at = ? WHERE user_id = ?",
        (new_xp, new_level, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), user_id)
    )
    conn.commit()
    conn.close()

    return {
        "xp_gained": xp_gained,
        "total_xp": new_xp,
        "level": new_level,
        "old_level": old_level,
        "leveled_up": new_level > old_level,
        "xp_into_level": xp_into_level,
        "xp_for_next": xp_for_next,
        "rank": new_rank["name"],
        "old_rank": old_rank["name"],
        "rank_up": new_rank["id"] != old_rank["id"],
    }


def get_augur_daily_xp(user_id: int) -> str | None:
    """Get the last date this user received daily XP. Returns date string or None."""
    conn = get_db()
    row = conn.execute("SELECT last_daily_xp FROM augur_profiles WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if row and row["last_daily_xp"]:
        return row["last_daily_xp"]
    return None


def set_augur_daily_xp(user_id: int, date_str: str):
    """Set the last daily XP date for a user."""
    conn = get_db()
    conn.execute(
        "UPDATE augur_profiles SET last_daily_xp = ? WHERE user_id = ?",
        (date_str, user_id)
    )
    conn.commit()
    conn.close()


def get_augur_buildings_entered(user_id: int) -> dict:
    """Get dict of buildings this user has entered (for first-entry bonus)."""
    conn = get_db()
    row = conn.execute("SELECT buildings_entered FROM augur_profiles WHERE user_id = ?", (user_id,)).fetchone()
    conn.close()
    if row and row["buildings_entered"]:
        try:
            return json.loads(row["buildings_entered"])
        except (json.JSONDecodeError, TypeError):
            pass
    return {}


def set_augur_buildings_entered(user_id: int, buildings: dict):
    """Update the buildings_entered JSON for a user."""
    conn = get_db()
    conn.execute(
        "UPDATE augur_profiles SET buildings_entered = ? WHERE user_id = ?",
        (json.dumps(buildings), user_id)
    )
    conn.commit()
    conn.close()


# ─── Social Presence ───────────────────────────────────────

def upsert_augur_presence(user_id: int, augur_name: str, level: int, rank_idx: int, tile_x: int, tile_y: int):
    """Insert or update augur presence on heartbeat. One row per user."""
    conn = get_db()
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    conn.execute("""
        INSERT INTO augur_presence (user_id, augur_name, level, rank_idx, tile_x, tile_y, last_heartbeat, is_active)
        VALUES (?, ?, ?, ?, ?, ?, ?, 1)
        ON CONFLICT(user_id) DO UPDATE SET
            augur_name = excluded.augur_name,
            level = excluded.level,
            rank_idx = excluded.rank_idx,
            tile_x = excluded.tile_x,
            tile_y = excluded.tile_y,
            last_heartbeat = excluded.last_heartbeat,
            is_active = 1
    """, (user_id, augur_name, level, rank_idx, tile_x, tile_y, now))
    conn.commit()
    conn.close()


def get_nearby_augurs(exclude_user_id: int, max_age_seconds: int = 60) -> list:
    """Get active augurs with heartbeat within max_age_seconds. Excludes the requesting user."""
    conn = get_db()
    cutoff = (datetime.now() - timedelta(seconds=max_age_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    rows = conn.execute("""
        SELECT user_id, augur_name, level, rank_idx, tile_x, tile_y, stance_type, stance_data
        FROM augur_presence
        WHERE user_id != ? AND is_active = 1 AND last_heartbeat >= ?
        ORDER BY last_heartbeat DESC
        LIMIT 50
    """, (exclude_user_id, cutoff)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_augur_stance(user_id: int, stance_type: str | None, stance_data: str | None):
    """Set or clear a user's stance (e.g. 'merchant' with scroll data)."""
    conn = get_db()
    conn.execute(
        "UPDATE augur_presence SET stance_type = ?, stance_data = ? WHERE user_id = ?",
        (stance_type, stance_data, user_id)
    )
    conn.commit()
    conn.close()


def clear_stale_presences(max_age_seconds: int = 300):
    """Mark augurs inactive if heartbeat is older than max_age_seconds."""
    conn = get_db()
    cutoff = (datetime.now() - timedelta(seconds=max_age_seconds)).strftime("%Y-%m-%d %H:%M:%S")
    conn.execute(
        "UPDATE augur_presence SET is_active = 0 WHERE last_heartbeat < ?",
        (cutoff,)
    )
    conn.commit()
    conn.close()
