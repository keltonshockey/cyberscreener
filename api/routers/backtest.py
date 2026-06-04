"""
Backtest router — /backtest/* endpoints with background-compute + file cache.
"""

import json
import os
import time
import threading
import concurrent.futures
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
    try:
        if not os.path.exists(CACHE_FILE):
            return None
        if time.time() - os.path.getmtime(CACHE_FILE) > CACHE_TTL:
            return None
        with open(CACHE_FILE) as f:
            data = json.load(f)
        # Treat error sentinels as not-fresh so callers can check status field
        if data.get("status") == "error":
            return data
        return data
    except Exception:
        return None


_PHASE_TIMEOUT = 90  # seconds per backtest phase

def _run_phase(fn, *args):
    """Run fn(*args) with a hard _PHASE_TIMEOUT second limit. Returns None on timeout/error."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        future = ex.submit(fn, *args)
        try:
            return future.result(timeout=_PHASE_TIMEOUT)
        except concurrent.futures.TimeoutError:
            logger.error(f"Backtest phase {fn.__name__} timed out after {_PHASE_TIMEOUT}s")
            return None
        except Exception as e:
            logger.error(f"Backtest phase {fn.__name__} error: {e}")
            return None

def _compute_and_cache(days: int, forward_period: int):
    global _computing
    tmp = CACHE_FILE + ".tmp"
    start = time.time()
    try:
        logger.info(f"Backtest compute start: days={days} forward={forward_period}")
        svr = _run_phase(run_full_backtest, days, forward_period)
        logger.info(f"score_vs_returns: {'ok' if svr else 'timeout'} ({time.time()-start:.1f}s)")
        la  = _run_phase(backtest_layer_attribution, days, forward_period)
        logger.info(f"layer_attribution: {'ok' if la else 'timeout'} ({time.time()-start:.1f}s)")
        et  = _run_phase(backtest_earnings_timing, days)
        logger.info(f"earnings_timing: {'ok' if et else 'timeout'} ({time.time()-start:.1f}s)")

        timed_out = svr is None or la is None or et is None
        result = {
            "computed_at": time.strftime("%Y-%m-%d %H:%M:%S"),
            "days": days,
            "forward_period": forward_period,
            "compute_seconds": round(time.time() - start, 1),
            "partial": timed_out,
            "score_vs_returns": svr or {"status": "timeout", "message": "Phase timed out. Try days=7."},
            "layer_attribution": la or {"status": "timeout", "message": "Phase timed out."},
            "earnings_timing":   et or {"status": "timeout", "message": "Phase timed out."},
        }
        if timed_out:
            result["status"] = "partial"
            result["message"] = "Backtest timed out. Try days=7 for faster results."
        with open(tmp, "w") as f:
            json.dump(result, f)
        os.replace(tmp, CACHE_FILE)
        logger.info(f"Backtest cache written in {result['compute_seconds']}s (partial={timed_out})")
    except Exception as e:
        logger.error(f"Backtest outer error: {e}")
        try:
            with open(tmp, "w") as f:
                json.dump({"status": "error", "message": str(e), "computed_at": time.strftime("%Y-%m-%d %H:%M:%S")}, f)
            os.replace(tmp, CACHE_FILE)
        except Exception:
            pass
    finally:
        _computing = False
        logger.info("Backtest thread done, _computing=False")



def start_compute(days: int = 60, forward_period: int = 30):
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
        if cached.get("status") == "error":
            return {"status": "error", "message": cached.get("message", "Backtest computation failed.")}
        if cached.get("status") == "partial":
            return {"status": "timeout", "partial": True,
                    "message": cached.get("message", "Backtest timed out. Try days=7."),
                    "data": cached.get("score_vs_returns", {})}
        return cached.get("score_vs_returns", cached)
    start_compute(days, forward_period)
    return _COMPUTING_RESPONSE


@router.get("/backtest/score-vs-returns")
def get_score_vs_returns(days: int = Query(60, ge=30, le=365), forward_period: int = Query(14, ge=7, le=90)):
    cached = _cache_fresh()
    if cached:
        if cached.get("status") == "error":
            return {"status": "error", "message": cached.get("message")}
        return cached.get("score_vs_returns", {})
    start_compute(days, forward_period)
    return _COMPUTING_RESPONSE


@router.get("/backtest/layer-attribution")
def get_layer_attribution(days: int = Query(60, ge=30, le=365), forward_period: int = Query(14, ge=7, le=90)):
    cached = _cache_fresh()
    if cached:
        if cached.get("status") == "error":
            return {"status": "error", "message": cached.get("message")}
        return cached.get("layer_attribution", {})
    start_compute(days, forward_period)
    return _COMPUTING_RESPONSE


@router.get("/backtest/earnings-timing")
def get_earnings_timing(days: int = Query(60, ge=30, le=365)):
    cached = _cache_fresh()
    if cached:
        if cached.get("status") == "error":
            return {"status": "error", "message": cached.get("message")}
        return cached.get("earnings_timing", {})
    start_compute(days, 30)
    return _COMPUTING_RESPONSE


@router.get("/backtest/status")
def get_backtest_status():
    """Lightweight status check — computing / ready / error."""
    if _computing:
        return {"status": "computing"}
    cached = _cache_fresh()
    if not cached:
        return {"status": "computing"}
    if cached.get("status") == "error":
        return {"status": "error", "message": cached.get("message")}
    return {"status": "ready", "computed_at": cached.get("computed_at")}


@router.post("/backtest/refresh")
def refresh_backtest(
    days: int = Query(60, ge=30, le=365),
    forward_period: int = Query(14, ge=7, le=90),
    admin: dict = Depends(require_admin),
):
    """Force-invalidate the backtest cache and recompute. Admin only."""
    try:
        os.remove(CACHE_FILE)
    except FileNotFoundError:
        pass
    start_compute(days, forward_period)
    return {"status": "computing", "message": "Cache cleared. Recomputing.", "retry_after": 60}
