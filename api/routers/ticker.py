"""
Ticker / universe router — read-only /tickers, /tickers/{sector}, /universe.

Extracted verbatim from main.py (SESSION-ROUTER-SPLIT). Behavior-preserving:
same routes, methods, request/response schemas, and status codes. Lowest-risk
group (read-only) — extracted first to prove the router pattern.
"""

from fastapi import APIRouter, HTTPException

from core.universe import (
    CYBER_UNIVERSE,
    get_universe_by_sector, get_sector_summary, get_all_tickers,
    ALL_CYBER_TICKERS, ALL_ENERGY_TICKERS, ALL_DEFENSE_TICKERS,
    ALL_BROAD_TICKERS,
)

# Full multi-sector universe (cyber + energy + defense + broad S&P500/Nasdaq100,
# deduplicated). Computed identically to main.py so /tickers and /universe return
# byte-identical payloads after extraction.
ALL_TICKERS = sorted(list(set(ALL_CYBER_TICKERS + ALL_ENERGY_TICKERS + ALL_DEFENSE_TICKERS + ALL_BROAD_TICKERS)))

router = APIRouter(tags=["ticker"])


@router.get("/tickers")
def get_tickers():
    return {"universe": CYBER_UNIVERSE, "all_tickers": ALL_TICKERS, "total": len(ALL_TICKERS)}


# ─── Universe Endpoints ───

@router.get("/universe")
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

@router.get("/tickers/{sector}")
def get_tickers_by_sector(sector: str):
    valid = ["cyber", "energy", "defense"]
    if sector not in valid:
        raise HTTPException(status_code=400, detail=f"Sector must be one of {valid}")
    tickers = get_all_tickers([sector])
    return {"sector": sector, "tickers": tickers, "total": len(tickers)}
