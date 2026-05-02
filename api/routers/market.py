"""
Market router — /stats, /market/indices, /intel/*, /killer-plays,
/inverse-plays, /signals/* endpoints.
"""

import time
import logging
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor as _TPE

import requests as _requests
import xml.etree.ElementTree as _ET
import yfinance as yf

from fastapi import APIRouter, Query, HTTPException

from db.models import get_db, get_weights
from core.universe import (
    ALL_CYBER_TICKERS, ALL_ENERGY_TICKERS, ALL_DEFENSE_TICKERS, ALL_BROAD_TICKERS,
)

logger = logging.getLogger(__name__)
router = APIRouter(tags=["market"])

_ALL_TICKER_SET = set(ALL_CYBER_TICKERS + ALL_ENERGY_TICKERS + ALL_DEFENSE_TICKERS + ALL_BROAD_TICKERS)

# ── Stats ──────────────────────────────────────────────────────────────────────

_stats_cache = {"data": None, "ts": 0}


@router.get("/stats")
def get_stats():
    """Dashboard stats — cached 60s."""
    now = time.time()
    if _stats_cache["data"] and (now - _stats_cache["ts"]) < 60:
        return _stats_cache["data"]

    conn = get_db()
    stats = {}
    stats["total_scans"] = conn.execute("SELECT COUNT(*) FROM scans").fetchone()[0]
    stats["total_score_records"] = conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    try:
        stats["total_signals"] = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    except Exception:
        stats["total_signals"] = 0
    stats["total_price_snapshots"] = conn.execute("SELECT COUNT(*) FROM prices").fetchone()[0]
    stats["unique_tickers_tracked"] = conn.execute("SELECT COUNT(DISTINCT ticker) FROM scores").fetchone()[0]
    stats["first_scan"] = conn.execute("SELECT MIN(timestamp) FROM scans").fetchone()[0]
    stats["last_scan"] = conn.execute("SELECT MAX(timestamp) FROM scans").fetchone()[0]
    stats["scoring_version"] = "v2"
    stats["active_weights"] = get_weights()

    latest = conn.execute("SELECT id FROM scans ORDER BY id DESC LIMIT 1").fetchone()
    if latest:
        top_lt = conn.execute(
            "SELECT ticker, lt_score, opt_score FROM scores WHERE scan_id = ? ORDER BY lt_score DESC LIMIT 5",
            (latest[0],)
        ).fetchall()
        stats["top_lt_scores"] = [{"ticker": r[0], "lt_score": r[1], "opt_score": r[2]} for r in top_lt]
        top_opt = conn.execute(
            "SELECT ticker, opt_score, lt_score FROM scores WHERE scan_id = ? ORDER BY opt_score DESC LIMIT 5",
            (latest[0],)
        ).fetchall()
        stats["top_opt_scores"] = [{"ticker": r[0], "opt_score": r[1], "lt_score": r[2]} for r in top_opt]

    conn.close()
    _stats_cache["data"] = stats
    _stats_cache["ts"] = now
    return stats


# ── Market Indices ─────────────────────────────────────────────────────────────

INDICES = [
    ("^GSPC",    "S&P 500",   "NYSE",    "🇺🇸"),
    ("^IXIC",    "NASDAQ",    "NASDAQ",  "🇺🇸"),
    ("^DJI",     "Dow Jones", "NYSE",    "🇺🇸"),
    ("^GDAXI",   "DAX",       "XETRA",   "🇩🇪"),
    ("^FTSE",    "FTSE 100",  "LSE",     "🇬🇧"),
    ("^N225",    "Nikkei",    "TSE",     "🇯🇵"),
    ("^HSI",     "Hang Seng", "HKEX",    "🇭🇰"),
    ("^FCHI",    "CAC 40",    "EURONEXT","🇫🇷"),
    ("^STOXX50E","STOXX 50",  "EURONEXT","🇪🇺"),
]

