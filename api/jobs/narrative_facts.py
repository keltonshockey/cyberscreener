"""
Light, cited fact fetchers for the narrative pipeline.

Every fact is {id, kind, title, url, date}. The model may cite ONLY facts fetched
this run (the cite-only-fetched rule lives in the verifier). Each fetcher is
isolated and defensive: a failure logs and returns [], the rest proceed (Job
Radar lesson). stdlib only (urllib + a tolerant XML/JSON parse).

  * SEC: latest 10-K / 10-Q from SEC EDGAR's public submissions JSON, each with
    the filing index URL. This is the EDGAR path the system already uses, but
    decoupled (no yfinance / scanner imports — the scoring box stays untouched).
  * News: a small headline fetch via Google News RSS, capped + time-bounded.
  * Peers: a curated sector -> peer-set map for the competition frame.
"""

import os
import re
import json
import time
import logging
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime

logger = logging.getLogger(__name__)

_UA = "cyberscreener-narrative/1.0 (contact: ops@quaest.tech)"

# SEC asks for a descriptive UA; EDGAR JSON is public + read-only.
_SEC_TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
_SEC_SUBMISSIONS = "https://data.sec.gov/submissions/CIK{cik:010d}.json"

NEWS_CAP = 4
NEWS_CACHE_TTL = 12 * 3600  # 12h — light footprint, headlines don't churn faster

# Curated competition frame. Intentionally small; v1 (NARRATIVE_LAYER_PLAN.md).
PEER_MAP = {
    "cyber": ["CRWD", "PANW", "FTNT", "ZS", "S", "OKTA", "NET", "CYBR"],
    "energy": ["CCJ", "CEG", "FSLR", "NEE", "VST", "EQIX"],
    "defense": ["LMT", "RTX", "NOC", "GD", "AVAV", "KTOS"],
    "tech": ["MSFT", "AAPL", "NVDA", "GOOGL", "AMZN", "META"],
}

# Module cache for news so repeated runs within the TTL don't re-fetch.
_news_cache: dict = {}


def _get(url: str, timeout: int = 8) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def peers_for(sector: str | None) -> list:
    if not sector:
        return []
    return [p for p in PEER_MAP.get(sector.lower(), [])]


# ── SEC ──────────────────────────────────────────────────────────────────────

_cik_map: dict | None = None


def _load_cik_map() -> dict:
    global _cik_map
    if _cik_map is not None:
        return _cik_map
    try:
        data = json.loads(_get(_SEC_TICKERS_URL, timeout=10))
        # shape: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "..."}, ...}
        _cik_map = {
            row["ticker"].upper(): int(row["cik_str"])
            for row in data.values()
        }
    except Exception as e:  # noqa: BLE001 - defensive per source
        logger.warning("SEC cik map fetch failed: %s", e)
        _cik_map = {}
    return _cik_map


def fetch_sec_facts(ticker: str, kinds=("10-K", "10-Q"), limit: int = 2) -> list:
    """Latest 10-K/10-Q filings with index URLs. Returns [] on any failure."""
    t = ticker.upper()
    facts: list = []
    try:
        cik = _load_cik_map().get(t)
        if not cik:
            return []
        data = json.loads(_get(_SEC_SUBMISSIONS.format(cik=cik), timeout=10))
        recent = data.get("filings", {}).get("recent", {})
        forms = recent.get("form", [])
        accs = recent.get("accessionNumber", [])
        dates = recent.get("filingDate", [])
        prim = recent.get("primaryDocument", [])
        seen = 0
        for i, form in enumerate(forms):
            if form not in kinds:
                continue
            acc = accs[i].replace("-", "")
            doc = prim[i] if i < len(prim) else ""
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{acc}/{doc or ''}".rstrip("/")
            facts.append({
                "id": f"sec{seen + 1}",
                "kind": "sec_filing",
                "title": f"{form} filed {dates[i]}",
                "url": url,
                "date": dates[i],
            })
            seen += 1
            if seen >= limit:
                break
    except Exception as e:  # noqa: BLE001
        logger.warning("SEC facts failed for %s: %s", t, e)
        return []
    return facts


# ── News ─────────────────────────────────────────────────────────────────────

def fetch_news_facts(ticker: str, company: str | None = None, cap: int = NEWS_CAP) -> list:
    """A few recent cited headlines via Google News RSS. Cached per ticker for
    NEWS_CACHE_TTL. Returns [] on any failure."""
    t = ticker.upper()
    now = time.time()
    cached = _news_cache.get(t)
    if cached and (now - cached["ts"]) < NEWS_CACHE_TTL:
        return cached["facts"]

    facts: list = []
    try:
        q = f'"{company}" stock' if company else f"{t} stock"
        url = (
            "https://news.google.com/rss/search?q="
            + urllib.parse.quote(q)
            + "&hl=en-US&gl=US&ceid=US:en"
        )
        root = ET.fromstring(_get(url, timeout=8))
        items = root.findall(".//item")
        for i, item in enumerate(items[:cap]):
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub = (item.findtext("pubDate") or "").strip()
            if not title or not link:
                continue
            facts.append({
                "id": f"news{len(facts) + 1}",
                "kind": "news",
                "title": title,
                "url": link,
                "date": pub,
            })
    except Exception as e:  # noqa: BLE001
        logger.warning("News facts failed for %s: %s", t, e)
        facts = []

    _news_cache[t] = {"ts": now, "facts": facts}
    return facts


def assemble_facts(ticker: str, sector: str | None = None, company: str | None = None) -> list:
    """All cited facts for one ticker. Each fetcher is independent; one failing
    does not sink the others."""
    facts: list = []
    facts.extend(fetch_sec_facts(ticker))
    facts.extend(fetch_news_facts(ticker, company=company))
    return facts
