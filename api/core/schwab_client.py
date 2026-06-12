"""
Schwab marketdata client — async, cached, with graceful fallback.
Used by scanner.py to enrich options data for top-25 tickers.

Token file expected at: /opt/cyberscreener/.vault/schwab_tokens.json
Format: {"access_token": "...", "refresh_token": "...", "expires_in": 1800,
          "access_token_issued_at": <unix_seconds>}

Falls back cleanly (returns None) on any error — scanner never crashes.
"""
# Deferred annotation evaluation is REQUIRED here: chain_to_dataframes' return
# annotation references pd, but pandas is imported lazily inside the function.
# Without this, the module raises NameError at import on Python <=3.13 (prod is
# 3.11) — scanner.py swallows that as "Schwab pre-fetch failed (non-fatal)" and
# silently falls back to yfinance for every ticker. Python 3.14 (mill) defers
# annotations by default, which is why test runs there never caught it.
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Optional
import aiohttp

logger = logging.getLogger(__name__)

SCHWAB_BASE = "https://api.schwabapi.com/marketdata/v1"
TOKEN_PATH = Path("/opt/cyberscreener/.vault/schwab_tokens.json")
_CACHE_TTL = 240  # seconds

# Module-level cache: {symbol: (fetched_at, data)}
_chain_cache: dict[str, tuple[float, Optional[dict]]] = {}
_quote_cache: dict[str, tuple[float, Optional[dict]]] = {}

# Concurrency limiter (max 5 concurrent Schwab calls). It must NOT be created at
# import time: scanner.py drives enrichment via a fresh asyncio.run() each scan,
# so a module-level Semaphore binds to the first run's loop and every later scan
# raises "bound to a different event loop". Create it lazily inside the running
# loop and rebind whenever the loop changes.
_SEM_LIMIT = 5
_sem: Optional[asyncio.Semaphore] = None
_sem_loop: Optional[asyncio.AbstractEventLoop] = None


def _get_sem() -> asyncio.Semaphore:
    global _sem, _sem_loop
    loop = asyncio.get_running_loop()
    if _sem is None or _sem_loop is not loop:
        _sem = asyncio.Semaphore(_SEM_LIMIT)
        _sem_loop = loop
    return _sem

def load_token() -> Optional[str]:
    try:
        if not TOKEN_PATH.exists():
            return None
        with open(TOKEN_PATH, 'r') as f:
            token_data = json.load(f)
        access_token_issued_at = token_data.get("access_token_issued_at", 0)
        expires_in = token_data.get("expires_in", 1800)
        if access_token_issued_at + expires_in - time.time() < 60:
            logger.warning("Schwab token near expiry")
        return token_data["access_token"]
    except Exception as e:
        logger.warning(f"Failed to load Schwab token: {e}")
        return None

async def get_option_chain(symbol: str, access_token: str, strike_count: int = 10) -> Optional[dict]:
    if symbol in _chain_cache and time.time() - _chain_cache[symbol][0] < _CACHE_TTL:
        return _chain_cache[symbol][1]
    async with _get_sem():
        try:
            url = f"{SCHWAB_BASE}/chains"
            params = {
                "symbol": symbol,
                "contractType": "ALL",
                "strikeCount": strike_count,
                "range": "NTM",
                "includeUnderlyingQuote": True
            }
            headers = {"Authorization": f"Bearer {access_token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, headers=headers, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status == 200:
                        data = await response.json()
                        _chain_cache[symbol] = (time.time(), data)
                        return data
        except Exception as e:
            logger.warning(f"Failed to fetch option chain for {symbol}: {e}")
    _chain_cache[symbol] = (time.time(), None)
    return None

async def get_quote(symbol: str, access_token: str) -> Optional[dict]:
    if symbol in _quote_cache and time.time() - _quote_cache[symbol][0] < _CACHE_TTL:
        return _quote_cache[symbol][1]
    async with _get_sem():
        try:
            url = f"{SCHWAB_BASE}/{symbol}/quotes"
            headers = {"Authorization": f"Bearer {access_token}"}
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=8)) as response:
                    if response.status == 200:
                        data = await response.json()
                        _quote_cache[symbol] = (time.time(), data)
                        return data
        except Exception as e:
            logger.warning(f"Failed to fetch quote for {symbol}: {e}")
    _quote_cache[symbol] = (time.time(), None)
    return None

async def enrich_tickers(symbols: list[str]) -> dict[str, dict]:
    token = load_token()
    if not token:
        logger.warning("No Schwab token available for enrichment")
        return {}
    async def _one(symbol):
        chain, quote = await asyncio.gather(
            get_option_chain(symbol, token),
            get_quote(symbol, token),
        )
        return symbol, {"chain": chain, "quote": quote}
    pairs = await asyncio.gather(*[_one(s) for s in symbols])
    return dict(pairs)

def chain_to_dataframes(chain: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    import pandas as pd
    if not chain or "callExpDateMap" not in chain or "putExpDateMap" not in chain:
        return pd.DataFrame(), pd.DataFrame()
    
    def flatten_options(exp_date_map):
        options = []
        for exp_date, strikes in exp_date_map.items():
            for strike_price, option_list in strikes.items():
                for option in option_list:
                    options.append({
                        "strike": option.get("strikePrice", 0),
                        "lastPrice": option.get("last", 0),
                        "bid": option.get("bid", 0),
                        "ask": option.get("ask", 0),
                        "volume": option.get("totalVolume", 0),
                        "openInterest": option.get("openInterest", 0),
                        "impliedVolatility": option.get("volatility", 0) / 100,
                        "delta": option.get("delta", 0),
                        "gamma": option.get("gamma", 0),
                        "theta": option.get("theta", 0)
                    })
        return pd.DataFrame(options).fillna(0)

    calls_df = flatten_options(chain["callExpDateMap"])
    puts_df = flatten_options(chain["putExpDateMap"])
    return calls_df, puts_df
