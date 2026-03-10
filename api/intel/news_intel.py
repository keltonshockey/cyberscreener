"""
news_intel.py — Live threat-context scoring for CyberScreener.

Provides warm_caches() + score_ticker_threat_context() called by scanner.py
once per scan run.  Uses module-level TTL caches so all tickers in a scan
share a single fetch of RSS feeds, status pages, and the S&P 500 price.
"""

import time
import requests
import xml.etree.ElementTree as ET
import yfinance as yf
from collections import deque
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, as_completed

# ── Module-level caches ────────────────────────────────────────────────────────

_news_cache     = {"items": None, "ts": 0}   # TTL: 1800s (30 min)
_outage_cache   = {"data":  None, "ts": 0}   # TTL: 300s  (5 min)
_market_cache   = {"spx":   None, "ts": 0}   # TTL: 300s  (5 min)
# Rolling outage history: ticker → deque of last 3 status strings
# Used for confirmation: only apply full penalty after 2+ bad checks
_outage_history: dict = {}

# ── Constants ──────────────────────────────────────────────────────────────────

NEWS_SOURCES = [
    ("Bleeping Computer", "https://www.bleepingcomputer.com/feed/"),
    ("Krebs on Security", "https://krebsonsecurity.com/feed/"),
    ("Dark Reading",      "https://www.darkreading.com/rss.xml"),
]

THREAT_KEYWORDS = {
    "breach", "ransomware", "hack", "exploit", "zero-day",
    "vulnerability", "attack", "phishing", "malware", "outage", "leak",
    "credential", "intrusion", "compromise",
}

# Tickers that have Statuspage endpoints
STATUS_PAGES = {
    "CRWD": ("CrowdStrike",    "https://status.crowdstrike.com/api/v2/summary.json"),
    "NET":  ("Cloudflare",     "https://www.cloudflarestatus.com/api/v2/summary.json"),
    "OKTA": ("Okta",           "https://status.okta.com/api/v2/summary.json"),
    "DDOG": ("Datadog",        "https://status.datadoghq.com/api/v2/summary.json"),
    "PANW": ("Palo Alto",      "https://status.paloaltonetworks.com/api/v2/summary.json"),
    "ZS":   ("Zscaler",        "https://trust.zscaler.com/api/v2/summary.json"),
    "S":    ("SentinelOne",    "https://status.sentinelone.com/api/v2/summary.json"),
}

# ── RSS fetching ───────────────────────────────────────────────────────────────

def _parse_date(pub_str: str):
    """Parse RFC-2822 pubDate → datetime (UTC). Returns None on failure."""
    try:
        from email.utils import parsedate_to_datetime
        dt = parsedate_to_datetime(pub_str)
        return dt.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception:
        return None


def _fetch_one_feed(source_name: str, url: str) -> list:
    items = []
    try:
        resp = requests.get(url, timeout=8,
                            headers={"User-Agent": "CyberScreener/1.0"})
        root = ET.fromstring(resp.content)
        channel = root.find("channel") or root
        for item in channel.findall("item")[:25]:
            title   = (item.findtext("title") or "").strip()
            desc    = (item.findtext("description") or "").strip()
            link    = (item.findtext("link") or "").strip()
            pub     = (item.findtext("pubDate") or "").strip()
            combined = (title + " " + desc).lower()
            tags     = [kw for kw in THREAT_KEYWORDS if kw in combined]
            # Simple ticker mention: exact word match
            words = set(combined.split())
            # ticker_mentions resolved later against the known universe
            items.append({
                "title":     title,
                "summary":   desc[:300],
                "link":      link,
                "published": pub,
                "pub_dt":    _parse_date(pub),
                "source":    source_name,
                "tags":      tags,
                "combined":  combined,
            })
    except Exception as e:
        print(f"⚠️ news_intel: failed fetching {source_name}: {e}")
    return items


