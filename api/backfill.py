"""
Historical Backfill — Bootstrap the backtest database with simulated past scans.

Downloads 1 year of daily data for all tickers, then for each Monday over
the past N months, computes what the screener would have scored that day.
Saves to the same DB so the backtest engine can analyze it immediately.

Usage:
  python backfill.py                # Default: 6 months of weekly scans
  python backfill.py --months 3     # 3 months
  python backfill.py --months 12    # Full year
"""

import sys
import argparse
import time
import logging
from pathlib import Path
from datetime import datetime, timedelta

import yfinance as yf
import pandas as pd
import numpy as np

sys.path.insert(0, str(Path(__file__).parent))

from core.scanner import ALL_TICKERS, score_long_term, score_options
from db.models import init_db, get_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger(__name__)


def download_all_history(tickers, period="1y"):
    """Download full price history for all tickers at once (much faster than one-by-one)."""
    logger.info(f"Downloading {period} history for {len(tickers)} tickers...")
    try:
        data = yf.download(tickers, period=period, group_by="ticker", progress=True, threads=True)
        logger.info(f"Download complete. Shape: {data.shape}")
        return data
    except Exception as e:
        logger.error(f"Bulk download failed: {e}")
        return None


def download_fundamentals(tickers):
    """Download current fundamentals for all tickers (these don't change much over 6mo)."""
    logger.info(f"Fetching fundamentals for {len(tickers)} tickers...")
    fundamentals = {}
    for i, ticker in enumerate(tickers):
        try:
            t = yf.Ticker(ticker)
            info = t.info
            fundamentals[ticker] = {
                "market_cap": info.get("marketCap", 0),
                "revenue": info.get("totalRevenue", 0),
                "revenue_growth": info.get("revenueGrowth", 0),
                "gross_margins": info.get("grossMargins", 0),
                "fcf": info.get("freeCashflow", 0),
                "ps_ratio": info.get("priceToSalesTrailing12Months", None),
                "pe_ratio": info.get("trailingPE", None),
                "beta": info.get("beta", 1.0),
                "short_pct": info.get("shortPercentOfFloat", 0) or 0,
            }
            if (i + 1) % 10 == 0:
                logger.info(f"  Fundamentals: {i+1}/{len(tickers)}")
            time.sleep(0.2)
        except Exception as e:
            fundamentals[ticker] = {}
    return fundamentals


def compute_technicals_on_date(hist_df, sim_date, lookback=252):
    """Compute all technical indicators as of a specific date using historical data."""
    # Get data up to sim_date
    mask = hist_df.index <= pd.Timestamp(sim_date)
    data = hist_df[mask]

    if data.empty or len(data) < 20:
        return None

    close = data["Close"]
    price = close.iloc[-1]

    # SMAs
    sma_20 = close.rolling(20).mean().iloc[-1] if len(close) >= 20 else price
    sma_50 = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else price
    sma_200 = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else None

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
    rs = gain / loss
    rsi_series = 100 - (100 / (1 + rs))
    rsi = rsi_series.iloc[-1] if not rsi_series.empty else 50

    # BB width
    rolling_std = close.rolling(20).std().iloc[-1] if len(close) >= 20 else 0
    bb_width = (rolling_std * 4) / sma_20 * 100 if sma_20 > 0 else 0

    # Volume ratio
    if "Volume" in data.columns and len(data) >= 20:
        avg_vol_20d = data["Volume"].tail(20).mean()
        avg_vol_5d = data["Volume"].tail(5).mean()
        vol_ratio = avg_vol_5d / avg_vol_20d if avg_vol_20d > 0 else 1.0
    else:
        vol_ratio = 1.0

    # Performance
    price_63d_ago = close.iloc[-63] if len(close) >= 63 else price
    price_252d_ago = close.iloc[0]
    high_52w = data["High"].max() if "High" in data.columns else price
    low_52w = data["Low"].min() if "Low" in data.columns else price

    perf_3m = ((price / price_63d_ago) - 1) * 100 if price_63d_ago > 0 else 0
    perf_1y = ((price / price_252d_ago) - 1) * 100 if price_252d_ago > 0 else 0
    pct_from_high = ((price / high_52w) - 1) * 100 if high_52w > 0 else 0

    return {
        "price": round(float(price), 2),
        "rsi": round(float(rsi), 1) if not np.isnan(rsi) else 50.0,
        "sma_20": round(float(sma_20), 2),
        "sma_50": round(float(sma_50), 2),
        "sma_200": round(float(sma_200), 2) if sma_200 is not None else None,
        "bb_width": round(float(bb_width), 1),
        "vol_ratio": round(float(vol_ratio), 2),
        "perf_3m": round(float(perf_3m), 1),
        "perf_1y": round(float(perf_1y), 1),
        "pct_from_52w_high": round(float(pct_from_high), 1),
        "price_52w_high": round(float(high_52w), 2),
        "price_52w_low": round(float(low_52w), 2),
        "price_above_sma20": float(price) > float(sma_20),
        "price_above_sma50": float(price) > float(sma_50),
        "price_above_sma200": float(price) > float(sma_200) if sma_200 is not None else None,
    }