EXCHANGE_HOURS = {
    "NYSE":     (14, 30, 21,  0),
    "NASDAQ":   (14, 30, 21,  0),
    "LSE":      ( 8,  0, 16, 30),
    "XETRA":    ( 8,  0, 16, 30),
    "TSE":      ( 0,  0,  6,  0),
    "HKEX":     ( 1, 30,  8,  0),
    "EURONEXT": ( 8,  0, 16, 30),
}

_market_cache = {"data": None, "ts": 0}


def _exchange_is_open(exchange: str) -> bool:
    now = datetime.utcnow()
    if now.weekday() >= 5:
        return False
    hrs = EXCHANGE_HOURS.get(exchange)
    if not hrs:
        return False
    oh, om, ch, cm = hrs
    open_mins  = oh * 60 + om
    close_mins = ch * 60 + cm
    now_mins   = now.hour * 60 + now.minute
    return open_mins <= now_mins < close_mins


@router.get("/market/indices")
def market_indices():
    if _market_cache["data"] and (time.time() - _market_cache["ts"]) < 300:
        return _market_cache["data"]

    results = []
    for symbol, name, exchange, flag in INDICES:
        try:
            t = yf.Ticker(symbol)
            fi = t.fast_info
            price = getattr(fi, "last_price", None) or getattr(fi, "regular_market_price", None)
            prev_close = getattr(fi, "previous_close", None) or getattr(fi, "regular_market_previous_close", None)
            if price is None:
                hist = t.history(period="2d")
                if not hist.empty:
                    price = float(hist["Close"].iloc[-1])
                    if len(hist) >= 2:
                        prev_close = float(hist["Close"].iloc[-2])
            price      = float(price) if price is not None else None
            prev_close = float(prev_close) if prev_close is not None else price
            change_pct = ((price - prev_close) / prev_close * 100) if (price and prev_close) else 0.0
            results.append({
                "symbol":     symbol,
                "name":       name,
                "flag":       flag,
                "exchange":   exchange,
                "price":      round(price, 2) if price is not None else None,
                "change_pct": round(change_pct, 2),
                "is_open":    _exchange_is_open(exchange),
            })
        except Exception as e:
            results.append({
                "symbol":     symbol,
                "name":       name,
                "flag":       flag,
                "exchange":   exchange,
                "price":      None,
                "change_pct": None,
                "is_open":    _exchange_is_open(exchange),
                "error":      str(e),
            })

    _market_cache["data"] = results
    _market_cache["ts"]   = time.time()
    return results


# ── Intel: Cyber News + Outages ────────────────────────────────────────────────

NEWS_SOURCES = [
    ("Bleeping Computer", "https://www.bleepingcomputer.com/feed/"),
    ("Krebs on Security", "https://krebsonsecurity.com/feed/"),
    ("Dark Reading",      "https://www.darkreading.com/rss.xml"),
]

NEWS_KEYWORDS = [
    "breach", "ransomware", "hack", "exploit", "zero-day", "vulnerability",
    "attack", "phishing", "malware", "outage", "leak", "credential",
]

STATUS_PAGES = {
    "CRWD": ("CrowdStrike",     "https://status.crowdstrike.com/api/v2/summary.json"),
    "NET":  ("Cloudflare",      "https://www.cloudflarestatus.com/api/v2/summary.json"),
    "OKTA": ("Okta",            "https://status.okta.com/api/v2/summary.json"),
    "DDOG": ("Datadog",         "https://status.datadoghq.com/api/v2/summary.json"),
    "PANW": ("Palo Alto",       "https://status.paloaltonetworks.com/api/v2/summary.json"),
    "ZS":   ("Zscaler",         "https://trust.zscaler.com/api/v2/summary.json"),
    "S":    ("SentinelOne",     "https://status.sentinelone.com/api/v2/summary.json"),
    "MSFT": ("Microsoft Azure", "https://azure.status.microsoft.com/en-us/status"),
    "GOOGL":("Google Cloud",    "https://status.cloud.google.com/"),
}

_news_cache   = {"data": None, "ts": 0}
_outage_cache = {"data": None, "ts": 0}


