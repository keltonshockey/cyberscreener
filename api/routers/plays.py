"""
Options plays router — /plays/*, /ai/status.

Extracted verbatim from main.py (SESSION-ROUTER-SPLIT). Behavior-preserving:
same routes, methods, request/response schemas, and status codes.

Moved as a self-contained unit: the play cache/status state, the background
play fetcher, and the unified Reality Check scorer (_compute_rc) all live here
because their only callers are these endpoints. _compute_rc moved verbatim to
break the import cycle that would otherwise exist (main.py imports this router;
the endpoints need _compute_rc) — it is FROZEN and covered by a behavior test
in tests/test_compute_rc_frozen.py plus the existing scoring golden suite.
"""

import time
import logging
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Query, HTTPException

from core.scanner import (
    fetch_options_chain, generate_plays, fetch_ticker_data, _iv_for_play,
)
from core.universe import (
    ALL_CYBER_TICKERS, ALL_ENERGY_TICKERS, ALL_DEFENSE_TICKERS,
    ALL_BROAD_TICKERS,
)
from db.models import (
    get_db,
    log_play, get_open_plays, get_play_history, get_play_stats,
)
try:
    from intel.notifier import notify_high_rc_play as _notify_high_rc_play
    _NOTIFIER_AVAILABLE = True
except ImportError:
    _NOTIFIER_AVAILABLE = False

logger = logging.getLogger(__name__)

# Full multi-sector universe (deduplicated) — computed identically to main.py so
# the /plays/* universe membership checks behave byte-identically after extraction.
ALL_TICKERS = sorted(list(set(ALL_CYBER_TICKERS + ALL_ENERGY_TICKERS + ALL_DEFENSE_TICKERS + ALL_BROAD_TICKERS)))

router = APIRouter(tags=["plays"])


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