def _warm_news(all_tickers: set):
    global _news_cache
    if _news_cache["items"] and (time.time() - _news_cache["ts"]) < 1800:
        return
    all_items = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = {ex.submit(_fetch_one_feed, name, url): name
                for name, url in NEWS_SOURCES}
        for f in as_completed(futs):
            all_items.extend(f.result())

    # Resolve ticker mentions against known universe
    for item in all_items:
        combined_words = set(item["combined"].split())
        item["ticker_mentions"] = [t for t in all_tickers
                                   if t.lower() in combined_words]

    # Sort newest first
    all_items.sort(key=lambda x: x["pub_dt"] or datetime.min, reverse=True)
    _news_cache["items"] = all_items
    _news_cache["ts"]    = time.time()


# ── Status page checking ───────────────────────────────────────────────────────

def _check_one_status(ticker: str, name: str, url: str) -> dict:
    result = {"ticker": ticker, "name": name,
              "status": "unknown", "indicator": "unknown",
              "components_affected": []}
    try:
        resp = requests.get(url, timeout=5)
        data = resp.json()
        indicator = data.get("status", {}).get("indicator", "none")
        result["indicator"] = indicator
        result["status"] = (
            "operational" if indicator == "none" else
            "outage"      if indicator in ("major", "critical") else
            "degraded"    if indicator == "minor" else
            "unknown"
        )
        result["components_affected"] = [
            c["name"] for c in data.get("components", [])
            if c.get("status", "operational") != "operational"
        ]
    except Exception as e:
        result["error"] = str(e)
    return result


def _warm_outages():
    global _outage_cache
    if _outage_cache["data"] and (time.time() - _outage_cache["ts"]) < 300:
        return
    statuses = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futs = {ex.submit(_check_one_status, tk, nm, url): tk
                for tk, (nm, url) in STATUS_PAGES.items()}
        for f in as_completed(futs):
            r = f.result()
            statuses[r["ticker"]] = r
    # Track rolling history for confirmation (require 2+ consecutive bad checks)
    for tk, svc in statuses.items():
        if tk not in _outage_history:
            _outage_history[tk] = deque(maxlen=3)
        _outage_history[tk].append(svc.get("status", "unknown"))

    _outage_cache["data"] = statuses
    _outage_cache["ts"]   = time.time()


# ── S&P 500 macro regime ───────────────────────────────────────────────────────

def _warm_market():
    global _market_cache
    if _market_cache["spx"] is not None and (time.time() - _market_cache["ts"]) < 300:
        return
    try:
        fi = yf.Ticker("^GSPC").fast_info
        price      = getattr(fi, "last_price",     None) or getattr(fi, "regular_market_price", None)
        prev_close = getattr(fi, "previous_close", None) or getattr(fi, "regular_market_previous_close", None)
        if price is None:
            hist = yf.Ticker("^GSPC").history(period="2d")
            if not hist.empty:
                price = float(hist["Close"].iloc[-1])
                prev_close = float(hist["Close"].iloc[-2]) if len(hist) >= 2 else price
        change_pct = ((float(price) - float(prev_close)) / float(prev_close) * 100) if (price and prev_close) else 0.0
        _market_cache["spx"] = round(change_pct, 2)
    except Exception as e:
        print(f"⚠️ news_intel: SPX fetch failed: {e}")
        _market_cache["spx"] = 0.0
    _market_cache["ts"] = time.time()


# ── Public API ─────────────────────────────────────────────────────────────────

def warm_caches(all_tickers=None):
    """
    Pre-fetch RSS feeds, status pages, and S&P 500 in parallel.
    Call once before the ticker loop in run_scan().
    `all_tickers` should be the full set of ticker symbols for mention detection.
    """
    ticker_set = set(all_tickers) if all_tickers else set()
    with ThreadPoolExecutor(max_workers=3) as ex:
        f_news    = ex.submit(_warm_news, ticker_set)
        f_outages = ex.submit(_warm_outages)
        f_market  = ex.submit(_warm_market)
        # Wait for all three — exceptions are swallowed inside each helper
        for f in [f_news, f_outages, f_market]:
            try:
                f.result(timeout=20)
            except Exception as e:
                print(f"⚠️ news_intel warm_caches error: {e}")


