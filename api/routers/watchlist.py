"""
Valuation Watchlist router -- the monthly snapshot surface for the one
evidence-backed signal (lt_valuation, growth-adjusted EV/Revenue).

ADDITIVE + READ-ONLY. Every request opens cyberscreener.db through
db.ro.connect_ro (file:...?mode=ro + PRAGMA query_only), so this router is
mechanically incapable of writing. It performs no inserts anywhere -- the
snapshot is computed at read time from the scans/scores tables that already
exist; nothing new is persisted.

Snapshot rule (deterministic): use the LAST completed scan whose timestamp
falls on or before the last calendar day (UTC) of the PREVIOUS month relative
to "now". "Completed" means the scans row exists and holds at least one
scores row (models.save_scan rolls back empty scans, but the guard costs one
EXISTS). "Now" is UTC today, overridable via ?asof=YYYY-MM-DD so tests and
reproductions can pin it. Because the rule only looks strictly before the
first day of the as-of month, scans that land mid-current-month can never
change the response: the watchlist holds still for a month at a time, which
is the product point -- the signal's horizon is 6-12 months.

Rows with NULL lt_valuation are excluded (no fabricated ranks); ties break by
ticker for a stable order. Plain SQL, no pandas.
"""

import os
import re
import sqlite3
from datetime import date, datetime, timezone

from fastapi import APIRouter, HTTPException, Query

from db.ro import connect_ro
from core.watchlist_copy import copy_payload

router = APIRouter(tags=["watchlist"])

DEFAULT_DB = "/app/data/cyberscreener.db"

_ASOF_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _db_path() -> str:
    # Read at request time (not import time) so tests can rebind the DB via
    # the same env var db.models honors.
    return os.environ.get("CYBERSCREENER_DB", DEFAULT_DB)


def _open_ro() -> sqlite3.Connection:
    """The router's single door to the DB -- strictly read-only."""
    return connect_ro(_db_path())


def _parse_asof(asof: str) -> date:
    if not _ASOF_RE.match(asof):
        raise HTTPException(status_code=422, detail="asof must be YYYY-MM-DD")
    try:
        return date.fromisoformat(asof)
    except ValueError:
        raise HTTPException(status_code=422, detail="asof is not a real calendar date")


def _month_start_str(d: date) -> str:
    """First day of d's month, as the text boundary the scans query compares
    against. scans.timestamp is 'YYYY-MM-DD HH:MM:SS', so lexicographic
    `timestamp < 'YYYY-MM-01'` is exactly 'on or before the last calendar day
    of the previous month'."""
    return f"{d.year:04d}-{d.month:02d}-01"


@router.get("/watchlist/valuation")
def valuation_watchlist(
    asof: str | None = Query(
        None,
        description="YYYY-MM-DD override of 'now' (UTC) for reproducibility/testing.",
    ),
    limit: int = Query(25, ge=1, le=200),
):
    now_d = _parse_asof(asof) if asof is not None else datetime.now(timezone.utc).date()
    boundary = _month_start_str(now_d)

    try:
        conn = _open_ro()
    except sqlite3.OperationalError:
        # mode=ro never creates a file; a missing DB is a service condition,
        # not a 500.
        raise HTTPException(status_code=503, detail="score database unavailable")

    try:
        scan = conn.execute(
            """
            SELECT s.id, s.timestamp
            FROM scans s
            WHERE s.timestamp < ?
              AND EXISTS (SELECT 1 FROM scores sc WHERE sc.scan_id = s.id)
            ORDER BY s.timestamp DESC, s.id DESC
            LIMIT 1
            """,
            (boundary,),
        ).fetchone()
        if scan is None:
            raise HTTPException(
                status_code=404,
                detail=(
                    "no completed scan on or before the last day of the month "
                    f"preceding {now_d.isoformat()}"
                ),
            )

        # sector arrived by migration; tolerate a pre-migration DB.
        cols = {r[1] for r in conn.execute("PRAGMA table_info(scores)")}
        sector_expr = "sector" if "sector" in cols else "NULL AS sector"
        rows = conn.execute(
            f"""
            SELECT ticker, lt_valuation, {sector_expr}, price
            FROM scores
            WHERE scan_id = ? AND lt_valuation IS NOT NULL
            ORDER BY lt_valuation DESC, ticker ASC
            LIMIT ?
            """,
            (scan["id"], limit),
        ).fetchall()
    finally:
        conn.close()

    entries = [
        {
            "rank": i + 1,
            "ticker": r["ticker"],
            "lt_valuation": r["lt_valuation"],
            "sector": r["sector"],
            "price": r["price"],
        }
        for i, r in enumerate(rows)
    ]

    ts = scan["timestamp"]
    return {
        "as_of_scan_id": scan["id"],
        "as_of_utc": ts,
        # The month the snapshot's data actually comes from (normally the
        # previous calendar month; older if that month had no scans -- showing
        # the scan's own month is the honest label either way).
        "snapshot_month": ts[:7],
        "entries": entries,
        "copy": copy_payload(),
    }
