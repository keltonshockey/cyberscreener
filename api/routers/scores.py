"""
Scores router — /scores/* and /chart/* endpoints with in-memory cache.
"""

import time
from datetime import datetime, timedelta

from fastapi import APIRouter, Query

from db.models import get_db, get_score_history

router = APIRouter(tags=["scores"])

_latest_scores_cache = {"data": None, "ts": 0, "key": None}
_sparkline_cache = {"data": None, "ts": 0, "key": None}


@router.get("/prices/sparklines")
def get_sparklines(
    tickers: str = Query(..., description="Comma-separated tickers, e.g. NVDA,AMD"),
    points: int = Query(30, ge=5, le=60),
):
    """Recent close-price series per ticker — a real price path for grid sparklines
    (replaces the client-side ``[sma200, sma50, sma20, price]`` slope proxy).

    Lean by design: the last ``points`` closes only, batched for many tickers in one
    request, and cached 60s (prices refresh once per scan, not per request).
    """
    syms = []
    for raw in (tickers or "").split(","):
        s = raw.strip().upper()
        if s and s.replace(".", "").isalnum() and len(s) <= 10 and s not in syms:
            syms.append(s)
        if len(syms) >= 200:
            break
    if not syms:
        return {"points": points, "series": {}}

    now = time.time()
    key = f"{points}:{','.join(sorted(syms))}"
    if (
        _sparkline_cache["data"]
        and (now - _sparkline_cache["ts"]) < 60
        and _sparkline_cache["key"] == key
    ):
        return _sparkline_cache["data"]

    conn = get_db()
    placeholders = ",".join("?" * len(syms))
    # Pull the most-recent `points` closes per ticker via a windowed query, then
    # re-order ascending for plotting. ROW_NUMBER keeps it to one round-trip.
    rows = conn.execute(f"""
        SELECT ticker, date, close_price FROM (
            SELECT ticker, date, close_price,
                   ROW_NUMBER() OVER (PARTITION BY ticker ORDER BY date DESC) AS rn
            FROM prices
            WHERE ticker IN ({placeholders})
        ) WHERE rn <= ?
        ORDER BY ticker ASC, date ASC
    """, (*syms, points)).fetchall()
    conn.close()

    series = {}
    for r in rows:
        series.setdefault(r["ticker"], []).append(round(r["close_price"], 2))

    result = {"points": points, "series": series}
    _sparkline_cache["data"] = result
    _sparkline_cache["ts"] = now
    _sparkline_cache["key"] = key
    return result


