"""
SEC / Insider Intel Layer

Sources:
  1. yfinance insider transactions (SEC Form 4 proxy)
  2. yfinance analyst recommendations
  3. SEC EDGAR full-text search for recent 8-K / DEF 14A filings (no auth needed)

Returns:
  {
    "sec_score": 0-100,
    "sec_signals": [...],              # human-readable signal strings
    "insider_buys_30d": int,
    "insider_sells_30d": int,
    "insider_net_30d": int,            # buys - sells (positive = bullish)
    "insider_buy_value_30d": float,    # $ value of buys
    "insider_sell_value_30d": float,
    "analyst_consensus": str,          # "Strong Buy" / "Buy" / "Hold" / "Sell"
    "analyst_target_price": float,
    "analyst_upside_pct": float,
    "analyst_count": int,
    "recent_8k_count": int,            # 8-K filings in last 30d (potential catalysts)
  }
"""

import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

EDGAR_BASE = "https://efts.sec.gov/LATEST/search-index?q=%22{ticker}%22&dateRange=custom&startdt={start}&enddt={end}&forms=8-K"
EDGAR_HEADERS = {"User-Agent": "CyberScreener research@cyberscreener.io"}


def _get_insider_data(ticker_obj, ticker_sym: str) -> dict:
    """Parse yfinance insider transactions for the last 30 days."""
    result = {
        "insider_buys_30d": 0,
        "insider_sells_30d": 0,
        "insider_buy_value_30d": 0.0,
        "insider_sell_value_30d": 0.0,
    }
    try:
        txns = ticker_obj.insider_transactions
        if txns is None or txns.empty:
            return result

        cutoff = datetime.now() - timedelta(days=30)

        for _, row in txns.iterrows():
            try:
                date_val = row.get("startDate") or row.get("Start Date") or row.get("Date")
                if date_val is None:
                    continue
                if hasattr(date_val, "to_pydatetime"):
                    tx_date = date_val.to_pydatetime().replace(tzinfo=None)
                else:
                    tx_date = datetime.strptime(str(date_val)[:10], "%Y-%m-%d")

                if tx_date < cutoff:
                    continue

                transaction = str(row.get("transaction", row.get("Transaction", ""))).lower()
                shares = abs(float(row.get("shares", row.get("Shares", 0)) or 0))
                value = abs(float(row.get("value", row.get("Value", 0)) or 0))

                is_buy = any(k in transaction for k in ["purchase", "buy", "acquisition", "grant"])
                is_sell = any(k in transaction for k in ["sale", "sell", "disposition"])

                if is_buy:
                    result["insider_buys_30d"] += 1
                    result["insider_buy_value_30d"] += value
                elif is_sell:
                    result["insider_sells_30d"] += 1
                    result["insider_sell_value_30d"] += value

            except Exception:
                continue

    except Exception as e:
        logger.debug(f"insider_transactions error for {ticker_sym}: {e}")

    return result


def _get_analyst_data(ticker_obj, ticker_sym: str, current_price: float) -> dict:
    """Get analyst consensus and price target from yfinance."""
    result = {
        "analyst_consensus": None,
        "analyst_target_price": None,
        "analyst_upside_pct": None,
        "analyst_count": 0,
    }
    try:
        info = ticker_obj.info

        # Analyst consensus via recommendationMean (1=Strong Buy, 5=Strong Sell)
        rec_mean = info.get("recommendationMean")
        rec_key = info.get("recommendationKey", "")
        n_analysts = info.get("numberOfAnalystOpinions", 0) or 0
        target_price = info.get("targetMeanPrice")

        if rec_mean is not None:
            if rec_mean <= 1.5:
                consensus = "Strong Buy"
            elif rec_mean <= 2.5:
                consensus = "Buy"
            elif rec_mean <= 3.5:
                consensus = "Hold"
            elif rec_mean <= 4.5:
                consensus = "Sell"
            else:
                consensus = "Strong Sell"
            result["analyst_consensus"] = consensus

        if target_price and current_price and current_price > 0:
            result["analyst_target_price"] = round(float(target_price), 2)
            result["analyst_upside_pct"] = round(((float(target_price) / current_price) - 1) * 100, 1)

        result["analyst_count"] = int(n_analysts)

    except Exception as e:
        logger.debug(f"analyst data error for {ticker_sym}: {e}")

    return result