def _fetch_rss(source_name: str, url: str) -> list:
    items = []
    try:
        resp = _requests.get(url, timeout=8, headers={"User-Agent": "CyberScreener/1.0"})
        root = _ET.fromstring(resp.content)
        channel = root.find("channel") or root
        for item in channel.findall("item")[:20]:
            title    = (item.findtext("title") or "").strip()
            desc     = (item.findtext("description") or "").strip()
            link     = (item.findtext("link") or "").strip()
            pub      = (item.findtext("pubDate") or "").strip()
            combined = (title + " " + desc).lower()
            tags     = [kw for kw in NEWS_KEYWORDS if kw in combined]
            mentions = [t for t in _ALL_TICKER_SET if t.lower() in combined.split()]
            items.append({
                "title":           title,
                "summary":         desc[:200],
                "link":            link,
                "published":       pub,
                "source":          source_name,
                "tags":            tags,
                "ticker_mentions": mentions,
            })
    except Exception:
        pass
    return items


@router.get("/intel/news")
def intel_news():
    if _news_cache["data"] and (time.time() - _news_cache["ts"]) < 1800:
        return _news_cache["data"]

    all_items = []
    with _TPE(max_workers=3) as ex:
        futures = {ex.submit(_fetch_rss, name, url): name for name, url in NEWS_SOURCES}
        for f in futures:
            all_items.extend(f.result())

    def _parse_date(item):
        try:
            from email.utils import parsedate_to_datetime
            return parsedate_to_datetime(item["published"])
        except Exception:
            return datetime.min

    all_items.sort(key=_parse_date, reverse=True)

    result = {"items": all_items[:30], "fetched_at": datetime.utcnow().isoformat()}
    _news_cache["data"] = result
    _news_cache["ts"]   = time.time()
    return result


def _check_statuspage(ticker: str, name: str, url: str) -> dict:
    base = {
        "ticker":              ticker,
        "name":                name,
        "url":                 url,
        "status":              "unknown",
        "indicator":           "none",
        "components_affected": [],
        "checked_at":          datetime.utcnow().isoformat(),
    }
    try:
        if url.endswith(".json"):
            resp = _requests.get(url, timeout=5)
            data = resp.json()
            indicator = data.get("status", {}).get("indicator", "none")
            base["indicator"] = indicator
            base["status"]    = (
                "operational" if indicator == "none" else
                "outage"      if indicator in ("major", "critical") else
                "degraded"
            )
            base["components_affected"] = [
                c["name"] for c in data.get("components", [])
                if c.get("status", "operational") != "operational"
            ]
        else:
            resp = _requests.get(url, timeout=5)
            base["indicator"] = "none" if resp.status_code < 400 else "major"
            base["status"]    = "operational" if resp.status_code < 400 else "outage"
    except Exception as e:
        base["status"]    = "unknown"
        base["indicator"] = "unknown"
        base["error"]     = str(e)
    return base


@router.get("/intel/outages")
def intel_outages():
    if _outage_cache["data"] and (time.time() - _outage_cache["ts"]) < 300:
        return _outage_cache["data"]

    results = []
    with _TPE(max_workers=6) as ex:
        futures = {
            ex.submit(_check_statuspage, ticker, name, url): ticker
            for ticker, (name, url) in STATUS_PAGES.items()
        }
        for f in futures:
            results.append(f.result())

    results.sort(key=lambda x: x["ticker"])
    _outage_cache["data"] = results
    _outage_cache["ts"]   = time.time()
    return results


# ── Killer Plays ───────────────────────────────────────────────────────────────

