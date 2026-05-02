"""
Backtest router — /backtest/* endpoints with background-compute + file cache.
"""

import json
import os
import time
import threading
import logging
from typing import Optional

from fastapi import APIRouter, Query, Depends

from deps import require_admin
from backtest.engine import (
    run_full_backtest,
    backtest_layer_attribution,
    backtest_earnings_timing,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["backtest"])

# ── Cache ──────────────────────────────────────────────────────────────────────

CACHE_FILE = "/tmp/quaest_backtest_cache.json"
CACHE_TTL = 7200  # 2 hours

_lock = threading.Lock()
_computing = False


def _cache_fresh() -> Optional[dict]:
    import os
    try:
        if not os.path.exists(CACHE_FILE):
            return None
        if time.time() - os.path.getmtime(CACHE_FILE) > CACHE_TTL:
            return None
        with open(CACHE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _compute_and_cache(days: int, forward_period: int):
    global _computing
    try:
        result = {
            "computed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "days": days,
            "forward_period": forward_period,
            "score_vs_returns": run_full_backtest(days, forward_period),
            "layer_attribution": backtest_layer_attribution(days, forward_period),
            "earnings_timing": backtest_earnings_timing(days),
        }
        with open(CACHE_FILE, "w") as f:
            json.dump(result, f)
        logger.info("Backtest cache written")
    except Exception as e:
        logger.error(f"Backtest cache compute failed: {e}")
    finally:
        _computing = False


def start_compute(days: int = 60, forward_period: int = 14):
    global _computing
    with _lock:
        if _computing:
            return
        _computing = True
    t = threading.Thread(target=_compute_and_cache, args=(days, forward_period), daemon=True)
    t.start()


_COMPUTING_RESPONSE = {
    "status": "computing",
    "message": "Backtest is running in the background. Retry in 60-90 seconds.",
    "retry_after": 60,
}

# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/backtest")
def get_backtest(days: int = Query(60, ge=30, le=365), forward_period: int = Query(14, ge=7, le=90)):
    cached = _cache_fresh()
    if cached:
        return cached.get("score_vs_returns", cached)
    start_compute(days, forward_period)
    return _COMPUTING_RESPONSE


@router.get("/backtest/score-vs-returns")
def get_score_vs_returns(days: int = Query(60, ge=30, le=365), forward_period: int = Query(14, ge=7, le=90)):
    cached = _cache_fresh()
    if cached:
        return cached.get("score_vs_returns", {})
    start_compute(days, forward_period)
    return _COMPUTING_RESPONSE


@router.get("/backtest/layer-attribution")
def get_layer_attribution(days: int = Query(60, ge=30, le=365), forward_period: int = Query(14, ge=7, le=90)):
    cached = _cache_fresh()
    if cached:
        return cached.get("layer_attribution", {})
    start_compute(days, forward_period)
    return _COMPUTING_RESPONSE


@router.get("/backtest/earnings-timing")
def get_earnings_timing(days: int = Query(60, ge=30, le=365)):
    cached = _cache_fresh()
    if cached:
        return cached.get("earnings_timing", {})
    start_compute(days, 14)
    return _COMPUTING_RESPONSE


@router.post("/backtest/refresh")
def refresh_backtest(
    days: int = Query(60, ge=30, le=365),
    forward_period: int = Query(14, ge=7, le=90),
    admin: dict = Depends(require_admin),
):
    """Force-invalidate the backtest cache and recompute. Admin only."""
    import os
    try:
        os.remove(CACHE_FILE)
    except FileNotFoundError:
        pass
    start_compute(days, forward_period)
    return {"status": "computing", "message": "Cache cleared. Recomputing.", "retry_after": 60}