def _latest_scores_for(ticker):
    """Latest lt/opt scores for a ticker, for journal logging at entry time."""
    try:
        conn = get_db()
        row = conn.execute(
            "SELECT lt_score, opt_score FROM scores WHERE ticker = ? "
            "ORDER BY scan_id DESC LIMIT 1", (ticker,)).fetchone()
        conn.close()
        return dict(row) if row else None
    except Exception:
        return None


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
        # Untrustworthy IV (NULLed by the ingestion gate, absent, or pre-fix
        # corrupt) no longer drops the ticker — estimate from cap tier and flag it.
        _iv_use, _iv_estimated, _iv_note = _iv_for_play(data.get("iv_30d"), data.get("market_cap_b"))
        if _iv_estimated:
            logger.info(f"IV estimated [{ticker}]: {_iv_note}")
        plays = generate_plays(
            ticker=ticker, price=data["price"], chains=chains,
            days_to_earnings=data.get("days_to_earnings"),
            rsi=data.get("rsi", 50), iv_30d=_iv_use,
            price_above_sma20=data.get("price_above_sma20", True),
            price_above_sma50=data.get("price_above_sma50", True),
            perf_3m=data.get("perf_3m", 0),
            lt_score=data.get("lt_score", 0),
            opt_score=data.get("opt_score", 0),
            iv_rank=data.get("iv_rank"),
            whale_bias=data.get("whale_bias", "neutral"),
            weekly_above_sma20=data.get("weekly_above_sma20"),
            vol_ratio=data.get("vol_ratio", 1.0),
        )

        # Score each play with unified Reality Check and log high-quality ones for P&L tracking
        scored_plays = []
        for play in plays:
            rc_result = _compute_rc(play, data)
            rc = rc_result["score"]
            play["rc_score"] = rc
            play["rc_breakdown"] = rc_result["breakdown"]
            scored_plays.append(play)
            # Persist any play the forward-test journal would accept (its floor
            # is rc >= 50). Previously gated at 70, so rc 50-69 qualifying plays
            # were generated but never written to options_plays → never surfaced
            # by /killer-plays → journal logged appended=0. The RC >= 80 email
            # alert (nested below) is unchanged.
            if rc >= 50:
                try:
                    # fetch_ticker_data never carries lt/opt scores, so the old
                    # data.get(..., 0) filed conviction 0 on every journal row —
                    # read the latest scored values from the DB instead
                    scores_row = _latest_scores_for(ticker)
                    log_play(
                        ticker=ticker,
                        horizon=play.get("horizon", "medium"),
                        strategy=play.get("strategy", ""),
                        strike=play.get("strike"),
                        expiry=play.get("expiry"),
                        dte=play.get("dte", 30),
                        entry_price=play.get("entry_price", data["price"]),
                        entry_iv_rank=data.get("iv_rank"),
                        lt_score=scores_row["lt_score"] if scores_row else data.get("lt_score", 0),
                        opt_score=scores_row["opt_score"] if scores_row else data.get("opt_score", 0),
                        rc_score=rc,
                        direction=play.get("direction", "bullish"),
                        notes=play.get("rationale", ""),
                        max_loss=play.get("max_loss"),
                        risk_reward_ratio=play.get("risk_reward_ratio"),
                    )
                except Exception:
                    pass  # P&L logging is non-critical
                # Email alert for high-conviction plays (RC ≥ 80)
                if rc >= 80 and _NOTIFIER_AVAILABLE:
                    try:
                        play_with_price = {**play, "entry_price": play.get("entry_price", data["price"])}
                        _notify_high_rc_play(ticker, play_with_price, rc)
                    except Exception:
                        pass  # notifications are non-critical

        result = {
            "ticker": ticker, "price": data["price"],
            "rsi": data.get("rsi"), "iv_30d": data.get("iv_30d"),
            "iv_rank": data.get("iv_rank"),
            "iv_estimated": _iv_estimated, "iv_note": _iv_note,
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


@router.get("/plays/top/recommendations")
def get_top_plays(limit: int = Query(5, ge=1, le=15)):
    conn = get_db()
    scan = conn.execute("SELECT id FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    if not scan:
        conn.close()
        return {"plays": [], "message": "No scans found."}

    rows = conn.execute("""
        SELECT ticker, price, opt_score, lt_score, rsi, iv_30d, days_to_earnings,
               bb_width, vol_ratio, beta, perf_3m, pct_from_52w_high, market_cap_b
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
            _iv_use, _iv_estimated, _iv_note = _iv_for_play(row.get("iv_30d"), row.get("market_cap_b"))
            if _iv_estimated:
                logger.info(f"IV estimated batch [{ticker}]: {_iv_note}")
            # Derive SMA position from the row instead of assuming bullish — a
            # hardcoded price_above_sma=True was the same latent long-bias the
            # rebuild removes. None (unknown) is skipped by the helper, not read
            # as bullish.
            _p, _s20, _s50 = row.get("price"), row.get("sma_20"), row.get("sma_50")
            _above20 = (_p > _s20) if (_p is not None and _s20) else None
            _above50 = (_p > _s50) if (_p is not None and _s50) else None
            plays = generate_plays(
                ticker=ticker, price=row["price"], chains=chains,
                days_to_earnings=row.get("days_to_earnings"),
                rsi=row.get("rsi", 50), iv_30d=_iv_use,
                price_above_sma20=_above20, price_above_sma50=_above50,
                perf_3m=row.get("perf_3m", 0),
                lt_score=row.get("lt_score", 0),
                opt_score=row.get("opt_score", 0),
                vol_ratio=row.get("vol_ratio", 1.0),
            )
            results.append({
                "ticker": ticker, "opt_score": row["opt_score"], "lt_score": row["lt_score"],
                "price": row["price"], "plays": plays, "play_count": len(plays),
                "iv_estimated": _iv_estimated, "iv_note": _iv_note,
            })
            time.sleep(0.3)
        except Exception as e:
            results.append({"ticker": ticker, "opt_score": row["opt_score"], "plays": [], "error": str(e)})

    return {"results": results, "total_plays": sum(r.get("play_count", 0) for r in results), "timestamp": datetime.now().isoformat()}


@router.post("/plays/{ticker}/generate")
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


@router.get("/plays/{ticker}/status")
def plays_status(ticker: str):
    ticker = ticker.upper()
    st = _plays_status.get(ticker)
    if not st:
        return {"status": "not_started"}
    if st["running"]:
        return {"status": "running", "message": st.get("message", "Working...")}
    return {"status": "done", "result": st.get("result")}


@router.get("/plays/{ticker}")
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
        _iv_use, _iv_estimated, _iv_note = _iv_for_play(data.get("iv_30d"), data.get("market_cap_b"))
        if _iv_estimated:
            logger.info(f"IV estimated sync [{ticker}]: {_iv_note}")
        plays = generate_plays(  # weekly_above_sma20 + vol_ratio added below
            ticker=ticker, price=data["price"], chains=chains,
            days_to_earnings=data.get("days_to_earnings"),
            rsi=data.get("rsi", 50), iv_30d=_iv_use,
            price_above_sma20=data.get("price_above_sma20", True),
            price_above_sma50=data.get("price_above_sma50", True),
            perf_3m=data.get("perf_3m", 0),
            lt_score=data.get("lt_score", 0),
            opt_score=data.get("opt_score", 0),
            iv_rank=data.get("iv_rank"),
            whale_bias=data.get("whale_bias", "neutral"),
            weekly_above_sma20=data.get("weekly_above_sma20"),
            vol_ratio=data.get("vol_ratio", 1.0),
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
            "iv_estimated": _iv_estimated, "iv_note": _iv_note,
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

@router.get("/plays/history/all")
def plays_history_all(limit: int = Query(50, ge=1, le=200)):
    """Return all closed plays for the P&L review panel."""
    return {
        "plays": get_play_history(limit=limit),
        "stats": get_play_stats(),
    }


@router.get("/plays/history/{ticker}")
def plays_history_ticker(ticker: str, limit: int = Query(20, ge=1, le=100)):
    """Return closed plays for a specific ticker."""
    return {
        "ticker": ticker.upper(),
        "plays": get_play_history(ticker=ticker, limit=limit),
    }


# ─── AI Play Analysis (Claude API) ───

@router.post("/plays/{ticker}/analyze")
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


@router.get("/ai/status")
def ai_analysis_status():
    """Check if AI analysis is available."""
    from intel.ai_analysis import is_available
    return {"available": is_available()}


@router.get("/plays/open/tracked")
def plays_open_tracked():
    """Return all currently open (tracked, awaiting expiry) plays."""
    return {"plays": get_open_plays()}
