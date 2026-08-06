"""
Price series loading and the price-derived inputs, ported verbatim from the
June engine.

Prices are never restated, so any working daily source is PIT-valid; the corpus
carries yfinance Adj Close (split + dividend adjusted, i.e. total return).
Column 5 is Adj Close in the corpus CSV layout:

    Date,Open,High,Low,Close,Adj Close,Volume,Dividends,Stock Splits
"""

from __future__ import annotations

import bisect
import datetime as dt

from .pit import parse_date

# A snapshot needs a full year of history behind it for the 52-week high and
# the 200-day SMA. 252 trading days is that year.
MIN_HISTORY_BARS = 252

# Calendar days per month used to locate the forward-return target date.
DAYS_PER_MONTH = 30.44


def load_prices(path: str) -> tuple[list[dt.date], list[float]]:
    """Read (dates, adj_close) from a corpus price CSV, skipping unparseable rows."""
    dates: list[dt.date] = []
    adj: list[float] = []
    with open(path) as f:
        next(f)  # header
        for line in f:
            parts = line.split(",")
            if len(parts) < 6:
                continue
            try:
                d = parse_date(parts[0])
                a = float(parts[5])
            except Exception:
                continue
            if a > 0:
                dates.append(d)
                adj.append(a)
    return dates, adj


def price_row(dates: list[dt.date], adj: list[float], D: dt.date) -> dict | None:
    """
    Price-derived scoring inputs as of D, or None if there is not enough history.

    `bisect_right(...) - 1` is the last bar at or before D — never a bar after
    it, which is what keeps the snapshot point-in-time.
    """
    i = bisect.bisect_right(dates, D) - 1
    if i < MIN_HISTORY_BARS:
        return None
    price = adj[i]
    return dict(
        price=price,
        sma_20=sum(adj[i - 19:i + 1]) / 20,
        sma_50=sum(adj[i - 49:i + 1]) / 50,
        sma_200=sum(adj[i - 199:i + 1]) / 200,
        pct_from_52w_high=(price / max(adj[i - 251:i + 1]) - 1) * 100,
        perf_1m=(price / adj[i - 21] - 1) * 100,
        perf_3m=(price / adj[i - 63] - 1) * 100,
        _idx=i,
    )


def fwd_return(dates: list[dt.date], adj: list[float], D: dt.date, months: int) -> float | None:
    """
    Forward total return from D to D + `months`, or None if the series ends first.

    Returning None (rather than the last available price) is what prevents the
    tail of the corpus from manufacturing truncated, survivor-flattered returns.
    """
    target = D + dt.timedelta(days=int(round(months * DAYS_PER_MONTH)))
    j = bisect.bisect_left(dates, target)
    if j >= len(dates):
        return None
    i = bisect.bisect_right(dates, D) - 1
    if i < 0:
        return None
    return adj[j] / adj[i] - 1
