-- Real production schema for the `scans` + `scores` tables, captured read-only
-- from the droplet (/app/data/cyberscreener.db) on 2026-06-08. Used by
-- test_scan_persist.py to exercise save_scan() against the true production shape
-- (67 data columns incl. rc_score) rather than the legacy CREATE TABLE in
-- models.py, which predates the migrate_*.py column additions.

CREATE TABLE scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    tickers_scanned INTEGER DEFAULT 0,
    duration_seconds REAL,
    config_json TEXT,
    intel_layers TEXT DEFAULT 'base'
);

CREATE TABLE scores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    price REAL,
    market_cap_b REAL,
    lt_score REAL DEFAULT 0,
    opt_score REAL DEFAULT 0,
    lt_rule_of_40 REAL,
    lt_valuation REAL,
    lt_fcf_margin REAL,
    lt_trend REAL,
    lt_earnings_quality REAL,
    lt_discount_momentum REAL,
    opt_earnings_catalyst REAL,
    opt_iv_context REAL,
    opt_directional REAL,
    opt_technical REAL,
    opt_liquidity REAL,
    opt_asymmetry REAL,
    revenue_growth_pct REAL,
    gross_margin_pct REAL,
    operating_margin_pct REAL,
    ps_ratio REAL,
    pe_ratio REAL,
    ev_revenue REAL,
    fcf_m REAL,
    fcf_margin_pct REAL,
    revenue_b REAL,
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
    perf_1y REAL,
    perf_3m REAL,
    perf_1m REAL,
    pct_from_52w_high REAL,
    days_to_earnings INTEGER,
    sec_score REAL DEFAULT 0,
    sentiment_score REAL DEFAULT 0,
    sentiment_bull_pct REAL,
    whale_score REAL DEFAULT 0,
    pc_ratio REAL,
    insider_buys_30d INTEGER DEFAULT 0,
    insider_sells_30d INTEGER DEFAULT 0,
    lt_breakdown TEXT,
    opt_breakdown TEXT,
    horizon TEXT,
    horizon_reason TEXT,
    horizon_confidence REAL,
    recommended_expiry TEXT,
    recommended_dte INTEGER,
    timing_signals TEXT,
    timing_debug TEXT,
    sector TEXT DEFAULT 'cyber',
    subsector TEXT,
    scoring_profile TEXT DEFAULT 'saas',
    threat_score REAL DEFAULT 100,
    outage_status TEXT DEFAULT 'none',
    breach_victim INTEGER DEFAULT 0,
    demand_signal INTEGER DEFAULT 0,
    short_delta REAL,
    rc_score INTEGER,
    iv_suspect INTEGER DEFAULT 0,  -- added by the iv-ingestion sanity migration (this PR)
    FOREIGN KEY (scan_id) REFERENCES scans(id)
);

CREATE INDEX idx_scores_scan ON scores(scan_id);
CREATE INDEX idx_scores_ticker ON scores(ticker);

-- prices + signals tables touched by save_scan() (minimal shape).
CREATE TABLE prices (
    ticker TEXT NOT NULL,
    date TEXT NOT NULL,
    close_price REAL,
    UNIQUE(ticker, date)
);

CREATE TABLE signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scan_id INTEGER NOT NULL,
    ticker TEXT NOT NULL,
    signal_type TEXT,
    signal_text TEXT,
    impact TEXT
);