def score_ticker_threat_context(ticker: str, sector: str = "cyber") -> dict:
    """
    Return threat context + score modifiers for a single ticker.

    opt_modifier: delta to add to opt_score (can be negative)
    lt_modifier:  delta to add to lt_score  (≤0 only)
    threat_score: 100 + opt_modifier, clamped 0–100
    """
    opt_mod = 0
    lt_mod  = 0
    signals = []
    outage_status = "none"
    breach_victim = False
    demand_signal = False

    # ── 1. Outage check (with rolling confirmation) ────────────────────────────
    if _outage_cache["data"] and ticker in _outage_cache["data"]:
        svc = _outage_cache["data"][ticker]
        outage_status = svc.get("status", "unknown")
        # Confirmation: count bad checks in rolling window
        history = list(_outage_history.get(ticker, []))
        bad_count = sum(1 for s in history if s in ("outage", "degraded"))
        confirmed = bad_count >= 2  # 2 of last 3 checks bad = confirmed
        conf_label = "confirmed" if confirmed else "1st detection"

        if outage_status == "outage":
            # Full penalty after 2 consecutive bad checks; half penalty on first detection
            # Research basis: breach/outage events cause avg -3 to -8% moves for cyber stocks
            # Source: analysis of CRWD Jul 2024 (-38%), OKTA Nov 2023 (-11%), NET various (-5%)
            penalty = 20 if confirmed else 10
            opt_mod -= penalty
            affected = svc.get("components_affected", [])
            detail = f" ({', '.join(affected[:2])})" if affected else ""
            signals.append(f"🔴 Active service outage{detail} — {conf_label} (-{penalty}pts)")
        elif outage_status == "degraded":
            penalty = 8 if confirmed else 4
            opt_mod -= penalty
            signals.append(f"⚠️ Service degraded — {conf_label} (-{penalty}pts)")

    # ── 2. Breach / hack victim detection ─────────────────────────────────────
    if _news_cache["items"]:
        now = datetime.utcnow()
        threat_tags = {"breach", "hack", "ransomware", "leak", "intrusion", "compromise"}
        for item in _news_cache["items"]:
            # Only consider articles published in the last 48 hours
            pub_dt = item.get("pub_dt")
            if pub_dt and (now - pub_dt).total_seconds() > 172800:
                continue
            if ticker in item.get("ticker_mentions", []) and \
               threat_tags & set(item.get("tags", [])):
                breach_victim = True
                opt_mod -= 15
                lt_mod  -= 5
                signals.append(
                    f"🚨 Breach/attack news mentions {ticker}: \"{item['title'][:60]}...\""
                )
                break  # one strike is enough

    # ── 3. Demand signal for unaffected cyber vendors ─────────────────────────
    # Only apply if the company's OWN service is healthy — no point boosting
    # a company that is itself experiencing an outage/degradation
    if sector == "cyber" and not breach_victim and outage_status not in ("outage", "degraded"):
        if _news_cache["items"]:
            threat_articles = [
                i for i in _news_cache["items"]
                if {"breach", "hack", "ransomware", "attack"} & set(i.get("tags", []))
                and (i.get("pub_dt") is None or
                     (datetime.utcnow() - i["pub_dt"]).total_seconds() < 172800)
            ]
            if threat_articles:
                demand_signal = True
                opt_mod += 8
                signals.append(
                    f"🌋 Active threat landscape ({len(threat_articles)} breach articles) "
                    f"— demand signal for {ticker}"
                )

    # ── 4. Macro regime (S&P 500) ─────────────────────────────────────────────
    spx_chg = _market_cache.get("spx", 0.0) or 0.0
    if spx_chg < -3.0:
        opt_mod -= 10
        signals.append(f"📉 Market risk-off: S&P {spx_chg:+.2f}% — strong caution")
    elif spx_chg < -1.5:
        opt_mod -= 5
        signals.append(f"📉 Market soft: S&P {spx_chg:+.2f}% — mild caution")

    # ── 5. Compute composite threat_score ─────────────────────────────────────
    threat_score = max(0, min(100, 100 + opt_mod))

    return {
        "threat_score":   threat_score,
        "opt_modifier":   opt_mod,
        "lt_modifier":    lt_mod,
        "signals":        signals,
        "outage_status":  outage_status,
        "breach_victim":  breach_victim,
        "demand_signal":  demand_signal,
        "spx_change_pct": spx_chg,
    }