@router.get("/scores/latest")
def get_latest_scores(limit: int = Query(100, ge=1, le=600)):
    """
    Return the most recent score for each ticker across all scans.
    Cached 30s — invalidated when scan_id changes (new scan completed).
    """
    now = time.time()
    conn = get_db()
    scan = conn.execute("SELECT id, timestamp FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    if not scan:
        conn.close()
        return {"message": "No scans found.", "results": []}

    cache_key = f"{scan['id']}:{limit}"
    if (
        _latest_scores_cache["data"]
        and (now - _latest_scores_cache["ts"]) < 30
        and _latest_scores_cache["key"] == cache_key
    ):
        conn.close()
        return _latest_scores_cache["data"]

    rows = conn.execute("""
        SELECT * FROM scores
        WHERE scan_id = (SELECT MAX(id) FROM scans)
        ORDER BY lt_score DESC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    result = {
        "scan_id": scan["id"],
        "scan_timestamp": scan["timestamp"],
        "results": [dict(r) for r in rows],
    }
    _latest_scores_cache["data"] = result
    _latest_scores_cache["ts"] = now
    _latest_scores_cache["key"] = cache_key
    return result


@router.get("/scores/{ticker}")
def get_ticker_scores(ticker: str, days: int = Query(90, ge=7, le=365)):
    history = get_score_history(ticker.upper(), days)
    if not history:
        return {"ticker": ticker.upper(), "history": [], "message": "No data found."}
    return {"ticker": ticker.upper(), "history": history, "data_points": len(history)}


@router.get("/chart/{ticker}")
def get_chart_data(ticker: str, days: int = Query(90, ge=30, le=365)):
    """Price history with computed SMA/RSI and detected signal overlays for charting."""
    t = ticker.upper()
    conn = get_db()

    fetch_days = max(days + 220, 365)
    cutoff_all = (datetime.now() - timedelta(days=fetch_days)).strftime("%Y-%m-%d")
    display_cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    rows = conn.execute(
        "SELECT date, close_price FROM prices WHERE ticker = ? AND date >= ? ORDER BY date ASC",
        (t, cutoff_all)
    ).fetchall()

    if not rows:
        conn.close()
        return {"ticker": t, "prices": [], "signals": []}

    dates = [r["date"] for r in rows]
    closes = [r["close_price"] for r in rows]
    n = len(closes)

    def sma_series(c, period):
        out = [None] * len(c)
        for i in range(period - 1, len(c)):
            out[i] = sum(c[i - period + 1:i + 1]) / period
        return out

    def rsi_series(c, period=14):
        out = [None] * len(c)
        if len(c) < period + 1:
            return out
        gains, losses = [], []
        for i in range(1, period + 1):
            d = c[i] - c[i - 1]
            gains.append(max(d, 0))
            losses.append(max(-d, 0))
        avg_g = sum(gains) / period
        avg_l = sum(losses) / period
        out[period] = 100.0 if avg_l == 0 else round(100 - 100 / (1 + avg_g / avg_l), 1)
        for i in range(period + 1, len(c)):
            d = c[i] - c[i - 1]
            avg_g = (avg_g * (period - 1) + max(d, 0)) / period
            avg_l = (avg_l * (period - 1) + max(-d, 0)) / period
            out[i] = 100.0 if avg_l == 0 else round(100 - 100 / (1 + avg_g / avg_l), 1)
        return out

    sma20 = sma_series(closes, 20)
    sma50 = sma_series(closes, 50)
    sma200 = sma_series(closes, 200)
    rsi_vals = rsi_series(closes)

    prices_out = []
    for i in range(n):
        if dates[i] >= display_cutoff:
            prices_out.append({
                "date": dates[i],
                "close": round(closes[i], 2),
                "sma20": round(sma20[i], 2) if sma20[i] is not None else None,
                "sma50": round(sma50[i], 2) if sma50[i] is not None else None,
                "sma200": round(sma200[i], 2) if sma200[i] is not None else None,
                "rsi": rsi_vals[i],
            })

    signals = []

    for i in range(1, n):
        if dates[i] < display_cutoff:
            continue
        pr, cr = rsi_vals[i - 1], rsi_vals[i]
        if pr is not None and cr is not None:
            if pr > 30 and cr <= 30:
                signals.append({"date": dates[i], "type": "rsi_oversold", "label": f"RSI {cr:.0f} OS"})
            elif pr < 70 and cr >= 70:
                signals.append({"date": dates[i], "type": "rsi_overbought", "label": f"RSI {cr:.0f} OB"})

    for i in range(1, n):
        if dates[i] < display_cutoff:
            continue
        ps20, ps50, cs20, cs50 = sma20[i - 1], sma50[i - 1], sma20[i], sma50[i]
        if all(x is not None for x in [ps20, ps50, cs20, cs50]):
            if ps20 < ps50 and cs20 >= cs50:
                signals.append({"date": dates[i], "type": "sma_cross_bull", "label": "20/50 ↑"})
            elif ps20 > ps50 and cs20 <= cs50:
                signals.append({"date": dates[i], "type": "sma_cross_bear", "label": "20/50 ↓"})

    try:
        insider_rows = conn.execute("""
            SELECT sc.timestamp, s.insider_buys_30d, s.insider_sells_30d
            FROM scores s JOIN scans sc ON s.scan_id = sc.id
            WHERE s.ticker = ? AND sc.timestamp >= ?
            ORDER BY sc.timestamp ASC
        """, (t, display_cutoff)).fetchall()
        prev_b, prev_s = 0, 0
        for row in insider_rows:
            d = row["timestamp"][:10]
            b = row["insider_buys_30d"] or 0
            s = row["insider_sells_30d"] or 0
            if b > prev_b:
                signals.append({"date": d, "type": "insider_buy", "label": "Insider Buy"})
            if s > prev_s:
                signals.append({"date": d, "type": "insider_sell", "label": "Insider Sell"})
            prev_b, prev_s = b, s
    except Exception:
        pass

    try:
        earn_rows = conn.execute(
            "SELECT earnings_date FROM earnings_dates WHERE ticker = ? ORDER BY earnings_date ASC",
            (t,)
        ).fetchall()
        for row in earn_rows:
            ed = row[0] if not isinstance(row, dict) else row["earnings_date"]
            if ed and ed >= display_cutoff:
                signals.append({"date": ed, "type": "earnings", "label": "Earnings"})
    except Exception:
        pass

    try:
        earn_scan_rows = conn.execute("""
            SELECT sc.timestamp FROM scores s
            JOIN scans sc ON s.scan_id = sc.id
            WHERE s.ticker = ? AND s.days_to_earnings IS NOT NULL
              AND s.days_to_earnings <= 2 AND sc.timestamp >= ?
            ORDER BY sc.timestamp ASC
        """, (t, display_cutoff)).fetchall()
        seen = set()
        for row in earn_scan_rows:
            d = row["timestamp"][:10]
            if d not in seen:
                seen.add(d)
                too_close = any(
                    s_["type"] == "earnings" and
                    abs((datetime.strptime(s_["date"], "%Y-%m-%d") - datetime.strptime(d, "%Y-%m-%d")).days) < 7
                    for s_ in signals
                )
                if not too_close:
                    signals.append({"date": d, "type": "earnings", "label": "Earnings ~"})
    except Exception:
        pass

    conn.close()
    signals.sort(key=lambda s: s["date"])
    return {"ticker": t, "prices": prices_out, "signals": signals}