def get_forward_price(hist_df, sim_date, days_forward):
    """Get the price N trading days after sim_date."""
    mask = hist_df.index > pd.Timestamp(sim_date)
    future = hist_df[mask]
    if future.empty or len(future) < days_forward:
        return None
    idx = min(days_forward, len(future) - 1)
    return float(future["Close"].iloc[idx])


def run_backfill(months=6):
    """Run the full backfill process."""
    init_db()

    # Step 1: Download all history
    all_data = download_all_history(ALL_TICKERS, period="1y")
    if all_data is None or all_data.empty:
        logger.error("Failed to download historical data.")
        return

    # Step 2: Download fundamentals (current — used as proxy for past)
    fundamentals = download_fundamentals(ALL_TICKERS)

    # Step 3: Generate simulation dates (every Monday for past N months)
    today = datetime.today()
    start_date = today - timedelta(days=months * 30)
    sim_dates = []
    current = start_date
    while current < today - timedelta(days=7):  # Stop a week before today for forward returns
        # Find the next Monday
        while current.weekday() != 0:
            current += timedelta(days=1)
        if current < today - timedelta(days=7):
            sim_dates.append(current)
        current += timedelta(days=7)

    logger.info(f"Simulating {len(sim_dates)} weekly scans from {sim_dates[0].strftime('%Y-%m-%d')} to {sim_dates[-1].strftime('%Y-%m-%d')}")

    conn = get_db()
    total_records = 0

    for sim_idx, sim_date in enumerate(sim_dates):
        sim_date_str = sim_date.strftime("%Y-%m-%d")
        logger.info(f"[{sim_idx+1}/{len(sim_dates)}] Simulating scan for {sim_date_str}...")

        # Create scan record
        cursor = conn.execute(
            "INSERT INTO scans (timestamp, tickers_scanned, config_json, intel_layers) VALUES (?, ?, ?, ?)",
            (sim_date.strftime("%Y-%m-%d %H:%M:%S"), 0, '{"mode": "backfill"}', "base")
        )
        scan_id = cursor.lastrowid
        tickers_in_scan = 0

        for ticker in ALL_TICKERS:
            try:
                # Get ticker's historical data
                if ticker in all_data.columns.get_level_values(0):
                    ticker_hist = all_data[ticker].dropna(subset=["Close"])
                else:
                    continue

                # Compute technicals as of sim_date
                technicals = compute_technicals_on_date(ticker_hist, sim_date)
                if technicals is None:
                    continue

                # Merge with fundamentals
                fund = fundamentals.get(ticker, {})
                market_cap = fund.get("market_cap", 0)

                row = {
                    **technicals,
                    "ticker": ticker,
                    "market_cap_b": round(market_cap / 1e9, 1) if market_cap else None,
                    "revenue_growth_pct": round(fund.get("revenue_growth", 0) * 100, 1) if fund.get("revenue_growth") else None,
                    "gross_margin_pct": round(fund.get("gross_margins", 0) * 100, 1) if fund.get("gross_margins") else None,
                    "fcf_m": round(fund.get("fcf", 0) / 1e6, 0) if fund.get("fcf") else None,
                    "ps_ratio": round(fund.get("ps_ratio"), 1) if fund.get("ps_ratio") else None,
                    "pe_ratio": round(fund.get("pe_ratio"), 1) if fund.get("pe_ratio") else None,
                    "beta": round(fund.get("beta", 1.0), 2) if fund.get("beta") else None,
                    "short_pct": round(fund.get("short_pct", 0) * 100, 1),
                    "iv_30d": None,  # Can't reliably backfill historical IV
                    "days_to_earnings": None,  # Can't reliably backfill
                }

                # Score it
                lt_score, lt_reasons = score_long_term(row)
                opt_score, opt_reasons = score_options(row)

                # Insert score
                conn.execute("""
                    INSERT INTO scores (
                        scan_id, ticker, price, market_cap_b,
                        lt_score, opt_score,
                        revenue_growth_pct, gross_margin_pct, ps_ratio, pe_ratio, fcf_m,
                        rsi, sma_20, sma_50, sma_200, bb_width, vol_ratio, iv_30d, beta, short_pct,
                        perf_1y, perf_3m, pct_from_52w_high, days_to_earnings,
                        sec_score, sentiment_score, sentiment_bull_pct, whale_score, pc_ratio,
                        insider_buys_30d, insider_sells_30d
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    scan_id, ticker, row["price"], row.get("market_cap_b"),
                    lt_score, opt_score,
                    row.get("revenue_growth_pct"), row.get("gross_margin_pct"),
                    row.get("ps_ratio"), row.get("pe_ratio"), row.get("fcf_m"),
                    row["rsi"], row["sma_20"], row["sma_50"], row.get("sma_200"),
                    row["bb_width"], row["vol_ratio"], row.get("iv_30d"),
                    row.get("beta"), row.get("short_pct"),
                    row["perf_1y"], row["perf_3m"], row["pct_from_52w_high"],
                    row.get("days_to_earnings"),
                    0, 0, None, 0, None, 0, 0,
                ))

                # Save price snapshots (entry + forward dates for return calc)
                conn.execute(
                    "INSERT OR IGNORE INTO prices (ticker, date, close_price) VALUES (?, ?, ?)",
                    (ticker, sim_date_str, row["price"])
                )

                # Save forward prices for backtest return calculations
                for fwd_days in [7, 14, 30, 60]:
                    fwd_price = get_forward_price(ticker_hist, sim_date, fwd_days)
                    if fwd_price:
                        fwd_date = (sim_date + timedelta(days=fwd_days)).strftime("%Y-%m-%d")
                        conn.execute(
                            "INSERT OR IGNORE INTO prices (ticker, date, close_price) VALUES (?, ?, ?)",
                            (ticker, fwd_date, fwd_price)
                        )

                tickers_in_scan += 1
                total_records += 1

            except Exception as e:
                continue

        # Update scan with actual ticker count
        conn.execute("UPDATE scans SET tickers_scanned = ? WHERE id = ?", (tickers_in_scan, scan_id))
        conn.commit()

    conn.close()

    logger.info(f"")
    logger.info(f"✅ Backfill complete!")
    logger.info(f"   Simulated scans: {len(sim_dates)}")
    logger.info(f"   Total score records: {total_records}")
    logger.info(f"   Date range: {sim_dates[0].strftime('%Y-%m-%d')} → {sim_dates[-1].strftime('%Y-%m-%d')}")
    logger.info(f"")
    logger.info(f"You can now run backtests:")
    logger.info(f"   uvicorn api.main:app --port 8000")
    logger.info(f"   curl http://localhost:8000/backtest")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backfill historical scan data")
    parser.add_argument("--months", type=int, default=6, help="Months of history to backfill (default: 6)")
    args = parser.parse_args()

    run_backfill(args.months)
