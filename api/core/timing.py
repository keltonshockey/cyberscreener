"""
Options Timing Intelligence Layer

Classifies each ticker into a trade horizon and generates specific plays.

Horizons:
  lotto        — 1-7d to earnings: binary bet, OTM, small size
  pre_earnings — 8-42d to earnings: IV not fully priced, directional
  technical    — 43+d, strong momentum signal: trend play
  value        — 43+d, high LT score, no catalyst: LEAPS / stock

Earnings Date Sources (in priority order):
  1. yfinance get_earnings_dates() — already in scanner, often null
  2. Yahoo Finance earnings calendar scrape — reliable fallback
  3. None — horizon defaults to technical/value based on scores

Debug:
  Each result includes timing_debug dict showing exactly what data
  was used and why each decision was made.
"""

import logging
import math
import requests
from datetime import datetime, timedelta, date
from typing import Optional

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# SAFE MATH HELPERS
# ─────────────────────────────────────────────

def _safe(v, default=0.0):
    """Return default if v is None or NaN."""
    if v is None:
        return default
    try:
        f = float(v)
        return default if math.isnan(f) or math.isinf(f) else f
    except (TypeError, ValueError):
        return default


def _safe_int(v, default=0):
    try:
        f = float(v)
        return default if math.isnan(f) else int(f)
    except (TypeError, ValueError):
        return default


# ─────────────────────────────────────────────
# EARNINGS DATE ENRICHMENT
# ─────────────────────────────────────────────

def _scrape_yahoo_earnings_date(ticker: str) -> Optional[date]:
    """
    Scrape Yahoo Finance earnings calendar for next earnings date.
    Returns date or None. Fails silently.
    """
    try:
        url = f"https://finance.yahoo.com/calendar/earnings?symbol={ticker}"
        headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                          "AppleWebKit/537.36 (KHTML, like Gecko) "
                          "Chrome/120.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        }
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code != 200:
            return None

        # Look for date patterns in the HTML
        import re
        # Yahoo embeds dates as "Earnings Date":"YYYY-MM-DD" or similar
        patterns = [
            r'"earningsDate"\s*:\s*"(\d{4}-\d{2}-\d{2})"',
            r'"startdatetime"\s*:\s*"(\d{4}-\d{2}-\d{2})',
            r'Earnings Date.*?(\w+ \d+, \d{4})',
        ]
        text = resp.text
        for pattern in patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                try:
                    if '-' in match:
                        d = datetime.strptime(match[:10], "%Y-%m-%d").date()
                    else:
                        d = datetime.strptime(match, "%B %d, %Y").date()
                    if d >= datetime.today().date():
                        return d
                except ValueError:
                    continue
    except Exception as e:
        logger.debug(f"Yahoo earnings scrape failed for {ticker}: {e}")
    return None


def get_earnings_date(ticker: str, days_to_earnings_from_scanner: Optional[int]) -> tuple:
    """
    Get best available earnings date.
    Returns (days_to_earnings, source_str).
    """
    today = datetime.today().date()

    # Source 1: Scanner already computed it
    if days_to_earnings_from_scanner is not None:
        dte = int(days_to_earnings_from_scanner)
        if 0 < dte < 365:
            return dte, "yfinance"

    # Source 2: Yahoo Finance scrape
    try:
        scraped = _scrape_yahoo_earnings_date(ticker)
        if scraped:
            dte = (scraped - today).days
            if 0 < dte < 365:
                return dte, f"yahoo_scrape({scraped})"
    except Exception:
        pass

    return None, "not_found"


# ─────────────────────────────────────────────
# HORIZON CLASSIFICATION
# ─────────────────────────────────────────────

