"""
Narrative router — read-only per-ticker story panel.

ADDITIVE + READ-ONLY relative to the live system. The only write this router
performs is the lazy `record_view` into the SEPARATE `narratives.db` (so the
mill-side pipeline learns what is being looked at). It never imports or touches
`cyberscreener.db` / `db.models`, and it cannot influence any score.

Contract:
  GET /narrative/{ticker}
    * row exists -> 200 with the story payload + a computed `stale` flag.
    * no row    -> 202 {"status": "generating", ...} and the view is queued.
  The view is recorded on EVERY call so the lazy queue stays warm.
"""

from datetime import datetime, timedelta

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from db.narratives import (
    get_narrative, record_view,
    ST_TTL_HOURS, LT_TTL_DAYS,
)

router = APIRouter(tags=["narrative"])


def _is_stale(generated_at: str | None, max_age: timedelta) -> bool:
    """A section is stale if it was never generated or is older than its TTL."""
    if not generated_at:
        return True
    try:
        ts = datetime.fromisoformat(generated_at)
    except (ValueError, TypeError):
        return True
    return (datetime.utcnow() - ts) > max_age


@router.get("/narrative/{ticker}")
def get_ticker_narrative(ticker: str):
    t = (ticker or "").upper()

    # Always log the view so mill's lazy queue learns what is being looked at.
    record_view(t)

    row = get_narrative(t)
    if not row:
        # Nothing generated yet — tell the UI to show a quiet placeholder and
        # poll again on next load. The view we just recorded will get picked up.
        return JSONResponse(status_code=202, content={"status": "generating", "ticker": t})

    st_stale = _is_stale(row.get("st_generated_at"), timedelta(hours=ST_TTL_HOURS))
    lt_stale = _is_stale(row.get("lt_generated_at"), timedelta(days=LT_TTL_DAYS))

    return {
        "ticker": t,
        "lt_story": row.get("lt_story"),
        "st_story": row.get("st_story"),
        "sources": row.get("sources") or [],
        "confidence": row.get("confidence") or "ok",
        "lt_generated_at": row.get("lt_generated_at"),
        "st_generated_at": row.get("st_generated_at"),
        "stale": bool(st_stale or lt_stale),
    }
