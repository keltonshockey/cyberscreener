"""Tests for schwab_client.py — all external HTTP calls are mocked."""
import asyncio
import json
import time
import unittest.mock as mock
import pytest
import pandas as pd

from core.schwab_client import chain_to_dataframes, get_option_chain, enrich_tickers, load_token
import core.schwab_client as _sc

@pytest.fixture(autouse=True)
def clear_cache():
    _sc._chain_cache.clear()
    _sc._quote_cache.clear()
    yield

def test_chain_to_dataframes_basic():
    chain = {
        "callExpDateMap": {
            "2023-12-01": {
                "150.0": [
                    {"strikePrice": 150, "last": 2.5, "bid": 2.4, "ask": 2.6, "totalVolume": 1000, "openInterest": 50, "volatility": 30}
                ]
            }
        },
        "putExpDateMap": {
            "2023-12-01": {
                "150.0": [
                    {"strikePrice": 150, "last": 1.5, "bid": 1.4, "ask": 1.6, "totalVolume": 800, "openInterest": 40, "volatility": 25}
                ]
            }
        }
    }
    calls_df, puts_df = chain_to_dataframes(chain)
    assert all(col in calls_df.columns for col in ["strike", "volume", "openInterest", "impliedVolatility", "delta", "gamma", "theta"])
    assert all(col in puts_df.columns for col in ["strike", "volume", "openInterest", "impliedVolatility", "delta", "gamma", "theta"])
    assert calls_df["impliedVolatility"].iloc[0] == 0.3

def test_chain_to_dataframes_none():
    calls_df, puts_df = chain_to_dataframes(None)
    assert calls_df.empty
    assert puts_df.empty

@pytest.mark.asyncio
async def test_get_option_chain_success():
    with mock.patch('aiohttp.ClientSession.get') as mock_get:
        mock_response = mock.Mock()
        mock_response.status = 200
        mock_response.json = mock.AsyncMock(return_value={"key": "value"})
        mock_get.return_value.__aenter__.return_value = mock_response

        result = await get_option_chain("AAPL", "fake_token")
        assert isinstance(result, dict)

@pytest.mark.asyncio
async def test_get_option_chain_http_error():
    with mock.patch('aiohttp.ClientSession.get') as mock_get:
        mock_response = mock.Mock()
        mock_response.status = 401
        mock_get.return_value.__aenter__.return_value = mock_response

        result = await get_option_chain("AAPL", "bad_token")
        assert result is None

@pytest.mark.asyncio
async def test_get_option_chain_timeout():
    with mock.patch('aiohttp.ClientSession.get', side_effect=asyncio.TimeoutError):
        result = await get_option_chain("AAPL", "fake_token")
        assert result is None

@pytest.mark.asyncio
async def test_cache_prevents_second_call():
    with mock.patch('aiohttp.ClientSession.get') as mock_get:
        mock_response = mock.Mock()
        mock_response.status = 200
        mock_response.json.return_value = {"key": "value"}
        mock_get.return_value.__aenter__.return_value = mock_response

        await get_option_chain("TSLA", "tok")
        await get_option_chain("TSLA", "tok")
        assert mock_get.call_count == 1

@pytest.mark.asyncio
async def test_enrich_tickers_no_token():
    with mock.patch('core.schwab_client.load_token', return_value=None):
        result = await enrich_tickers(["AAPL", "TSLA"])
        assert result == {}


def test_get_sem_rebinds_across_sequential_event_loops():
    """Regression (Defect B, 2026-06-12): scanner.run_scan drives enrichment via a
    FRESH asyncio.run() every scan. A module-level asyncio.Semaphore binds to the
    first run's loop, so every later scan raised 'is bound to a different event
    loop' and enrichment silently fell back to yfinance. _get_sem() must create
    the semaphore inside the running loop and rebind when the loop changes."""
    _sc._sem = None
    _sc._sem_loop = None

    async def _acquire():
        async with _sc._get_sem():
            return id(asyncio.get_running_loop())

    loop_a = asyncio.run(_acquire())   # old code: binds module sem to loop A
    loop_b = asyncio.run(_acquire())   # old code: RuntimeError raised here
    assert loop_a != loop_b, "expected two genuinely distinct event loops"
    assert _sc._sem is not None


def test_get_option_chain_works_across_sequential_runs():
    """Same regression through the real acquisition path: two separate
    asyncio.run() cycles, each entering `async with _get_sem()`."""
    _sc._sem = None
    _sc._sem_loop = None
    _sc._chain_cache.clear()
    with mock.patch('aiohttp.ClientSession.get') as mock_get:
        mock_response = mock.Mock()
        mock_response.status = 200
        mock_response.json = mock.AsyncMock(return_value={"ok": 1})
        mock_get.return_value.__aenter__.return_value = mock_response

        r1 = asyncio.run(get_option_chain("REGRA", "tok"))
        r2 = asyncio.run(get_option_chain("REGRB", "tok"))
    assert r1 == {"ok": 1}
    assert r2 == {"ok": 1}