@router.get("/killer-plays")
def get_killer_plays(limit: int = Query(8, ge=1, le=15)):
    """
    Return the highest-conviction plays from the latest scan.
    """
    conn = get_db()

    pct_row = conn.execute("""
        SELECT (s.opt_score * 0.6 + s.lt_score * 0.4) AS combined FROM scores s
        INNER JOIN (
            SELECT ticker, MAX(scan_id) AS max_scan_id FROM scores GROUP BY ticker
        ) latest ON s.ticker = latest.ticker AND s.scan_id = latest.max_scan_id
        ORDER BY combined DESC
        LIMIT 1 OFFSET (
            SELECT MAX(1, CAST(COUNT(*)*0.3 AS INTEGER))
            FROM scores s2
            INNER JOIN (
                SELECT ticker, MAX(scan_id) AS max_scan_id FROM scores GROUP BY ticker
            ) latest2 ON s2.ticker = latest2.ticker AND s2.scan_id = latest2.max_scan_id
        )
    """).fetchone()
    combined_floor = max(35.0, float(pct_row[0]) if pct_row else 35.0)

    rows = conn.execute("""
        SELECT s.ticker, s.price, s.opt_score, s.lt_score, s.rsi, s.days_to_earnings,
               s.threat_score, s.outage_status, s.breach_victim, s.demand_signal,
               s.bb_width, s.vol_ratio, s.sector, s.pct_from_52w_high, s.beta,
               s.iv_30d, s.horizon, s.recommended_expiry, s.iv_rank
        FROM scores s
        INNER JOIN (
            SELECT ticker, MAX(scan_id) AS max_scan_id
            FROM scores GROUP BY ticker
        ) latest ON s.ticker = latest.ticker AND s.scan_id = latest.max_scan_id
        WHERE (s.opt_score * 0.6 + s.lt_score * 0.4) >= ?
          AND (s.opt_score >= 45 OR s.lt_score >= 55)
          AND (s.threat_score IS NULL OR s.threat_score >= 70)
          AND (s.outage_status IS NULL OR s.outage_status NOT IN ('outage'))
          AND (s.breach_victim IS NULL OR s.breach_victim = 0)
        ORDER BY (s.opt_score * 0.6 + s.lt_score * 0.4) DESC
        LIMIT ?
    """, (combined_floor, limit * 2)).fetchall()
    conn.close()

    results = []
    for r in rows:
        row = dict(r)
        rsi = row.get("rsi") or 50
        dte = row.get("days_to_earnings")
        opt = row.get("opt_score") or 0
        lt  = row.get("lt_score") or 0

        has_catalyst   = (dte is not None and 1 <= dte <= 30) or rsi < 35 or rsi > 65 or (row.get("bb_width") and row["bb_width"] < 12)
        has_strong_score = opt >= 50 or lt >= 60
        if not has_catalyst and not has_strong_score:
            continue

        if rsi > 65:
            row["direction"] = "bearish"
            row["direction_label"] = "📉 Bearish"
        elif rsi < 38:
            row["direction"] = "bullish"
            row["direction_label"] = "📈 Bullish"
        else:
            row["direction"] = "neutral"
            row["direction_label"] = "↔ Neutral"

        if dte is not None and 1 <= dte <= 14:
            row["catalyst"] = f"⚡ Earnings {dte}d"
        elif dte is not None and 14 < dte <= 30:
            row["catalyst"] = f"📅 Earnings {dte}d"
        elif rsi < 30:
            row["catalyst"] = "📉 Oversold"
        elif rsi > 70:
            row["catalyst"] = "📈 Overbought"
        elif row.get("demand_signal"):
            row["catalyst"] = "🌋 Demand Signal"
        elif row.get("bb_width") and row["bb_width"] < 12:
            row["catalyst"] = "⟨⟩ BB Squeeze"
        else:
            row["catalyst"] = "📊 Technical"

        row["combined_score"] = round(opt * 0.6 + lt * 0.4, 1)
        row["conviction"] = "HIGH" if row["combined_score"] >= 55 else "SOLID" if row["combined_score"] >= 45 else "WATCH"

        results.append(row)
        if len(results) >= limit:
            break

    return {
        "plays": results,
        "total": len(results),
        "threshold_used": combined_floor,
        "timestamp": datetime.now().isoformat(),
    }


# ── Inverse Plays ──────────────────────────────────────────────────────────────