def classify_horizon(
    days_to_earnings: Optional[int],
    lt_score: float,
    opt_score: float,
    rsi: float,
    iv_rank: Optional[float],
    whale_bias: str,
    perf_3m: float,
) -> tuple:
    """
    Classify the trade horizon and return (horizon, horizon_reason, confidence).

    Horizons:
      lotto        1-7d earnings
      pre_earnings 8-42d earnings
      technical    No near catalyst, strong momentum
      value        No near catalyst, high LT score
      avoid        Signals conflict or setup is weak
    """
    debug = {
        "days_to_earnings": days_to_earnings,
        "lt_score": lt_score,
        "opt_score": opt_score,
        "rsi": rsi,
        "iv_rank": iv_rank,
        "whale_bias": whale_bias,
        "perf_3m": perf_3m,
    }

    # ── Earnings-based horizons ──
    if days_to_earnings is not None and days_to_earnings > 0:
        if days_to_earnings <= 7:
            return "lotto", f"Earnings in {days_to_earnings}d — binary catalyst", 0.9, debug
        elif days_to_earnings <= 42:
            # Pre-earnings: best if IV not yet elevated
            iv_cheap = iv_rank is not None and iv_rank < 50
            confidence = 0.85 if iv_cheap else 0.65
            reason = (
                f"Earnings in {days_to_earnings}d — "
                f"{'IV still cheap (rank {:.0f}%)'.format(iv_rank) if iv_cheap else 'IV rising'}, "
                f"enter before IV spike"
            )
            return "pre_earnings", reason, confidence, debug

    # ── No near catalyst — use momentum and LT score ──
    bull_momentum = (
        rsi < 40 or  # Oversold bounce setup
        (perf_3m > 10 and rsi < 65) or  # Uptrend with room
        whale_bias in ("bullish", "active")
    )
    strong_fundamentals = lt_score >= 60

    if bull_momentum and strong_fundamentals:
        return "technical", "Strong momentum + solid fundamentals — trend play", 0.75, debug
    elif bull_momentum:
        return "technical", "Momentum signal — purely technical setup", 0.6, debug
    elif strong_fundamentals and lt_score >= 70:
        return "value", f"High LT score ({lt_score:.0f}) — LEAPS or accumulate", 0.7, debug
    elif opt_score < 25 and lt_score < 50:
        return "avoid", "Weak opt + LT scores — no edge identified", 0.3, debug
    else:
        return "value", "No strong catalyst or momentum — thesis-driven only", 0.5, debug


# ─────────────────────────────────────────────
# EXPIRY SELECTION PER HORIZON
# ─────────────────────────────────────────────

def select_expiry_for_horizon(
    horizon: str,
    days_to_earnings: Optional[int],
    available_expiries: list,
) -> tuple:
    """
    Pick the best expiry date for each horizon.
    Returns (expiry_str, dte, expiry_reason).
    available_expiries: list of 'YYYY-MM-DD' strings.
    """
    if not available_expiries:
        return None, None, "no_expiries_available"

    today = datetime.today().date()

    def dte_for(exp_str):
        return (datetime.strptime(exp_str, "%Y-%m-%d").date() - today).days

    expiries_with_dte = [(e, dte_for(e)) for e in available_expiries if dte_for(e) > 0]
    if not expiries_with_dte:
        return None, None, "all_expiries_past"

    if horizon == "lotto":
        # Want expiry right after earnings — shortest available
        if days_to_earnings:
            post = [(e, d) for e, d in expiries_with_dte if d >= days_to_earnings]
            if post:
                e, d = post[0]
                return e, d, f"First expiry after earnings ({days_to_earnings}d out)"
        e, d = expiries_with_dte[0]
        return e, d, "Nearest expiry (lotto)"

    elif horizon == "pre_earnings":
        # Want 20-45 DTE — captures the IV expansion into earnings
        target_dte = (days_to_earnings or 30) + 7  # One week past earnings
        best = min(expiries_with_dte, key=lambda x: abs(x[1] - target_dte))
        e, d = best
        return e, d, f"Post-earnings expiry ~{d}DTE — captures IV expansion"

    elif horizon == "technical":
        # 25-40 DTE — standard momentum play
        best = min(expiries_with_dte, key=lambda x: abs(x[1] - 35))
        e, d = best
        return e, d, f"~{d}DTE — standard technical play window"

    elif horizon == "value":
        # 60-90 DTE — thesis needs time to play out
        best = min(expiries_with_dte, key=lambda x: abs(x[1] - 75))
        e, d = best
        return e, d, f"~{d}DTE — thesis-driven, needs time"

    else:  # avoid
        e, d = expiries_with_dte[0]
        return e, d, "Default (horizon=avoid, no optimal expiry)"


# ─────────────────────────────────────────────
# PLAY SIZE GUIDANCE
# ─────────────────────────────────────────────

POSITION_SIZING = {
    "lotto": {
        "portfolio_pct": "0.5-1%",
        "contracts": "1-2",
        "rationale": "Binary outcome — size small, max loss = premium paid",
        "risk_level": "HIGH",
    },
    "pre_earnings": {
        "portfolio_pct": "1-2%",
        "contracts": "2-5",
        "rationale": "Defined risk, IV expansion expected — moderate size",
        "risk_level": "MEDIUM",
    },
    "technical": {
        "portfolio_pct": "2-3%",
        "contracts": "3-10",
        "rationale": "Trend trade with stop — standard size",
        "risk_level": "MEDIUM",
    },
    "value": {
        "portfolio_pct": "3-5%",
        "contracts": "5-15 or stock",
        "rationale": "Thesis-driven, longer hold — can size up",
        "risk_level": "LOW-MEDIUM",
    },
    "avoid": {
        "portfolio_pct": "0%",
        "contracts": "0",
        "rationale": "No clear edge — skip",
        "risk_level": "N/A",
    },
}


