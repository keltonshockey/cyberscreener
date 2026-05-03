"""
CyberScreener API v3 — FastAPI backend with auth, v2 scoring, and self-calibration.
"""

import sys
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent))

from fastapi import FastAPI, BackgroundTasks, Query, Header, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime, timedelta
import time
import hashlib
import json
import logging

logger = logging.getLogger(__name__)

from deps import (
    AUTH_AVAILABLE as _AUTH_AVAILABLE,
    check_rate_limit as _check_rate_limit,
    get_current_user,
    require_current_user,
    require_admin,
)

from core.scanner import (
    run_scan,
    fetch_options_chain, generate_plays, fetch_ticker_data,
    score_long_term, score_options, get_weights, set_weights,
    DEFAULT_LT_WEIGHTS, DEFAULT_OPT_WEIGHTS,
)
from core.universe import (
    CYBER_UNIVERSE, ENERGY_UNIVERSE, DEFENSE_UNIVERSE,
    get_universe_by_sector, get_sector_summary, get_all_tickers,
    ALL_CYBER_TICKERS, ALL_ENERGY_TICKERS, ALL_DEFENSE_TICKERS,
    ALL_BROAD_TICKERS,
    get_ticker_meta,
)
# Full multi-sector universe (cyber + energy + defense + broad S&P500/Nasdaq100, deduplicated)
ALL_TICKERS = sorted(list(set(ALL_CYBER_TICKERS + ALL_ENERGY_TICKERS + ALL_DEFENSE_TICKERS + ALL_BROAD_TICKERS)))
from db.models import (
    init_db, save_scan, get_score_history,
    get_all_scores_for_backtest, get_scan_count, get_db,
    save_score_weights, get_latest_weights,
    get_watchlist, add_to_watchlist, remove_from_watchlist, get_watchlist_tickers,
    # P2: P&L tracking
    log_play, get_open_plays, close_play, get_play_history, get_play_stats,
    # P4: User auth + Augur profiles
    create_user, get_user_by_email, get_user_by_id, update_user_last_login,
    create_augur_profile, get_augur_profile, get_augur_profile_by_id,
    update_augur_profile, update_augur_xp,
    get_augur_daily_xp, set_augur_daily_xp,
    get_augur_buildings_entered, set_augur_buildings_entered,
    save_refresh_token, validate_refresh_token,
    delete_refresh_token, delete_user_refresh_tokens, get_all_augur_profiles,
    set_user_admin, is_user_admin,
    # P5: Social presence
    upsert_augur_presence, get_nearby_augurs, set_augur_stance, clear_stale_presences,
)
from db.migrate_timing import run_migration as _run_timing_migration
from db.migrate_sectors import run_migration as _run_sectors_migration
from db.migrate_threat import run_migration as _run_threat_migration
from db.migrate_watchlist import run_migration as _run_watchlist_migration
from db.migrate_options_plays import run_migration as _run_options_plays_migration
from db.migrate_short_delta import run_migration as _run_short_delta_migration
from db.migrate_augur import run_migration as _run_augur_migration
from db.migrate_presence import run_migration as _run_presence_migration
try:
    from intel.notifier import notify_high_rc_play as _notify_high_rc_play
    _NOTIFIER_AVAILABLE = True
except ImportError:
    _NOTIFIER_AVAILABLE = False
from intel.earnings_calendar import seed_from_payload, save_earnings_date, get_all_upcoming_dates
from backtest.engine import (
    run_full_backtest,
    backtest_score_vs_returns,
    backtest_layer_attribution,
    backtest_earnings_timing,
    calibrate_weights,
)
from core.augur_weights import (
    validate_attributes, compute_user_weights, describe_augur,
    rescore_with_user_weights, ATTRIBUTES, ATTRIBUTE_POOL,
)

from deps import API_PASSWORD


# Allowed origins: production domain + local dev
_ALLOWED_ORIGINS = [
    "https://cyber.keltonshockey.com",
    "https://quaest.tech",
    "https://www.quaest.tech",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "http://localhost:3000",
]

app = FastAPI(title="Augur API", version="4.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization"],
    allow_credentials=True,
)

from routers.auth import router as _auth_router
from routers.backtest import router as _backtest_router
from routers.scores import router as _scores_router
from routers.market import router as _market_router

app.include_router(_auth_router)
app.include_router(_backtest_router)
app.include_router(_scores_router)
app.include_router(_market_router)

init_db()
try:
    _run_timing_migration()
    print("✅ Timing migration complete")
except Exception as _me:
    print(f"Timing migration warning: {_me}")
try:
    _run_sectors_migration()
    print("✅ Sectors migration complete")
except Exception as _me:
    print(f"Sectors migration warning: {_me}")
try:
    _run_threat_migration()
except Exception as _me:
    print(f"Threat migration warning: {_me}")
try:
    _run_watchlist_migration()
    print("✅ Watchlist migration complete")
except Exception as _me:
    print(f"Watchlist migration warning: {_me}")
try:
    _run_options_plays_migration()
    print("✅ Options plays migration complete")
except Exception as _me:
    print(f"Options plays migration warning: {_me}")
try:
    _run_short_delta_migration()
    print("✅ Short delta migration complete")
except Exception as _me:
    print(f"Short delta migration warning: {_me}")
try:
    _run_augur_migration()
    print("✅ Augur migration complete")
except Exception as _me:
    print(f"Augur migration warning: {_me}")
try:
    _run_presence_migration()
    print("✅ Presence migration complete")
except Exception as _me:
    print(f"Presence migration warning: {_me}")

# Load saved weights if available
def _load_saved_weights():
    for score_type in ["lt", "opt"]:
        saved = get_latest_weights(score_type)
        if saved:
            if score_type == "lt":
                set_weights(lt_weights=saved["weights"])
            else:
                set_weights(opt_weights=saved["weights"])
try:
    _load_saved_weights()
except Exception:
    pass

# Backtest warmup intentionally deferred to first request — loading 380K scores at
# startup exhausts RAM on a 1GB droplet and triggers the OOM killer.

from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# ── React SPA + Legacy Dashboard Serving ──

def _find_react_dist():
    """Find the React build directory."""
    candidates = [
        Path(__file__).parent.parent / "frontend" / "dist",
        Path("/app/frontend/dist"),
        Path("/opt/cyberscreener/frontend/dist"),
    ]
    for p in candidates:
        if p.exists() and (p / "index.html").exists():
            return p
    return None

def _find_dashboard():
    """Find the legacy single-file dashboard."""
    candidates = [
        Path(__file__).parent / "dashboard_embed.html",
        Path(__file__).parent.parent / "dashboard_embed.html",
        Path("/app/dashboard_embed.html"),
        Path("/app/api/dashboard_embed.html"),
    ]
    for p in candidates:
        if p.exists():
            return p
    return None

# Mount React static assets if build exists
_react_dist = _find_react_dist()
if _react_dist and (_react_dist / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(_react_dist / "assets")), name="react-assets")
    logger.info(f"Mounted React assets from {_react_dist / 'assets'}")

@app.get("/", response_class=HTMLResponse)
def serve_dashboard():
    # Prefer React SPA if built
    dist = _find_react_dist()
    if dist:
        return (dist / "index.html").read_text()
    # Fall back to legacy dashboard
    p = _find_dashboard()
    if p:
        return p.read_text()
    return "<h1>Dashboard not found</h1>"

@app.get("/legacy", response_class=HTMLResponse)
def serve_legacy_dashboard():
    """Serve the original single-file dashboard."""
    p = _find_dashboard()
    if p:
        return p.read_text()
    return "<h1>Legacy dashboard not found</h1>"

@app.get("/dashboard", response_class=HTMLResponse)
def serve_dashboard_alt():
    return serve_dashboard()

# ── Augur Character Models ─────────────────────────────────────────────────────

class AugurCreateRequest(BaseModel):
    prudentia: int = Field(..., ge=1, le=10)
    audacia: int = Field(..., ge=1, le=10)
    sapientia: int = Field(..., ge=1, le=10)
    fortuna: int = Field(..., ge=1, le=10)
    prospectus: int = Field(..., ge=1, le=10)
    liquiditas: int = Field(..., ge=1, le=10)

class AugurRespecRequest(BaseModel):
    prudentia: int = Field(..., ge=1, le=10)
    audacia: int = Field(..., ge=1, le=10)
    sapientia: int = Field(..., ge=1, le=10)
    fortuna: int = Field(..., ge=1, le=10)
    prospectus: int = Field(..., ge=1, le=10)
    liquiditas: int = Field(..., ge=1, le=10)


# ── Augur Character Endpoints ──────────────────────────────────────────────────