def _get_recent_8k_count(ticker_sym: str) -> int:
    """Count 8-K filings in the last 30 days via EDGAR full-text search."""
    try:
        end = datetime.now().strftime("%Y-%m-%d")
        start = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        url = EDGAR_BASE.format(ticker=ticker_sym, start=start, end=end)
        resp = requests.get(url, headers=EDGAR_HEADERS, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            return int(data.get("hits", {}).get("total", {}).get("value", 0))
    except Exception:
        pass
    return 0


def _compute_sec_score(insider: dict, analyst: dict, recent_8k: int) -> tuple[int, list]:
    """
    Compute sec_score (0-100) and generate signal strings.

    Scoring breakdown (max 100):
    - Insider net buying momentum  : 40 pts
    - Analyst consensus strength   : 35 pts
    - Analyst price target upside  : 15 pts
    - Recent 8-K catalysts         : 10 pts
    """
    score = 0
    signals = []

    buys = insider["insider_buys_30d"]
    sells = insider["insider_sells_30d"]
    net = buys - sells
    buy_val = insider["insider_buy_value_30d"]
    sell_val = insider["insider_sell_value_30d"]

    # ── Insider momentum (40 pts) ──
    if net >= 3:
        score += 40
        signals.append(f"🟢 Strong insider buying: {buys} purchases vs {sells} sales (30d)")
    elif net >= 1:
        score += 25
        signals.append(f"🟢 Net insider buying: {buys} purchases, {sells} sales (30d)")
    elif net == 0 and buys == 0:
        score += 15  # No activity is neutral
    elif net == -1:
        score += 5
        signals.append(f"🔴 Mild insider selling: {sells} sales vs {buys} purchases (30d)")
    else:
        score += 0
        signals.append(f"🔴 Insider selling pressure: {sells} sales vs {buys} purchases (30d)")

    if buy_val > 1_000_000:
        score += 5
        signals.append(f"💰 Large insider buy: ${buy_val/1e6:.1f}M in purchases")
    elif buy_val > 100_000:
        score += 2

    # ── Analyst consensus (35 pts) ──
    consensus = analyst.get("analyst_consensus")
    n = analyst.get("analyst_count", 0)
    if consensus == "Strong Buy" and n >= 10:
        score += 35
        signals.append(f"📈 Strong Buy consensus ({n} analysts)")
    elif consensus == "Strong Buy":
        score += 28
        signals.append(f"📈 Strong Buy consensus ({n} analysts)")
    elif consensus == "Buy" and n >= 10:
        score += 25
        signals.append(f"📈 Buy consensus ({n} analysts)")
    elif consensus == "Buy":
        score += 18
        signals.append(f"📈 Buy consensus ({n} analysts)")
    elif consensus == "Hold":
        score += 10
    elif consensus in ("Sell", "Strong Sell"):
        score += 0
        signals.append(f"🔴 Analyst consensus: {consensus} ({n} analysts)")

    # ── Analyst upside (15 pts) ──
    upside = analyst.get("analyst_upside_pct")
    target = analyst.get("analyst_target_price")
    if upside is not None:
        if upside >= 30:
            score += 15
            signals.append(f"🎯 Analyst target: ${target} (+{upside:.0f}% upside)")
        elif upside >= 15:
            score += 10
            signals.append(f"🎯 Analyst target: ${target} (+{upside:.0f}% upside)")
        elif upside >= 5:
            score += 5
        elif upside < -10:
            signals.append(f"⚠️ Analyst target below market: ${target} ({upside:.0f}%)")

    # ── Recent 8-K catalysts (10 pts) ──
    if recent_8k >= 3:
        score += 10
        signals.append(f"📋 {recent_8k} recent 8-K filings (active catalysts)")
    elif recent_8k >= 1:
        score += 5

    return min(score, 100), signals


def analyze_sec_intel(ticker_obj, ticker_sym: str) -> dict:
    """
    Main entry point for the SEC intel layer.
    Called by scanner.run_scan() when enable_sec=True.
    """
    try:
        # Get current price for upside calc
        current_price = None
        try:
            info = ticker_obj.info
            current_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
            if current_price:
                current_price = float(current_price)
        except Exception:
            pass

        insider = _get_insider_data(ticker_obj, ticker_sym)
        analyst = _get_analyst_data(ticker_obj, ticker_sym, current_price or 0)
        recent_8k = _get_recent_8k_count(ticker_sym)

        sec_score, signals = _compute_sec_score(insider, analyst, recent_8k)

        return {
            "sec_score": sec_score,
            "sec_signals": signals,
            "insider_buys_30d": insider["insider_buys_30d"],
            "insider_sells_30d": insider["insider_sells_30d"],
            "insider_net_30d": insider["insider_buys_30d"] - insider["insider_sells_30d"],
            "insider_buy_value_30d": round(insider["insider_buy_value_30d"], 0),
            "insider_sell_value_30d": round(insider["insider_sell_value_30d"], 0),
            "analyst_consensus": analyst["analyst_consensus"],
            "analyst_target_price": analyst["analyst_target_price"],
            "analyst_upside_pct": analyst["analyst_upside_pct"],
            "analyst_count": analyst["analyst_count"],
            "recent_8k_count": recent_8k,
        }

    except Exception as e:
        logger.warning(f"SEC intel failed for {ticker_sym}: {e}")
        return {
            "sec_score": 0,
            "sec_signals": [],
            "insider_buys_30d": 0,
            "insider_sells_30d": 0,
            "insider_net_30d": 0,
            "insider_buy_value_30d": 0,
            "insider_sell_value_30d": 0,
            "analyst_consensus": None,
            "analyst_target_price": None,
            "analyst_upside_pct": None,
            "analyst_count": 0,
            "recent_8k_count": 0,
        }