# ─────────────────────────────────────────────
# MAIN ENTRY POINT
# ─────────────────────────────────────────────

def compute_timing_intelligence(
    ticker: str,
    data: dict,
    fetched_chains: list,
) -> dict:
    """
    Compute full timing intelligence for a ticker.

    Args:
        ticker: Stock symbol
        data: Dict from fetch_ticker_data (already has lt_score, opt_score, etc.)
        fetched_chains: List of (expiry_str, chain_obj) tuples from scanner

    Returns:
        timing dict with horizon, expiry recommendation, plays, debug info
    """
    result = {
        "horizon": None,
        "horizon_reason": None,
        "horizon_confidence": None,
        "recommended_expiry": None,
        "recommended_dte": None,
        "expiry_reason": None,
        "sizing": None,
        "timing_signals": [],
        "timing_debug": {},
        "timing_error": None,
    }

    try:
        # ── Step 1: Get best earnings date ──
        dte_scanner = data.get("days_to_earnings")
        days_to_earnings, earnings_source = get_earnings_date(ticker, dte_scanner)

        # ── Step 2: Classify horizon ──
        lt_score = _safe(data.get("lt_score"), 0)
        opt_score = _safe(data.get("opt_score"), 0)
        rsi = _safe(data.get("rsi"), 50)
        iv_rank = data.get("iv_rank")
        whale_bias = data.get("whale_bias", "neutral")
        perf_3m = _safe(data.get("perf_3m"), 0)

        horizon, horizon_reason, confidence, h_debug = classify_horizon(
            days_to_earnings, lt_score, opt_score,
            rsi, iv_rank, whale_bias, perf_3m
        )

        # ── Step 3: Select expiry ──
        available_expiries = sorted(set(exp for exp, _ in fetched_chains)) if fetched_chains else []
        rec_expiry, rec_dte, expiry_reason = select_expiry_for_horizon(
            horizon, days_to_earnings, available_expiries
        )

        # ── Step 4: Build timing signals ──
        signals = []
        price = _safe(data.get("price"), 0)

        if days_to_earnings:
            signals.append(
                f"📅 Earnings in {days_to_earnings}d "
                f"(source: {earnings_source})"
            )

        if iv_rank is not None:
            if iv_rank < 20:
                signals.append(f"🟢 IV Rank {iv_rank:.0f}% — options historically cheap, favor buying")
            elif iv_rank > 80:
                signals.append(f"🔴 IV Rank {iv_rank:.0f}% — options expensive, favor spreads/selling")
            elif iv_rank > 60:
                signals.append(f"🟡 IV Rank {iv_rank:.0f}% — elevated, consider spreads over naked longs")

        if whale_bias in ("bullish", "bearish"):
            signals.append(f"🐋 Whale flow: {whale_bias} — institutional positioning detected")

        if rsi < 30:
            signals.append(f"📊 RSI {rsi:.0f} — oversold, mean reversion setup")
        elif rsi > 70:
            signals.append(f"📊 RSI {rsi:.0f} — overbought, consider puts or wait for pullback")

        if horizon == "pre_earnings" and iv_rank and iv_rank > 60:
            signals.append(
                f"⚠️ IV already elevated ({iv_rank:.0f}%) entering pre-earnings — "
                f"consider spread to reduce vega risk"
            )

        if horizon == "lotto" and price > 0 and data.get("iv_30d"):
            iv = _safe(data.get("iv_30d"), 30)
            days = days_to_earnings or 7
            expected_move = price * (iv / 100) * math.sqrt(days / 365)
            signals.append(
                f"📐 Expected move to earnings: ±${expected_move:.2f} "
                f"({expected_move/price*100:.1f}%) based on {iv:.0f}% IV"
            )

        # ── Step 5: Assemble result ──
        result.update({
            "horizon": horizon,
            "horizon_reason": horizon_reason,
            "horizon_confidence": round(confidence, 2),
            "recommended_expiry": rec_expiry,
            "recommended_dte": rec_dte,
            "expiry_reason": expiry_reason,
            "sizing": POSITION_SIZING.get(horizon, {}),
            "timing_signals": signals,
            "timing_debug": {
                **h_debug,
                "earnings_source": earnings_source,
                "available_expiries": available_expiries,
                "rec_expiry": rec_expiry,
            },
        })

    except Exception as e:
        logger.warning(f"Timing intelligence failed for {ticker}: {e}", exc_info=True)
        result["timing_error"] = str(e)

    return result
