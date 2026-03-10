"""
Earnings Calendar Intel Layer — DB-backed earnings dates.
"""
import os
import logging
import requests
from datetime import datetime, date
from typing import Optional

logger = logging.getLogger(__name__)
_FMP_KEY = os.environ.get("EARNINGS_API_KEY", "")
_FMP_URL = "https://financialmodelingprep.com/api/v3/historical/earning_calendar/{ticker}?limit=4&apikey={key}"

def get_db_earnings_date(ticker):
    try:
        from db.models import get_db
        conn = get_db()
        today = datetime.today().date().isoformat()
        row = conn.execute(
            "SELECT earnings_date, source FROM earnings_dates WHERE ticker = ? AND earnings_date >= ? ORDER BY earnings_date ASC LIMIT 1",
            (ticker.upper(), today)
        ).fetchone()
        conn.close()
        if row:
            d = datetime.strptime(row["earnings_date"], "%Y-%m-%d").date()
            return d, row["source"]
    except Exception as e:
        logger.debug(f"DB earnings lookup failed for {ticker}: {e}")
    return None

def save_earnings_date(ticker, earnings_date, source="manual", report_time="unknown"):
    try:
        from db.models import get_db
        conn = get_db()
        conn.execute(
            """INSERT INTO earnings_dates (ticker, earnings_date, report_time, source, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(ticker) DO UPDATE SET
                 earnings_date=excluded.earnings_date,
                 report_time=excluded.report_time,
                 source=excluded.source,
                 updated_at=excluded.updated_at""",
            (ticker.upper(), earnings_date.isoformat(), report_time, source,
             datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        logger.warning(f"Failed to save earnings date for {ticker}: {e}")
        return False

def seed_from_payload(payload):
    saved, failed, skipped = [], [], []
    for ticker, date_str in payload.items():
        try:
            d = datetime.strptime(date_str[:10], "%Y-%m-%d").date()
            if d < datetime.today().date():
                skipped.append(f"{ticker}: past date")
                continue
            if save_earnings_date(ticker.upper(), d, source="api_seed"):
                saved.append(f"{ticker}: {d}")
            else:
                failed.append(ticker)
        except ValueError:
            failed.append(f"{ticker}: invalid date '{date_str}'")
    return {"saved": saved, "failed": failed, "skipped": skipped}

def get_all_upcoming_dates():
    try:
        from db.models import get_db
        conn = get_db()
        today = datetime.today().date().isoformat()
        rows = conn.execute(
            "SELECT ticker, earnings_date, report_time, source, updated_at FROM earnings_dates WHERE earnings_date >= ? ORDER BY earnings_date ASC",
            (today,)
        ).fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception as e:
        logger.warning(f"Failed to fetch upcoming dates: {e}")
        return []

def fetch_from_fmp(ticker):
    if not _FMP_KEY:
        return None
    try:
        url = _FMP_URL.format(ticker=ticker, key=_FMP_KEY)
        resp = requests.get(url, timeout=10)
        if resp.status_code != 200:
            return None
        data = resp.json()
        if not data or not isinstance(data, list):
            return None
        today = datetime.today().date()
        for item in data:
            raw = item.get("date", "")
            if not raw:
                continue
            try:
                d = datetime.strptime(raw[:10], "%Y-%m-%d").date()
                if d >= today:
                    return d
            except ValueError:
                continue
    except Exception as e:
        logger.debug(f"FMP fetch failed for {ticker}: {e}")
    return None

def get_earnings_date_for_ticker(ticker, yfinance_dte=None):
    today = datetime.today().date()
    db_result = get_db_earnings_date(ticker)
    if db_result:
        d, source = db_result
        dte = (d - today).days
        if 0 < dte < 365:
            return dte, f"db:{source}({d})"
    if yfinance_dte is not None:
        dte = int(yfinance_dte)
        if 0 < dte < 365:
            return dte, "yfinance"
    fmp_date = fetch_from_fmp(ticker)
    if fmp_date:
        dte = (fmp_date - today).days
        if 0 < dte < 365:
            save_earnings_date(ticker, fmp_date, source="fmp_live")
            return dte, f"fmp_live({fmp_date})"
    return None, "not_found"