@app.post("/augur/create")
async def augur_create(req: AugurCreateRequest, user: dict = Depends(require_current_user)):
    """Create your Augur character. Attributes must sum to 36."""
    attrs = req.model_dump()
    valid, err = validate_attributes(attrs)
    if not valid:
        raise HTTPException(status_code=422, detail=err)

    # Check if already has a profile
    existing = get_augur_profile(user["id"])
    if existing:
        raise HTTPException(status_code=409, detail="Augur profile already exists. Use PUT /augur/respec to change.")

    profile_id = create_augur_profile(user["id"], attrs)
    desc = describe_augur(attrs)

    # Compute personalized weights preview
    lt_w, opt_w = compute_user_weights(attrs, DEFAULT_LT_WEIGHTS, DEFAULT_OPT_WEIGHTS)

    return {
        "profile_id": profile_id,
        "augur_name": user["augur_name"],
        "attributes": attrs,
        "dominant_trait": desc["dominant_trait"],
        "title": desc["title_suggestion"],
        "style": desc["style"],
        "lt_weights": lt_w,
        "opt_weights": opt_w,
    }


@app.put("/augur/respec")
async def augur_respec(req: AugurRespecRequest, user: dict = Depends(require_current_user)):
    """Respec your Augur character (change attributes). Limited to 1 per week."""
    attrs = req.model_dump()
    valid, err = validate_attributes(attrs)
    if not valid:
        raise HTTPException(status_code=422, detail=err)

    profile = get_augur_profile(user["id"])
    if not profile:
        raise HTTPException(status_code=404, detail="No Augur profile. Create one first via POST /augur/create.")

    # Rate-limit respec to 1/week
    if profile.get("last_respec"):
        last = datetime.strptime(profile["last_respec"], "%Y-%m-%d %H:%M:%S")
        if (datetime.now() - last).days < 7:
            days_left = 7 - (datetime.now() - last).days
            raise HTTPException(status_code=429, detail=f"Respec available in {days_left} day(s)")

    update_augur_profile(user["id"], attrs)
    desc = describe_augur(attrs)
    lt_w, opt_w = compute_user_weights(attrs, DEFAULT_LT_WEIGHTS, DEFAULT_OPT_WEIGHTS)

    return {
        "augur_name": user["augur_name"],
        "attributes": attrs,
        "dominant_trait": desc["dominant_trait"],
        "title": desc["title_suggestion"],
        "style": desc["style"],
        "lt_weights": lt_w,
        "opt_weights": opt_w,
    }


@app.get("/augur/profile")
async def augur_profile_me(user: dict = Depends(require_current_user)):
    """Get your full Augur profile with computed weight biases."""
    profile = get_augur_profile(user["id"])
    if not profile:
        raise HTTPException(status_code=404, detail="No Augur profile created yet")

    desc = describe_augur(profile)
    lt_w, opt_w = compute_user_weights(profile, DEFAULT_LT_WEIGHTS, DEFAULT_OPT_WEIGHTS)

    return {
        "user_id": user["id"],
        "augur_name": user["augur_name"],
        "attributes": {a: profile[a] for a in ATTRIBUTES},
        "avatar_seed": profile.get("avatar_seed"),
        "title": profile.get("title", "Novice Augur"),
        "xp": profile.get("xp", 0),
        "level": profile.get("level", 1),
        "dominant_trait": desc["dominant_trait"],
        "style": desc["style"],
        "lt_weights": lt_w,
        "opt_weights": opt_w,
        "base_lt_weights": DEFAULT_LT_WEIGHTS,
        "base_opt_weights": DEFAULT_OPT_WEIGHTS,
    }


# ── Social Presence (The Forum) ───────────────────────────────────────────────

class HeartbeatRequest(BaseModel):
    tile_x: int = Field(..., ge=0, le=200)
    tile_y: int = Field(..., ge=0, le=200)


class StanceRequest(BaseModel):
    stance_type: Optional[str] = None   # 'merchant' or None to clear
    stance_data: Optional[str] = None   # JSON scroll data


@app.post("/augur/heartbeat")
async def augur_heartbeat(req: HeartbeatRequest, user: dict = Depends(require_current_user)):
    """Send presence heartbeat with current tile position. Rate-limited: 10/min."""
    rate_key = f"heartbeat:{user['id']}"
    if not _check_rate_limit(rate_key, max_calls=10, window_seconds=60):
        raise HTTPException(status_code=429, detail="Heartbeat rate limit exceeded")

    # Get profile for level/rank
    profile = get_augur_profile(user["id"])
    level = profile["level"] if profile else 1

    # Determine rank index from level
    ranks = [
        {"minLevel": 1}, {"minLevel": 6}, {"minLevel": 16},
        {"minLevel": 31}, {"minLevel": 51},
    ]
    rank_idx = 0
    for i, r in enumerate(ranks):
        if level >= r["minLevel"]:
            rank_idx = i

    upsert_augur_presence(
        user_id=user["id"],
        augur_name=user["augur_name"],
        level=level,
        rank_idx=rank_idx,
        tile_x=req.tile_x,
        tile_y=req.tile_y,
    )

    # Opportunistically clean stale presences (> 5 min)
    clear_stale_presences(max_age_seconds=300)

    return {"ok": True, "tile_x": req.tile_x, "tile_y": req.tile_y}


@app.get("/augur/nearby")
async def augur_nearby(user: dict = Depends(require_current_user)):
    """Get nearby active augurs (heartbeat within last 60s). Excludes self."""
    augurs = get_nearby_augurs(exclude_user_id=user["id"], max_age_seconds=60)
    return {"augurs": augurs}


@app.post("/augur/stance")
async def augur_stance_endpoint(req: StanceRequest, user: dict = Depends(require_current_user)):
    """Set or clear merchant stance (display scroll data to other players)."""
    if req.stance_type and req.stance_type not in ("merchant",):
        raise HTTPException(status_code=400, detail="Invalid stance_type. Allowed: 'merchant'")

    # Validate stance_data is valid JSON if provided
    if req.stance_data:
        try:
            json.loads(req.stance_data)
        except (json.JSONDecodeError, TypeError):
            raise HTTPException(status_code=400, detail="stance_data must be valid JSON")

    set_augur_stance(user["id"], req.stance_type, req.stance_data)
    return {"ok": True, "stance_type": req.stance_type}