@router.get("/inverse-plays")
def get_inverse_plays(limit: int = Query(8, ge=1, le=15)):
    """
    Contrarian strategy: lowest-scored tickers from the latest scan.
    """
    conn = get_db()
    rows = conn.execute("""
        SELECT s.ticker, s.price, s.opt_score, s.lt_score, s.rsi,
               s.days_to_earnings, s.threat_score, s.outage_status,
               s.breach_victim, s.demand_signal, s.sector
        FROM scores s
        INNER JOIN (
            SELECT ticker, MAX(scan_id) AS max_scan_id FROM scores GROUP BY ticker
        ) latest ON s.ticker = latest.ticker AND s.scan_id = latest.max_scan_id
        WHERE s.lt_score IS NOT NULL AND s.opt_score IS NOT NULL
        ORDER BY (s.opt_score * 0.6 + s.lt_score * 0.4) ASC
        LIMIT ?
    """, (limit,)).fetchall()
    conn.close()

    results = []
    for r in rows:
        row = dict(r)
        row["combined_score"] = round((row.get("opt_score") or 0) * 0.6 + (row.get("lt_score") or 0) * 0.4, 1)
        dte = row.get("days_to_earnings")
        rsi = row.get("rsi") or 50
        row["inverse_reason"] = (
            "Earnings catalyst upcoming" if dte and 5 <= dte <= 30
            else "Technically oversold" if rsi < 35
            else "Lowest conviction in universe"
        )
        results.append(row)

    lt_corr = None
    q1_return = None
    q1_win_rate = None
    is_inverted = False
    try:
        from backtest.engine import backtest_score_vs_returns
        bt = backtest_score_vs_returns(days=180, forward_period=30)
        lt_a = bt.get("lt_analysis", {})
        lt_corr = lt_a.get("correlation")
        is_inverted = lt_corr is not None and lt_corr < -0.05
        q1 = (lt_a.get("quintiles") or {}).get("Q1", {})
        q1_return = q1.get("avg_return")
        q1_win_rate = q1.get("win_rate")
    except Exception:
        pass

    return {
        "plays": results,
        "total": len(results),
        "strategy": "contrarian",
        "lt_correlation": lt_corr,
        "is_inverted": is_inverted,
        "q1_avg_return": q1_return,
        "q1_win_rate": q1_win_rate,
        "interpretation": (
            "⚠️ Model is inversely correlated — these low-score tickers historically outperformed."
            if is_inverted
            else "Model is not currently inverted. Contrarian mode is precautionary."
        ),
        "timestamp": datetime.now().isoformat(),
    }


# ── Signals ────────────────────────────────────────────────────────────────────

@router.get("/signals/{ticker}/recent")
def get_recent_signals(ticker: str, limit: int = Query(40, ge=5, le=100)):
    """Return recent scoring signals for a ticker."""
    t = ticker.upper()
    if not t.replace(".", "").isalnum() or len(t) > 10:
        raise HTTPException(status_code=400, detail="Invalid ticker")
    conn = get_db()
    rows = conn.execute("""
        SELECT sg.signal_text, sg.impact, sc.timestamp AS scan_ts
        FROM signals sg
        JOIN scans sc ON sg.scan_id = sc.id
        WHERE sg.ticker = ?
        ORDER BY sg.id DESC LIMIT ?
    """, (t, limit)).fetchall()
    conn.close()
    return {"ticker": t, "signals": [dict(r) for r in rows], "total": len(rows)}


@router.get("/signals/momentum")
def get_momentum_signals(limit: int = Query(20, ge=5, le=100)):
    """Return recent score momentum events (≥8pt jump between consecutive scans)."""
    conn = get_db()
    rows = conn.execute("""
        SELECT sg.ticker, sg.signal_text, sg.impact, sc.timestamp AS scan_ts, sg.scan_id
        FROM signals sg
        JOIN scans sc ON sg.scan_id = sc.id
        WHERE sg.signal_type = 'momentum'
        ORDER BY sg.id DESC LIMIT ?
    """, (limit,)).fetchall()
    conn.close()
    return {"events": [dict(r) for r in rows], "total": len(rows)}