# ── Public Profile (catch-all — must come AFTER all /augur/... specific routes) ──
@app.get("/augur/{profile_id}")
async def augur_public_profile(profile_id: int):
    """Public Augur profile view (for community)."""
    profile = get_augur_profile_by_id(profile_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Augur not found")

    desc = describe_augur(profile)
    return {
        "augur_name": profile.get("augur_name", "Unknown"),
        "attributes": {a: profile[a] for a in ATTRIBUTES},
        "title": profile.get("title", "Novice Augur"),
        "xp": profile.get("xp", 0),
        "level": profile.get("level", 1),
        "dominant_trait": desc["dominant_trait"],
        "style": desc["style"],
        "avatar_seed": profile.get("avatar_seed"),
    }


@app.get("/augur/leaderboard/top")
async def augur_leaderboard(limit: int = Query(20, ge=1, le=100)):
    """Get top Augur profiles by XP."""
    profiles = get_all_augur_profiles(limit=limit)
    return {
        "augurs": [
            {
                "augur_name": p.get("augur_name"),
                "title": p.get("title", "Novice Augur"),
                "xp": p.get("xp", 0),
                "level": p.get("level", 1),
                "dominant_trait": describe_augur(p)["dominant_trait"],
                "avatar_seed": p.get("avatar_seed"),
            }
            for p in profiles
        ],
        "total": len(profiles),
    }


# ── XP & Leveling ─────────────────────────────────────────────────────────────

# XP values per action
_XP_ACTIONS = {
    "portal":      10,   # Enter a building door
    "scan":        50,   # Run a market scan
    "view_ticker": 15,   # View ticker detail
    "forge_smelt": 30,   # Backtest a strategy
    "npc_dialog":   5,   # Complete NPC dialog
    "daily_login": 25,   # First load per day
}
_FIRST_ENTRY_BONUS = 50  # Extra XP for first time entering each building

class XPGrantRequest(BaseModel):
    action: str = Field(..., description="XP action type")
    context: Optional[str] = Field(None, description="Additional context (e.g. district ID, NPC name)")

@app.post("/augur/xp")
async def grant_xp(req: XPGrantRequest, user: dict = Depends(require_current_user)):
    """Grant XP for in-game actions. Rate-limited: 10 calls/minute per action."""
    action = req.action
    context = req.context

    if action not in _XP_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    # Rate limit: 10 calls per minute per user per action
    rate_key = f"xp:{user['id']}:{action}"
    if not _check_rate_limit(rate_key, max_calls=10, window_seconds=60):
        raise HTTPException(status_code=429, detail="XP rate limit exceeded")

    base_xp = _XP_ACTIONS[action]
    bonus_xp = 0
    bonus_reason = None

    # Daily login bonus: only once per calendar day
    if action == "daily_login":
        today = datetime.now().strftime("%Y-%m-%d")
        last_daily = get_augur_daily_xp(user["id"])
        if last_daily == today:
            return {"xp_gained": 0, "total_xp": 0, "level": 0, "leveled_up": False,
                    "message": "Daily XP already claimed today"}
        set_augur_daily_xp(user["id"], today)

    # First-entry building bonus
    if action == "portal" and context:
        buildings = get_augur_buildings_entered(user["id"])
        if context not in buildings:
            buildings[context] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            set_augur_buildings_entered(user["id"], buildings)
            bonus_xp = _FIRST_ENTRY_BONUS
            bonus_reason = f"First entry: {context}"

    total_xp = base_xp + bonus_xp
    result = update_augur_xp(user["id"], total_xp)
    if result is None:
        raise HTTPException(status_code=404, detail="No Augur profile found")

    result["bonus_xp"] = bonus_xp
    result["bonus_reason"] = bonus_reason
    return result


# ── Personalized Scores ───────────────────────────────────────────────────────

@app.get("/scores/latest/personalized")
async def get_personalized_scores(
    limit: int = Query(100, ge=1, le=600),
    user: dict = Depends(require_current_user),
):
    """
    Returns latest scores re-weighted by the user's Augur attributes.
    Each ticker includes both system scores and personalized scores.
    """
    profile = get_augur_profile(user["id"])
    if not profile:
        raise HTTPException(status_code=404, detail="Create your Augur profile first")

    # Get user's personalized weights
    user_lt_w, user_opt_w = compute_user_weights(profile, DEFAULT_LT_WEIGHTS, DEFAULT_OPT_WEIGHTS)

    # Fetch latest system scores
    conn = get_db()
    rows = conn.execute("""
        SELECT s.* FROM scores s
        INNER JOIN (
            SELECT ticker, MAX(id) as max_id FROM scores GROUP BY ticker
        ) latest ON s.id = latest.max_id
        ORDER BY s.lt_score DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    results = []
    for row in rows:
        r = dict(row)
        ticker = r["ticker"]

        # Extract raw 0-1 scores from breakdown JSON
        lt_raw = {}
        opt_raw = {}
        try:
            lt_bd = json.loads(r.get("lt_breakdown") or "{}")
            for comp, data in lt_bd.items():
                if isinstance(data, dict) and "raw" in data:
                    lt_raw[comp] = data["raw"]
                elif isinstance(data, dict) and "points" in data and "max" in data and data["max"] > 0:
                    lt_raw[comp] = data["points"] / data["max"]  # backward compat
        except (json.JSONDecodeError, TypeError):
            pass
        try:
            opt_bd = json.loads(r.get("opt_breakdown") or "{}")
            for comp, data in opt_bd.items():
                if isinstance(data, dict) and "raw" in data:
                    opt_raw[comp] = data["raw"]
                elif isinstance(data, dict) and "points" in data and "max" in data and data["max"] > 0:
                    opt_raw[comp] = data["points"] / data["max"]
        except (json.JSONDecodeError, TypeError):
            pass

        # Recompute personalized scores
        user_lt_score = rescore_with_user_weights(lt_raw, user_lt_w) if lt_raw else r.get("lt_score", 0)
        user_opt_score = rescore_with_user_weights(opt_raw, user_opt_w) if opt_raw else r.get("opt_score", 0)

        results.append({
            "ticker": ticker,
            "sector": r.get("sector"),
            "lt_score": r.get("lt_score", 0),
            "opt_score": r.get("opt_score", 0),
            "user_lt_score": user_lt_score,
            "user_opt_score": user_opt_score,
            "lt_delta": round(user_lt_score - (r.get("lt_score") or 0), 1),
            "opt_delta": round(user_opt_score - (r.get("opt_score") or 0), 1),
            "price": r.get("price"),
            "rsi": r.get("rsi"),
            "scanned_at": r.get("scanned_at"),
        })

    # Sort by user LT score
    results.sort(key=lambda x: x["user_lt_score"], reverse=True)

    return {
        "augur_name": user["augur_name"],
        "dominant_trait": describe_augur(profile)["dominant_trait"],
        "count": len(results),
        "scores": results,
    }


@app.get("/health")
def health():
    return {"status": "ok", "version": "3.0.0", "scans": get_scan_count()}


# ─── Backfill ───
_backfill_status = {"running": False, "message": "idle"}

@app.post("/backfill")
def trigger_backfill(background_tasks: BackgroundTasks, months: int = Query(6, ge=1, le=12), admin: dict = Depends(require_admin)):
    if _backfill_status["running"]:
        return {"status": "busy", "message": _backfill_status["message"]}
    background_tasks.add_task(_run_backfill_background, months)
    return {"status": "started", "message": f"Backfilling {months} months of history..."}

@app.get("/backfill/status")
def backfill_status():
    return _backfill_status

def _run_backfill_background(months):
    global _backfill_status
    _backfill_status["running"] = True
    _backfill_status["message"] = "Starting backfill..."
    try:
        import yfinance as yf
        import pandas as pd
        import numpy as np
        from datetime import timedelta

        _backfill_status["message"] = f"Downloading price history for {len(ALL_TICKERS)} tickers..."
        data = yf.download(ALL_TICKERS, period="1y", group_by="ticker", progress=False, threads=True)
        if data is None or data.empty:
            _backfill_status["message"] = "Error: Failed to download data"
            _backfill_status["running"] = False
            return

        _backfill_status["message"] = "Fetching fundamentals..."
        fundamentals = {}
        for ticker in ALL_TICKERS:
            try:
                t = yf.Ticker(ticker)
                info = t.info
                fundamentals[ticker] = {
                    "market_cap": info.get("marketCap", 0),
                    "revenue": info.get("totalRevenue", 0),
                    "revenue_growth": info.get("revenueGrowth", 0),
                    "gross_margins": info.get("grossMargins", 0),
                    "operating_margins": info.get("operatingMargins", 0),
                    "fcf": info.get("freeCashflow", 0),
                    "ps_ratio": info.get("priceToSalesTrailing12Months"),
                    "pe_ratio": info.get("trailingPE"),
                    "eps": info.get("trailingEps"),
                    "beta": info.get("beta", 1.0),
                    "short_pct": info.get("shortPercentOfFloat", 0) or 0,
                    "enterprise_value": info.get("enterpriseValue", 0),
                }
                time.sleep(0.2)
            except Exception:
                fundamentals[ticker] = {}

        today = datetime.today()
        start_date = today - timedelta(days=months * 30)
        sim_dates = []
        current = start_date
        while current < today - timedelta(days=7):
            while current.weekday() != 0:
                current += timedelta(days=1)
            if current < today - timedelta(days=7):
                sim_dates.append(current)
            current += timedelta(days=7)

        _backfill_status["message"] = f"Simulating {len(sim_dates)} weekly scans..."
        conn = get_db()
        total_records = 0

        for sim_idx, sim_date in enumerate(sim_dates):
            sim_date_str = sim_date.strftime("%Y-%m-%d")
            _backfill_status["message"] = f"Scan {sim_idx+1}/{len(sim_dates)} ({sim_date_str})"

            cursor = conn.execute(
                "INSERT INTO scans (timestamp, tickers_scanned, config_json, intel_layers) VALUES (?, ?, ?, ?)",
                (sim_date.strftime("%Y-%m-%d %H:%M:%S"), 0, '{"mode":"backfill","scoring":"v2"}', "base")
            )
            scan_id = cursor.lastrowid
            tickers_in_scan = 0

            for ticker in ALL_TICKERS:
                try:
                    if ticker in data.columns.get_level_values(0):
                        ticker_hist = data[ticker].dropna(subset=["Close"])
                    else:
                        continue

                    mask = ticker_hist.index <= pd.Timestamp(sim_date)
                    td = ticker_hist[mask]
                    if td.empty or len(td) < 20:
                        continue

                    close = td["Close"]
                    price = float(close.iloc[-1])
                    sma_20 = float(close.rolling(20).mean().iloc[-1])
                    sma_50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
                    sma_200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

                    delta_c = close.diff()
                    gain = delta_c.where(delta_c > 0, 0).rolling(14).mean()
                    loss_c = (-delta_c.where(delta_c < 0, 0)).rolling(14).mean()
                    rs = gain / loss_c
                    rsi = float((100 - (100 / (1 + rs))).iloc[-1])
                    if np.isnan(rsi): rsi = 50.0

                    rolling_std = float(close.rolling(20).std().iloc[-1])
                    bb_width = (rolling_std * 4) / sma_20 * 100 if sma_20 > 0 else 0

                    vol_ratio = 1.0
                    if "Volume" in td.columns and len(td) >= 20:
                        v20 = td["Volume"].tail(20).mean()
                        v5 = td["Volume"].tail(5).mean()
                        vol_ratio = float(v5 / v20) if v20 > 0 else 1.0

                    p21 = float(close.iloc[-21]) if len(close) >= 21 else price
                    p63 = float(close.iloc[-63]) if len(close) >= 63 else price
                    p0 = float(close.iloc[0])
                    hi = float(td["High"].max()) if "High" in td.columns else price

                    fund = fundamentals.get(ticker, {})
                    mc = fund.get("market_cap", 0)
                    rev = fund.get("revenue", 0)
                    fcf = fund.get("fcf", 0)
                    ev = fund.get("enterprise_value", 0)

                    row = {
                        "ticker": ticker, "price": round(price, 2),
                        "market_cap_b": round(mc / 1e9, 1) if mc else None,
                        "revenue_b": round(rev / 1e9, 2) if rev else None,
                        "revenue_growth_pct": round(fund.get("revenue_growth", 0) * 100, 1) if fund.get("revenue_growth") else None,
                        "gross_margin_pct": round(fund.get("gross_margins", 0) * 100, 1) if fund.get("gross_margins") else None,
                        "operating_margin_pct": round(fund.get("operating_margins", 0) * 100, 1) if fund.get("operating_margins") else None,
                        "fcf_m": round(fcf / 1e6, 0) if fcf else None,
                        "fcf_margin_pct": round((fcf / rev) * 100, 1) if rev and rev > 0 and fcf else None,
                        "ps_ratio": round(fund.get("ps_ratio"), 1) if fund.get("ps_ratio") else None,
                        "pe_ratio": round(fund.get("pe_ratio"), 1) if fund.get("pe_ratio") else None,
                        "ev_revenue": round(ev / rev, 1) if ev and rev and rev > 0 else None,
                        "eps": fund.get("eps"),
                        "beta": round(fund.get("beta", 1.0), 2) if fund.get("beta") else None,
                        "short_pct": round(fund.get("short_pct", 0) * 100, 1),
                        "rsi": round(rsi, 1), "sma_20": round(sma_20, 2),
                        "sma_50": round(sma_50, 2) if sma_50 else None,
                        "sma_200": round(sma_200, 2) if sma_200 else None,
                        "bb_width": round(bb_width, 1), "vol_ratio": round(vol_ratio, 2),
                        "perf_3m": round(((price / p63) - 1) * 100, 1),
                        "perf_1m": round(((price / p21) - 1) * 100, 1),
                        "perf_1y": round(((price / p0) - 1) * 100, 1),
                        "pct_from_52w_high": round(((price / hi) - 1) * 100, 1),
                        "iv_30d": None, "iv_rank": None, "days_to_earnings": None,
                        "price_above_sma20": price > sma_20,
                        "price_above_sma50": price > sma_50 if sma_50 else None,
                        "price_above_sma200": price > sma_200 if sma_200 else None,
                    }

                    lt_score, _, lt_bd = score_long_term(row)
                    opt_score, _, opt_bd = score_options(row)

                    conn.execute("""
                        INSERT INTO scores (
                            scan_id, ticker, price, market_cap_b, lt_score, opt_score,
                            lt_rule_of_40, lt_valuation, lt_fcf_margin, lt_trend, lt_earnings_quality, lt_discount_momentum,
                            opt_earnings_catalyst, opt_iv_context, opt_directional, opt_technical, opt_liquidity, opt_asymmetry,
                            revenue_growth_pct, gross_margin_pct, operating_margin_pct,
                            ps_ratio, pe_ratio, ev_revenue, fcf_m, fcf_margin_pct, revenue_b,
                            rsi, sma_20, sma_50, sma_200, bb_width, vol_ratio, iv_30d, iv_rank, beta, short_pct,
                            perf_1y, perf_3m, perf_1m, pct_from_52w_high, days_to_earnings,
                            sec_score, sentiment_score, whale_score,
                            lt_breakdown, opt_breakdown
                        ) VALUES (
                            ?,?,?,?,?,?,
                            ?,?,?,?,?,?,
                            ?,?,?,?,?,?,
                            ?,?,?,
                            ?,?,?,?,?,?,
                            ?,?,?,?,?,?,?,?,?,?,
                            ?,?,?,?,?,
                            ?,?,?,
                            ?,?
                        )
                    """, (
                        scan_id, ticker, row["price"], row.get("market_cap_b"), lt_score, opt_score,
                        lt_bd.get("rule_of_40", {}).get("points", 0), lt_bd.get("valuation", {}).get("points", 0),
                        lt_bd.get("fcf_margin", {}).get("points", 0), lt_bd.get("trend", {}).get("points", 0),
                        lt_bd.get("earnings_quality", {}).get("points", 0), lt_bd.get("discount_momentum", {}).get("points", 0),
                        opt_bd.get("earnings_catalyst", {}).get("points", 0), opt_bd.get("iv_context", {}).get("points", 0),
                        opt_bd.get("directional", {}).get("points", 0), opt_bd.get("technical", {}).get("points", 0),
                        opt_bd.get("liquidity", {}).get("points", 0), opt_bd.get("asymmetry", {}).get("points", 0),
                        row.get("revenue_growth_pct"), row.get("gross_margin_pct"), row.get("operating_margin_pct"),
                        row.get("ps_ratio"), row.get("pe_ratio"), row.get("ev_revenue"),
                        row.get("fcf_m"), row.get("fcf_margin_pct"), row.get("revenue_b"),
                        row["rsi"], row["sma_20"], row.get("sma_50"), row.get("sma_200"),
                        row["bb_width"], row["vol_ratio"], None, None, row.get("beta"), row.get("short_pct"),
                        row["perf_1y"], row["perf_3m"], row.get("perf_1m"), row["pct_from_52w_high"], None,
                        0, 0, 0,
                        json.dumps(lt_bd), json.dumps(opt_bd),
                    ))

                    conn.execute("INSERT OR IGNORE INTO prices (ticker, date, close_price) VALUES (?, ?, ?)",
                                 (ticker, sim_date_str, row["price"]))
                    for fwd in [7, 14, 30, 60]:
                        fmask = ticker_hist.index > pd.Timestamp(sim_date)
                        future = ticker_hist[fmask]
                        if not future.empty and len(future) >= fwd:
                            fp = float(future["Close"].iloc[min(fwd, len(future)-1)])
                            fd = (sim_date + timedelta(days=fwd)).strftime("%Y-%m-%d")
                            conn.execute("INSERT OR IGNORE INTO prices (ticker, date, close_price) VALUES (?, ?, ?)",
                                         (ticker, fd, fp))

                    tickers_in_scan += 1
                    total_records += 1
                except Exception:
                    continue

            conn.execute("UPDATE scans SET tickers_scanned = ? WHERE id = ?", (tickers_in_scan, scan_id))
            conn.commit()

        conn.close()
        _backfill_status["message"] = f"✅ Complete! {len(sim_dates)} scans, {total_records} records"
    except Exception as e:
        _backfill_status["message"] = f"Error: {str(e)}"
    finally:
        _backfill_status["running"] = False


# ─────────────────────────────────────────────
# MODELS
# ─────────────────────────────────────────────

class ScanRequest(BaseModel):
    tickers: Optional[list[str]] = None
    enable_sec: bool = True
    enable_sentiment: bool = False
    enable_whale: bool = False

class ScanStatus(BaseModel):
    status: str
    scan_id: Optional[int] = None
    tickers_scanned: int = 0
    duration_seconds: Optional[float] = None
    message: str = ""

_scan_status = {"running": False, "last_scan_id": None, "message": ""}


# ─────────────────────────────────────────────
# ENDPOINTS
# ─────────────────────────────────────────────

@app.get("/api/info")
def api_info():
    return {
        "service": "Augur",
        "version": "3.1.0",
        "scoring": "v2",
        "total_scans": get_scan_count(),
        "active_weights": get_weights(),
    }

@app.get("/tickers")
def get_tickers():
    return {"universe": CYBER_UNIVERSE, "all_tickers": ALL_TICKERS, "total": len(ALL_TICKERS)}

@app.post("/scan", response_model=ScanStatus)
def trigger_scan(req: ScanRequest, background_tasks: BackgroundTasks, admin: dict = Depends(require_admin)):
    if not _check_rate_limit("scan", max_calls=5, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many scan requests. Try again in 5 minutes.")
    if _scan_status["running"]:
        return ScanStatus(status="busy", message="A scan is already running.")
    background_tasks.add_task(_run_scan_background, req)
    return ScanStatus(status="started", message="Scan started. Check /scan/status.")

def _run_scan_background(req: ScanRequest):
    global _scan_status
    _scan_status["running"] = True
    _scan_status["message"] = "Scanning..."
    start_time = time.time()
    # Merge standard universe with watchlist tickers
    try:
        wl_tickers = get_watchlist_tickers()
    except Exception:
        wl_tickers = []
    base_tickers = req.tickers or ALL_TICKERS
    tickers = sorted(set(base_tickers) | set(wl_tickers))
    try:
        def progress_callback(ticker, i, total):
            _scan_status["message"] = f"Scanning {ticker} ({i+1}/{total})"
        results = run_scan(tickers=tickers, enable_sec=req.enable_sec, callback=progress_callback)
        duration = time.time() - start_time
        intel_layers = []
        if req.enable_sec: intel_layers.append("sec")
        if req.enable_sentiment: intel_layers.append("sentiment")
        if req.enable_whale: intel_layers.append("whale")
        scan_id, _ = save_scan(results, intel_layers=intel_layers, duration_seconds=duration)
        _scan_status["last_scan_id"] = scan_id
        _scan_status["message"] = f"Complete. {len(results)} tickers in {duration:.1f}s."
    except Exception as e:
        _scan_status["message"] = f"Error: {str(e)}"
    finally:
        _scan_status["running"] = False

@app.get("/scan/status")
def scan_status():
    return _scan_status




# ─── Self-Calibration ───

@app.post("/calibrate")
def trigger_calibration(
    days: int = Query(180, ge=30, le=365),
    forward_period: int = Query(30, ge=7, le=90),
    dry_run: bool = Query(False),
    admin: dict = Depends(require_admin),
):
    """Auto-adjust scoring weights based on backtest data. Admin only."""
    return calibrate_weights(days, forward_period, dry_run=dry_run)

@app.get("/weights")
def get_current_weights():
    """Get current scoring weights and calibration history."""
    current = get_weights()
    lt_saved = get_latest_weights("lt")
    opt_saved = get_latest_weights("opt")
    return {
        "active_weights": current,
        "defaults": {"lt": DEFAULT_LT_WEIGHTS, "opt": DEFAULT_OPT_WEIGHTS},
        "last_calibration": {
            "lt": {
                "timestamp": lt_saved.get("timestamp") if lt_saved else None,
                "correlation": lt_saved.get("backtest_correlation") if lt_saved else None,
                "quintile_spread": lt_saved.get("backtest_quintile_spread") if lt_saved else None,
            } if lt_saved else None,
            "opt": {
                "timestamp": opt_saved.get("timestamp") if opt_saved else None,
            } if opt_saved else None,
        }
    }

@app.post("/weights/reset")
def reset_weights(admin: dict = Depends(require_admin)):
    """Reset weights to defaults. Admin only."""
    set_weights(lt_weights=DEFAULT_LT_WEIGHTS, opt_weights=DEFAULT_OPT_WEIGHTS)
    return {"status": "reset", "weights": get_weights()}


# ─── Options Play Builder ───

# ─── Unified Reality Check Scorer ───
# Combines trade quality (R/R, breakeven), execution quality (volume, OI, spread),
# score alignment (opt+LT), IV context, catalyst timing, and technical confirmation.
def _compute_rc(play: dict, ticker_data: dict) -> dict:
    """
    Compute unified Reality Check score (0-100) for a generated play.
    Returns dict with total score and per-component breakdown.
    Higher = better quality. RC >= 70 → log for P&L tracking.
    """
    breakdown = {}

    opt_score = ticker_data.get("opt_score", 0) or 0
    lt_score = ticker_data.get("lt_score", 0) or 0
    iv_rank = ticker_data.get("iv_rank") or 50
    days_to_earnings = ticker_data.get("days_to_earnings")
    rsi = ticker_data.get("rsi", 50) or 50
    dte = play.get("dte", 30) or 30
    strategy = (play.get("strategy") or "").lower()
    direction = (play.get("direction") or "").lower()

    # ── 1. Trade Quality: R/R ratio + breakeven distance (max 25 pts) ──
    tq = 0
    rr = play.get("risk_reward_ratio", 0) or 0
    be_dist = play.get("breakeven_distance_pct", 0) or 0

    if rr >= 3.0:
        tq += 18
    elif rr >= 2.0:
        tq += 14
    elif rr >= 1.0:
        tq += 9
    elif rr >= 0.5:
        tq += 4

    # Breakeven distance bonus — closer = more achievable
    if be_dist < 3:
        tq += 7  # very tight breakeven
    elif be_dist < 6:
        tq += 5
    elif be_dist < 10:
        tq += 3
    elif be_dist < 15:
        tq += 1

    tq = min(25, tq)
    breakdown["trade_quality"] = {"points": tq, "max": 25, "detail": f"R/R {rr:.1f}:1, BE {be_dist:.1f}%"}

    # ── 2. Execution Quality: volume, OI, bid-ask spread (max 20 pts) ──
    eq = 0
    vol = play.get("volume", 0) or 0
    oi = play.get("open_interest", 0) or 0
    spread_pct = play.get("bid_ask_spread_pct") or 999

    # Volume scoring
    if vol >= 500:
        eq += 6
    elif vol >= 100:
        eq += 4
    elif vol >= 30:
        eq += 2

    # Open Interest scoring
    if oi >= 2000:
        eq += 6
    elif oi >= 500:
        eq += 4
    elif oi >= 100:
        eq += 2

    # Bid/Ask spread scoring
    if spread_pct < 5:
        eq += 8  # tight spread
    elif spread_pct < 10:
        eq += 5
    elif spread_pct < 20:
        eq += 2

    eq = min(20, eq)
    breakdown["execution"] = {"points": eq, "max": 20, "detail": f"Vol {vol}, OI {oi}, Sprd {spread_pct:.0f}%"}

    # ── 3. Score Alignment: opt_score + LT confluence (max 20 pts) ──
    # Relaxed thresholds — typical opt scores are 39-55, lt scores 45-75
    sa = 0
    if opt_score >= 65:
        sa += 12
    elif opt_score >= 50:
        sa += 9
    elif opt_score >= 40:
        sa += 6
    elif opt_score >= 30:
        sa += 3

    if lt_score >= 60:
        sa += 8
    elif lt_score >= 45:
        sa += 6
    elif lt_score >= 35:
        sa += 3

    sa = min(20, sa)
    breakdown["score_alignment"] = {"points": sa, "max": 20, "detail": f"Opt {opt_score}, LT {lt_score}"}

    # ── 4. IV Context: direction-aware IV rank (max 15 pts) ──
    # Widened sweet spots — normal IV environments (30-60%) should still score decently
    iv = 0
    is_buying = "long" in strategy or "buy" in play.get("action", "").lower() or "debit" in strategy
    is_selling = "credit" in strategy or "sell" in play.get("action", "").lower().split("/")[0]

    if is_buying and not is_selling:
        # Buying options: want lower IV (cheaper premium)
        if iv_rank < 25:
            iv += 15
        elif iv_rank < 45:
            iv += 11
        elif iv_rank < 60:
            iv += 7
        elif iv_rank < 75:
            iv += 3
        else:
            iv -= 2  # very expensive — mild penalty
    else:
        # Selling options / credit spreads: want higher IV (richer premium)
        if iv_rank > 70:
            iv += 15
        elif iv_rank > 50:
            iv += 11
        elif iv_rank > 35:
            iv += 7
        elif iv_rank > 20:
            iv += 3

    iv = max(0, min(15, iv))
    breakdown["iv_context"] = {"points": iv, "max": 15, "detail": f"IV Rank {iv_rank}%, {'buying' if is_buying else 'selling'}"}

    # ── 5. Catalyst Timing: earnings, technical catalyst, DTE window (max 10 pts) ──
    ct = 0
    price_above_sma20 = ticker_data.get("price_above_sma20", False)
    price_above_sma50 = ticker_data.get("price_above_sma50", False)

    if days_to_earnings is not None and 0 < days_to_earnings <= dte:
        ct += 7  # earnings within play window
    elif days_to_earnings is not None and days_to_earnings <= dte * 1.5:
        ct += 4
    else:
        # No earnings catalyst — award points for technical catalysts instead
        if rsi < 30 or rsi > 70:
            ct += 5  # RSI extreme = strong mean reversion catalyst
        elif rsi < 35 or rsi > 65:
            ct += 3  # approaching extreme
        if "bull" in direction and price_above_sma20 and price_above_sma50:
            ct += 2  # strong uptrend confirmation
        elif "bear" in direction and not price_above_sma20 and not price_above_sma50:
            ct += 2  # strong downtrend confirmation

    # DTE sweet spot bonus
    if 14 <= dte <= 60:
        ct += 3  # optimal DTE window
    elif 7 <= dte <= 90:
        ct += 1

    ct = min(10, ct)
    catalyst_detail = f"Earnings {'in ' + str(days_to_earnings) + 'd' if days_to_earnings else 'N/A'}, DTE {dte}"
    breakdown["catalyst"] = {"points": ct, "max": 10, "detail": catalyst_detail}

    # ── 6. Technical Confirmation: RSI + direction alignment (max 10 pts) ──
    tc = 0
    if "bull" in direction or "call" in strategy:
        if 35 <= rsi <= 60:
            tc += 7  # goldilocks zone for bullish
        elif rsi < 30:
            tc += 6  # oversold rebound
        elif 60 < rsi <= 70:
            tc += 4
        elif rsi < 35:
            tc += 5  # near oversold
        # RSI > 70 for bullish = risky, no points
    elif "bear" in direction or "put" in strategy:
        if 55 <= rsi <= 75:
            tc += 7  # goldilocks for bearish
        elif rsi > 75:
            tc += 6  # overbought reversal
        elif 40 <= rsi < 55:
            tc += 4
        elif rsi > 65:
            tc += 5  # near overbought
    else:
        # Neutral (straddle/strangle/iron condor)
        if rsi < 30 or rsi > 70:
            tc += 6  # extremes = bigger move potential
        elif rsi < 40 or rsi > 60:
            tc += 4
        elif 40 <= rsi <= 60 and price_above_sma20:
            tc += 3  # stable trend — good for premium selling

    tc = min(10, tc)
    breakdown["technical"] = {"points": tc, "max": 10, "detail": f"RSI {rsi:.0f}, {direction.split('(')[0].strip()}"}

    # ── Total ──
    total = tq + eq + sa + iv + ct + tc
    total = min(100, max(0, total))

    return {"score": total, "breakdown": breakdown}


_plays_cache = {}
_plays_status = {}
_PLAYS_CACHE_MAX = 200  # prevent unbounded memory growth

def _evict_plays_cache():
    """Drop the oldest half of entries when cache exceeds max size."""
    if len(_plays_cache) > _PLAYS_CACHE_MAX:
        sorted_keys = sorted(_plays_cache, key=lambda k: _plays_cache[k].get("timestamp", ""), reverse=False)
        for k in sorted_keys[:len(sorted_keys) // 2]:
            _plays_cache.pop(k, None)
            _plays_status.pop(k, None)

def _fetch_plays_background(ticker):
    global _plays_status, _plays_cache
    _plays_status[ticker] = {"running": True, "message": f"Fetching data for {ticker}..."}
    try:
        data = fetch_ticker_data(ticker)
        if not data:
            _plays_status[ticker] = {"running": False, "message": "done",
                                     "result": {"ticker": ticker, "plays": [], "error": "Could not fetch data"}}
            return

        _plays_status[ticker]["message"] = f"Fetching options chain for {ticker}..."
        chains = fetch_options_chain(ticker)
        if not chains:
            _plays_status[ticker] = {"running": False, "message": "done",
                                     "result": {"ticker": ticker, "plays": [], "price": data.get("price"),
                                                "error": "No options chain available"}}
            return

        _plays_status[ticker]["message"] = f"Generating plays for {ticker}..."
        plays = generate_plays(
            ticker=ticker, price=data["price"], chains=chains,
            days_to_earnings=data.get("days_to_earnings"),
            rsi=data.get("rsi", 50), iv_30d=data.get("iv_30d"),
            price_above_sma20=data.get("price_above_sma20", True),
            price_above_sma50=data.get("price_above_sma50", True),
            perf_3m=data.get("perf_3m", 0),
            lt_score=data.get("lt_score", 0),
            opt_score=data.get("opt_score", 0),
            iv_rank=data.get("iv_rank"),
            whale_bias=data.get("whale_bias", "neutral"),
        )

        # Score each play with unified Reality Check and log high-quality ones for P&L tracking
        scored_plays = []
        for play in plays:
            rc_result = _compute_rc(play, data)
            rc = rc_result["score"]
            play["rc_score"] = rc
            play["rc_breakdown"] = rc_result["breakdown"]
            scored_plays.append(play)
            if rc >= 70:
                try:
                    log_play(
                        ticker=ticker,
                        horizon=play.get("horizon", "medium"),
                        strategy=play.get("strategy", ""),
                        strike=play.get("strike"),
                        expiry=play.get("expiry"),
                        dte=play.get("dte", 30),
                        entry_price=data["price"],
                        entry_iv_rank=data.get("iv_rank"),
                        lt_score=data.get("lt_score", 0),
                        opt_score=data.get("opt_score", 0),
                        rc_score=rc,
                        direction=play.get("direction", "bullish"),
                        notes=play.get("rationale", ""),
                    )
                except Exception:
                    pass  # P&L logging is non-critical
                # Email alert for high-conviction plays (RC ≥ 80)
                if rc >= 80 and _NOTIFIER_AVAILABLE:
                    try:
                        play_with_price = {**play, "entry_price": data["price"]}
                        _notify_high_rc_play(ticker, play_with_price, rc)
                    except Exception:
                        pass  # notifications are non-critical

        result = {
            "ticker": ticker, "price": data["price"],
            "rsi": data.get("rsi"), "iv_30d": data.get("iv_30d"),
            "iv_rank": data.get("iv_rank"),
            "days_to_earnings": data.get("days_to_earnings"),
            "beta": data.get("beta"), "perf_3m": data.get("perf_3m"),
            "bb_width": data.get("bb_width"), "vol_ratio": data.get("vol_ratio"),
            "pct_from_52w_high": data.get("pct_from_52w_high"),
            "plays": scored_plays, "play_count": len(scored_plays),
            "timestamp": datetime.now().isoformat(),
        }
        _plays_cache[ticker] = {"data": result, "timestamp": datetime.now().isoformat()}
        _plays_status[ticker] = {"running": False, "message": "done", "result": result}
        _evict_plays_cache()
    except Exception as e:
        _plays_status[ticker] = {"running": False, "message": "done",
                                 "result": {"ticker": ticker, "plays": [], "error": str(e)}}


@app.get("/plays/top/recommendations")
def get_top_plays(limit: int = Query(5, ge=1, le=15)):
    conn = get_db()
    scan = conn.execute("SELECT id FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    if not scan:
        conn.close()
        return {"plays": [], "message": "No scans found."}

    rows = conn.execute("""
        SELECT ticker, price, opt_score, lt_score, rsi, iv_30d, days_to_earnings,
               bb_width, vol_ratio, beta, perf_3m, pct_from_52w_high
        FROM scores WHERE scan_id = ? ORDER BY opt_score DESC LIMIT ?
    """, (scan["id"], limit)).fetchall()
    conn.close()

    results = []
    for row in rows:
        row = dict(row)
        ticker = row["ticker"]
        try:
            chains = fetch_options_chain(ticker)
            if not chains:
                results.append({"ticker": ticker, "opt_score": row["opt_score"], "plays": [], "error": "No options chain"})
                continue
            plays = generate_plays(
                ticker=ticker, price=row["price"], chains=chains,
                days_to_earnings=row.get("days_to_earnings"),
                rsi=row.get("rsi", 50), iv_30d=row.get("iv_30d"),
                price_above_sma20=True, price_above_sma50=True,
                perf_3m=row.get("perf_3m", 0),
                lt_score=row.get("lt_score", 0),
                opt_score=row.get("opt_score", 0),
            )
            results.append({
                "ticker": ticker, "opt_score": row["opt_score"], "lt_score": row["lt_score"],
                "price": row["price"], "plays": plays, "play_count": len(plays),
            })
            time.sleep(0.3)
        except Exception as e:
            results.append({"ticker": ticker, "opt_score": row["opt_score"], "plays": [], "error": str(e)})

    return {"results": results, "total_plays": sum(r.get("play_count", 0) for r in results), "timestamp": datetime.now().isoformat()}


@app.post("/plays/{ticker}/generate")
def trigger_plays(ticker: str, background_tasks: BackgroundTasks, force: bool = Query(False)):
    ticker = ticker.upper()
    if ticker not in ALL_TICKERS:
        raise HTTPException(status_code=404, detail=f"{ticker} not in universe")

    if not force and ticker in _plays_cache:
        cached = _plays_cache[ticker]
        try:
            age = (datetime.now() - datetime.fromisoformat(cached["timestamp"])).seconds
            if age < 90:
                return {"status": "cached", "result": cached["data"]}
        except Exception:
            pass

    if ticker in _plays_status and _plays_status[ticker].get("running"):
        return {"status": "running", "message": _plays_status[ticker].get("message", "Working...")}

    background_tasks.add_task(_fetch_plays_background, ticker)
    return {"status": "started", "message": f"Generating plays for {ticker}..."}


@app.get("/plays/{ticker}/status")
def plays_status(ticker: str):
    ticker = ticker.upper()
    st = _plays_status.get(ticker)
    if not st:
        return {"status": "not_started"}
    if st["running"]:
        return {"status": "running", "message": st.get("message", "Working...")}
    return {"status": "done", "result": st.get("result")}


@app.get("/plays/{ticker}")
def get_plays_for_ticker(ticker: str):
    ticker = ticker.upper()
    if ticker not in ALL_TICKERS:
        raise HTTPException(status_code=404, detail=f"{ticker} not in universe")

    if ticker in _plays_cache:
        return _plays_cache[ticker]["data"]

    st = _plays_status.get(ticker)
    if st and not st.get("running") and st.get("result"):
        return st["result"]

    # Sync fallback — same logic as _fetch_plays_background but inline
    try:
        data = fetch_ticker_data(ticker)
        if not data:
            return {"ticker": ticker, "plays": [], "error": "Could not fetch data"}
        chains = fetch_options_chain(ticker)
        if not chains:
            return {"ticker": ticker, "plays": [], "error": "No options chain", "price": data.get("price")}
        plays = generate_plays(
            ticker=ticker, price=data["price"], chains=chains,
            days_to_earnings=data.get("days_to_earnings"),
            rsi=data.get("rsi", 50), iv_30d=data.get("iv_30d"),
            price_above_sma20=data.get("price_above_sma20", True),
            price_above_sma50=data.get("price_above_sma50", True),
            perf_3m=data.get("perf_3m", 0),
            lt_score=data.get("lt_score", 0),
            opt_score=data.get("opt_score", 0),
            iv_rank=data.get("iv_rank"),
            whale_bias=data.get("whale_bias", "neutral"),
        )
        # Score each play with unified Reality Check
        for play in plays:
            rc_result = _compute_rc(play, data)
            play["rc_score"] = rc_result["score"]
            play["rc_breakdown"] = rc_result["breakdown"]

        result = {
            "ticker": ticker, "price": data["price"],
            "rsi": data.get("rsi"), "iv_30d": data.get("iv_30d"),
            "iv_rank": data.get("iv_rank"),
            "days_to_earnings": data.get("days_to_earnings"),
            "beta": data.get("beta"), "perf_3m": data.get("perf_3m"),
            "bb_width": data.get("bb_width"), "vol_ratio": data.get("vol_ratio"),
            "pct_from_52w_high": data.get("pct_from_52w_high"),
            "plays": plays, "play_count": len(plays),
            "timestamp": datetime.now().isoformat(),
        }
        # Cache for 90s so subsequent requests don't re-compute
        _plays_cache[ticker] = {"data": result, "timestamp": datetime.now().isoformat()}
        _evict_plays_cache()
        return result
    except Exception as e:
        return {"ticker": ticker, "plays": [], "error": str(e)}


# ─── P2: Play P&L History Endpoints ───

@app.get("/plays/history/all")
def plays_history_all(limit: int = Query(50, ge=1, le=200)):
    """Return all closed plays for the P&L review panel."""
    return {
        "plays": get_play_history(limit=limit),
        "stats": get_play_stats(),
    }


@app.get("/plays/history/{ticker}")
def plays_history_ticker(ticker: str, limit: int = Query(20, ge=1, le=100)):
    """Return closed plays for a specific ticker."""
    return {
        "ticker": ticker.upper(),
        "plays": get_play_history(ticker=ticker, limit=limit),
    }


# ─── AI Play Analysis (Claude API) ───

@app.post("/plays/{ticker}/analyze")
def analyze_plays_ai(ticker: str):
    """Use Claude API to analyze generated plays for a ticker."""
    from intel.ai_analysis import analyze_plays as ai_analyze, is_available as ai_available

    ticker = ticker.upper()
    if not ai_available():
        return {"error": "AI analysis not configured. Set ANTHROPIC_API_KEY env var.", "available": False}

    # Get cached plays
    cached_plays = None
    if ticker in _plays_cache:
        cached_plays = _plays_cache[ticker]["data"]
    elif ticker in _plays_status and _plays_status[ticker].get("result"):
        cached_plays = _plays_status[ticker]["result"]

    if not cached_plays or not cached_plays.get("plays"):
        return {"error": f"No plays generated for {ticker}. Generate plays first.", "available": True}

    result = ai_analyze(
        ticker=ticker,
        price=cached_plays.get("price", 0),
        plays=cached_plays["plays"],
        ticker_data=cached_plays,
    )
    return {**result, "ticker": ticker, "available": True}


@app.get("/ai/status")
def ai_analysis_status():
    """Check if AI analysis is available."""
    from intel.ai_analysis import is_available
    return {"available": is_available()}


@app.get("/plays/open/tracked")
def plays_open_tracked():
    """Return all currently open (tracked, awaiting expiry) plays."""
    return {"plays": get_open_plays()}


# ─── Timing Debug Endpoints ───

@app.get("/debug/timing/{ticker}")
def debug_timing(ticker: str, admin: dict = Depends(require_admin)):
    """
    Test timing intelligence for a single ticker without running a full scan.
    Shows horizon classification, expiry selection, and all inputs used.
    """
    import yfinance as yf
    from core.timing import compute_timing_intelligence, get_earnings_date, classify_horizon
    import math

    def _safe(v, d=0.0):
        if v is None: return d
        try:
            f = float(v)
            return d if math.isnan(f) else f
        except: return d

    t = yf.Ticker(ticker.upper())
    result = {"ticker": ticker.upper(), "steps": [], "timing": None, "error": None}

    try:
        # Step 1: basic data
        info = t.fast_info
        price = _safe(getattr(info, 'last_price', None), 0)
        result["steps"].append(f"price=${price:.2f}")

        # Step 2: earnings date
        days_to_earnings = None
        try:
            ed_df = t.get_earnings_dates(limit=4)
            import pandas as pd
            if ed_df is not None and not ed_df.empty:
                now = pd.Timestamp.now(tz=ed_df.index[0].tzinfo) if ed_df.index[0].tzinfo else pd.Timestamp.now()
                future = ed_df[ed_df.index >= now]
                if not future.empty:
                    ed = future.index[0].date()
                    from datetime import datetime
                    days_to_earnings = (ed - datetime.today().date()).days
        except Exception as e:
            result["steps"].append(f"yfinance earnings date failed: {e}")

        dte_final, earnings_source = get_earnings_date(ticker.upper(), days_to_earnings)
        result["steps"].append(f"earnings_date: {dte_final}d out (source: {earnings_source})")

        # Step 3: fetch options chains
        fetched_chains = []
        try:
            dates = list(t.options) if t.options else []
            for exp in dates[:3]:
                try:
                    chain = t.option_chain(exp)
                    fetched_chains.append((exp, chain))
                except Exception:
                    continue
            result["steps"].append(f"chains_fetched: {len(fetched_chains)} expiries")
        except Exception as e:
            result["steps"].append(f"options fetch failed: {e}")

        # Step 4: build minimal data dict
        data = {
            "price": price,
            "days_to_earnings": dte_final,
            "lt_score": 55.0,   # placeholder — full scan needed for real value
            "opt_score": 30.0,
            "rsi": 50.0,
            "iv_rank": None,
            "whale_bias": "neutral",
            "perf_3m": 0.0,
            "iv_30d": None,
        }

        # Step 5: run timing
        timing = compute_timing_intelligence(ticker.upper(), data, fetched_chains)
        result["timing"] = timing
        result["note"] = "lt_score/opt_score are placeholders (55/30) — run /scan for real values"

    except Exception as e:
        result["error"] = str(e)

    return result


@app.get("/debug/timing-full/{ticker}")
def debug_timing_full(ticker: str, admin: dict = Depends(require_admin)):
    """
    Run a single-ticker full scan and return timing intelligence alongside all scores.
    Slower (~10s) but shows real lt_score/opt_score feeding into timing.
    """
    from core.scanner import fetch_ticker_data, score_long_term, score_options
    from core.timing import compute_timing_intelligence

    data = fetch_ticker_data(ticker.upper())
    if not data:
        return {"error": f"Failed to fetch data for {ticker}"}

    lt_score, _, lt_breakdown = score_long_term(data)
    opt_score, _, opt_breakdown = score_options(data)
    data["lt_score"] = lt_score
    data["opt_score"] = opt_score

    fetched_chains = data.pop("_fetched_chains", [])
    data.pop("_ticker_obj", None)

    timing = compute_timing_intelligence(ticker.upper(), data, fetched_chains)

    return {
        "ticker": ticker.upper(),
        "lt_score": lt_score,
        "opt_score": opt_score,
        "whale_score": data.get("whale_score", 0),
        "days_to_earnings": data.get("days_to_earnings"),
        "iv_rank": data.get("iv_rank"),
        "rsi": data.get("rsi"),
        "perf_3m": data.get("perf_3m"),
        "timing": timing,
    }

# ─── Universe Endpoints ───

@app.get("/universe")
def get_full_universe():
    return {
        "sectors": get_universe_by_sector(),
        "summary": get_sector_summary(),
        "tickers": {
            "cyber": ALL_CYBER_TICKERS,
            "energy": ALL_ENERGY_TICKERS,
            "defense": ALL_DEFENSE_TICKERS,
            "all": ALL_TICKERS,
        }
    }

@app.get("/tickers/{sector}")
def get_tickers_by_sector(sector: str):
    valid = ["cyber", "energy", "defense"]
    if sector not in valid:
        raise HTTPException(status_code=400, detail=f"Sector must be one of {valid}")
    tickers = get_all_tickers([sector])
    return {"sector": sector, "tickers": tickers, "total": len(tickers)}


# ─── Earnings Calendar Endpoints ───

class EarningsSeedRequest(BaseModel):
    dates: dict
    password: str

class EarningsSetRequest(BaseModel):
    ticker: str
    date: str
    report_time: Optional[str] = "unknown"
    password: str

@app.post("/earnings/seed")
def earnings_seed(req: EarningsSeedRequest, admin: dict = Depends(require_admin)):
    return seed_from_payload(req.dates)

@app.post("/earnings/set")
def earnings_set(req: EarningsSetRequest, admin: dict = Depends(require_admin)):
    try:
        d = datetime.strptime(req.date[:10], "%Y-%m-%d").date()
        ok = save_earnings_date(req.ticker.upper(), d, source="manual_override", report_time=req.report_time)
        if ok:
            return {"status": "saved", "ticker": req.ticker.upper(), "date": req.date}
        raise HTTPException(status_code=500, detail="Failed to save")
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date: {req.date}")

@app.get("/earnings/upcoming")
def earnings_upcoming():
    return {"dates": get_all_upcoming_dates()}


@app.get("/weights/history")
def get_weights_history(limit: int = Query(50, ge=1, le=200)):
    """Return full calibration history from score_weights table."""
    conn = get_db()
    rows = conn.execute(
        "SELECT * FROM score_weights ORDER BY id DESC LIMIT ?", (limit,)
    ).fetchall()
    conn.close()
    history = []
    for r in rows:
        entry = dict(r)
        try:
            entry["weights"] = json.loads(entry.get("weights_json") or "{}")
        except Exception:
            entry["weights"] = {}
        history.append(entry)
    return {"history": history, "count": len(history)}




# ── Test notification endpoint ─────────────────────────────────────────────────

@app.post("/notify/test")
def test_notification(admin: dict = Depends(require_admin)):
    """Send a test email to verify SendGrid configuration. Admin only."""
    if not _NOTIFIER_AVAILABLE:
        return {"status": "unavailable", "message": "Notifier module not loaded"}
    try:
        from intel.notifier import test_email, _ENABLED
        if not _ENABLED:
            return {"status": "disabled", "message": "Email not configured — set ALERT_EMAIL_TO, ALERT_EMAIL_FROM, SENDGRID_API_KEY"}
        sent = test_email()
        if sent:
            return {"status": "sent", "message": "Test email dispatched — check your inbox"}
        return {"status": "error", "message": "Send failed — check logs (sender may need verification in SendGrid)"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# ── Watchlist — Custom ticker tracking ────────────────────────────────────────

class WatchlistAddRequest(BaseModel):
    ticker: str
    notes: Optional[str] = ""
    sector: Optional[str] = "unknown"


@app.get("/watchlist")
def watchlist_list():
    """Return all watchlist items with their latest scan scores."""
    items = get_watchlist()
    if not items:
        return {"items": [], "total": 0}
    conn = get_db()
    for item in items:
        t = item["ticker"]
        score_row = conn.execute("""
            SELECT s.lt_score, s.opt_score, s.price, s.rsi, s.threat_score,
                   s.outage_status, s.sector as scored_sector
            FROM scores s
            INNER JOIN (
                SELECT ticker, MAX(scan_id) AS max_scan_id FROM scores GROUP BY ticker
            ) latest ON s.ticker = latest.ticker AND s.scan_id = latest.max_scan_id
            WHERE s.ticker = ?
        """, (t,)).fetchone()
        if score_row:
            item.update(dict(score_row))
            item["has_scores"] = True
        else:
            item["has_scores"] = False
    conn.close()
    return {"items": items, "total": len(items)}


def _scan_watchlist_ticker(ticker: str):
    """Run a quick single-ticker scan for a newly-added watchlist item."""
    try:
        from core.scanner import run_scan
        results = run_scan(tickers=[ticker], enable_sec=True, enable_sentiment=True)
        if results:
            save_scan(results, intel_layers=["sec", "sentiment"], duration_seconds=0)
            logger.info(f"✅ Watchlist scan complete for {ticker}")
    except Exception as e:
        logger.warning(f"Watchlist scan failed for {ticker}: {e}")


@app.post("/watchlist")
def watchlist_add(req: WatchlistAddRequest, background_tasks: BackgroundTasks):
    """Add a ticker to the watchlist and immediately trigger a background scan."""
    ticker = req.ticker.upper().strip()
    # Validate ticker format
    if not ticker or len(ticker) > 10 or not ticker.replace(".", "").isalnum():
        raise HTTPException(status_code=400, detail="Invalid ticker format (max 10 chars, alphanumeric)")
    try:
        added = add_to_watchlist(ticker, notes=req.notes or "", sector=req.sector or "unknown")
        if added:
            background_tasks.add_task(_scan_watchlist_ticker, ticker)
            return {
                "status": "added",
                "ticker": ticker,
                "message": f"{ticker} added — scanning now, scores ready in ~15s",
            }
        return {
            "status": "already_exists",
            "ticker": ticker,
            "message": f"{ticker} already in watchlist",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/watchlist/{ticker}")
def watchlist_remove(ticker: str):
    """Remove a ticker from the watchlist."""
    t = ticker.upper()
    if not t.replace(".", "").isalnum() or len(t) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker")
    remove_from_watchlist(t)
    return {"status": "removed", "ticker": t}


# ── Email Alerts ───────────────────────────────────────────────────────────────

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

SMTP_HOST = os.environ.get("SMTP_HOST", "")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
ALERT_EMAIL = os.environ.get("ALERT_EMAIL", "")


def _send_email(subject: str, body_html: str) -> bool:
    """Send an HTML email alert. Returns True on success."""
    if not all([SMTP_HOST, SMTP_USER, SMTP_PASS, ALERT_EMAIL]):
        print("⚠️ Email not configured (set SMTP_HOST, SMTP_USER, SMTP_PASS, ALERT_EMAIL env vars)")
        return False
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = SMTP_USER
        msg["To"] = ALERT_EMAIL
        msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, ALERT_EMAIL, msg.as_string())
        return True
    except Exception as e:
        print(f"⚠️ Email send failed: {e}")
        return False


@app.post("/alerts/send-killer-plays")
def send_killer_plays_alert(admin: dict = Depends(require_admin)):
    """Fetch killer plays and send an email alert."""
    if not _check_rate_limit("email_alert", max_calls=3, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Email alert rate limit: max 3/hour")

    # Get top plays
    plays_data = get_killer_plays(limit=8)
    plays = plays_data.get("plays", [])
    if not plays:
        return {"status": "skipped", "message": "No killer plays found meeting criteria"}

    # Build HTML email
    rows_html = ""
    for p in plays:
        rows_html += f"""
        <tr style="border-bottom:1px solid #eee">
          <td style="padding:8px 12px;font-weight:700;font-family:monospace">{p['ticker']}</td>
          <td style="padding:8px 12px">${p.get('price','—')}</td>
          <td style="padding:8px 12px;color:{'#34c759' if (p.get('opt_score',0))>=65 else '#ff9500'};font-weight:700">{p.get('opt_score','—')}</td>
          <td style="padding:8px 12px;color:#007aff;font-weight:700">{p.get('lt_score','—')}</td>
          <td style="padding:8px 12px">{p.get('catalyst','—')}</td>
          <td style="padding:8px 12px">{p.get('direction_label','—')}</td>
          <td style="padding:8px 12px;font-weight:700">{p.get('combined_score','—')}</td>
        </tr>"""

    body_html = f"""
    <html><body style="font-family:-apple-system,sans-serif;color:#1d1d1f;background:#f5f5f7;padding:0;margin:0">
    <div style="max-width:700px;margin:32px auto;background:#fff;border-radius:16px;overflow:hidden;box-shadow:0 2px 12px rgba(0,0,0,.08)">
      <div style="padding:24px 28px;background:linear-gradient(135deg,#007aff,#5856d6)">
        <h1 style="margin:0;color:#fff;font-size:22px">⚡ Augur Killer Plays Alert</h1>
        <p style="margin:6px 0 0;color:rgba(255,255,255,.8);font-size:13px">{datetime.now().strftime('%B %d, %Y at %H:%M UTC')} · {len(plays)} high-conviction opportunities</p>
      </div>
      <div style="padding:24px 28px">
        <p style="font-size:13px;color:#86868b;margin-bottom:16px">These tickers scored ≥55 opt + ≥40 LT with no active threat signals. Review on Augur before acting.</p>
        <table style="width:100%;border-collapse:collapse;font-size:13px">
          <thead><tr style="background:#f5f5f7;border-bottom:2px solid #e5e5ea">
            <th style="padding:8px 12px;text-align:left">Ticker</th>
            <th style="padding:8px 12px;text-align:left">Price</th>
            <th style="padding:8px 12px;text-align:left">Opt</th>
            <th style="padding:8px 12px;text-align:left">LT</th>
            <th style="padding:8px 12px;text-align:left">Catalyst</th>
            <th style="padding:8px 12px;text-align:left">Direction</th>
            <th style="padding:8px 12px;text-align:left">Score</th>
          </tr></thead>
          <tbody>{rows_html}</tbody>
        </table>
        <p style="margin-top:20px;font-size:11px;color:#aeaeb2">⚠️ For research only. Not financial advice. Past signals do not guarantee future results.</p>
      </div>
    </div></body></html>"""

    sent = _send_email(f"⚡ Augur: {len(plays)} Killer Plays Found", body_html)
    return {
        "status": "sent" if sent else "email_not_configured",
        "plays_count": len(plays),
        "plays": [p["ticker"] for p in plays],
    }


@app.get("/alerts/config")
def get_alert_config(admin: dict = Depends(require_admin)):
    """Check email alert configuration status. Admin only."""
    return {
        "configured": bool(SMTP_HOST and SMTP_USER and SMTP_PASS and ALERT_EMAIL),
        "smtp_host": SMTP_HOST or "(not set)",
        "alert_email": ALERT_EMAIL or "(not set)",
        "required_env_vars": ["SMTP_HOST", "SMTP_PORT", "SMTP_USER", "SMTP_PASS", "ALERT_EMAIL"],
    }


# ─── SPA Catch-All (must be LAST) ───
# Serves React index.html for any non-API path so React Router can handle client-side routing.

@app.get("/{full_path:path}", response_class=HTMLResponse)
def spa_catch_all(full_path: str):
    """SPA catch-all: serve React index.html for client-side routes."""
    # Don't catch API-like paths
    if full_path.startswith(("api/", "docs", "openapi", "redoc")):
        raise HTTPException(status_code=404)
    dist = _find_react_dist()
    if dist:
        return (dist / "index.html").read_text()
    # Fall back to legacy
    p = _find_dashboard()
    if p:
        return p.read_text()
    raise HTTPException(status_code=404, detail="Dashboard not found")
