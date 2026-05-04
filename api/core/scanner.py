"""
Core scanner v2 — Rewritten scoring with first-principles-driven metrics.

LT Score (max 100): Would you hold this stock for 1-3 years?
  - Rule of 40 (25 pts): Growth% + Operating Margin%
  - Relative Valuation (20 pts): EV/Revenue vs growth rate (PEG-like)
  - FCF Margin (15 pts): FCF/Revenue — efficiency, not absolute size
  - Technical Trend (15 pts): SMA positioning (200 > 50 > 20 = strong uptrend)
  - Earnings Quality (10 pts): Positive EPS, improving margins
  - Discount + Momentum (15 pts): 52w discount + 3-month trend alignment

Options Score (max 100): Is there an asymmetric short-term trade?
  - Earnings Catalyst (25 pts): Proximity + historical volatility around earnings
  - IV Context (20 pts): IV Rank (current IV vs 52-week IV range)
  - Directional Conviction (20 pts): RSI + SMA alignment + volume confirms
  - Technical Setup (15 pts): BB squeeze + RSI extreme + support/resistance
  - Liquidity (10 pts): Options volume, open interest, spread tightness
  - Asymmetry (10 pts): Expected move vs typical move
"""

import math
import yfinance as yf
import pandas as pd
import numpy as np
import time
import logging
from datetime import datetime, timedelta


def _safe_num(v, default=0):
    """Convert a value to a number, replacing NaN/None/inf with default."""
    if v is None:
        return default
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except (TypeError, ValueError):
        return default


def _safe_int(v, default=0):
    """Convert a value to int, replacing NaN/None/inf with default."""
    return int(_safe_num(v, default))

try:
    from core.universe import (
        get_ticker_meta as _get_ticker_meta,
        ALL_CYBER_TICKERS as _CYB,
        ALL_ENERGY_TICKERS as _ENR,
        ALL_DEFENSE_TICKERS as _DEF,
        ALL_BROAD_TICKERS as _BRD,
    )
    _UNIVERSE_IMPORTED = True
except ImportError:
    _get_ticker_meta = lambda t: {"sector": "cyber", "subsector": "", "scoring_profile": "saas"}
    _CYB, _ENR, _DEF, _BRD = [], [], [], []
    _UNIVERSE_IMPORTED = False

try:
    from core.timing import compute_timing_intelligence
    TIMING_AVAILABLE = True
except Exception as _timing_err:
    TIMING_AVAILABLE = False
    import logging as _lg
    _lg.getLogger(__name__).warning(f"Timing module unavailable: {_timing_err}")

logger = logging.getLogger(__name__)

# Intel layers — imported with fallback so scanner still works if intel fails
try:
    from intel.sec_filings import analyze_sec_intel
    SEC_AVAILABLE = True
except ImportError:
    SEC_AVAILABLE = False
    logger.warning("SEC intel layer not available")

try:
    from intel.sentiment import analyze_sentiment
    SENTIMENT_AVAILABLE = True
except ImportError:
    SENTIMENT_AVAILABLE = False
    logger.warning("Sentiment layer not available")

# P1 + P5: DB access for IV history and short interest trend
try:
    from db.models import get_iv_history, get_short_interest_trend
    DB_HISTORY_AVAILABLE = True
except ImportError:
    DB_HISTORY_AVAILABLE = False
    logger.debug("DB history not available — using synthetic IV rank and skipping short delta")

# ─────────────────────────────────────────────
# TICKER UNIVERSE
# ─────────────────────────────────────────────
# Full multi-sector universe sourced from core/universe.py.
# Kept as a local fallback for import-order safety.

CYBER_UNIVERSE = {
    "Platform Giants": ["CRWD", "PANW", "FTNT", "ZS", "CSCO"],
    "Identity & Access (IAM)": ["OKTA", "CYBR", "SAIL"],
    "Cloud & Network Security": ["NET", "AKAM", "CHKP", "VRNS", "QLYS", "TENB", "RPD", "FFIV"],
    "AI-Powered / Next-Gen": ["S", "DDOG", "MSFT", "GOOGL", "AVGO"],
    "Endpoint Detection (EDR/XDR)": ["GEN"],
    "Threat Intel / IR": ["OTEX", "RDWR"],
    "Enterprise GRC": ["IBM"],
    "Network Hardware / Firewall": ["NTCT", "ATEN"],
    "Data Security": ["VRNS", "VRNT"],
    "Gov / Defense Cyber": ["CACI", "LDOS", "SAIC", "BAH", "BBAI", "PLTR"],
    "Mid/Small Cap Plays": ["TLS", "OSPN", "JAMF", "DT", "ESTC", "RBBN"],
    "ETF Benchmarks": ["HACK"],  # CIBR and BUG removed — no fundamentals/options data
}

_CYBER_FALLBACK = sorted(list(set(t for tickers in CYBER_UNIVERSE.values() for t in tickers)))

# Use full multi-sector universe when universe.py is available
if _UNIVERSE_IMPORTED and (_CYB or _ENR or _DEF):
    ALL_TICKERS = sorted(list(set(_CYB + _ENR + _DEF + _BRD)))
else:
    ALL_TICKERS = _CYBER_FALLBACK


# ─────────────────────────────────────────────
# DEFAULT SCORING WEIGHTS (overridden by self-calibration)
# ─────────────────────────────────────────────

DEFAULT_LT_WEIGHTS = {
    "rule_of_40": 25,
    "valuation": 20,
    "fcf_margin": 15,
    "trend": 15,
    "earnings_quality": 10,
    "discount_momentum": 15,
}

DEFAULT_OPT_WEIGHTS = {
    "earnings_catalyst": 25,
    "iv_context": 20,
    "directional": 20,
    "technical": 15,
    "liquidity": 10,
    "asymmetry": 10,
}

# Active weights — updated by self-calibration
_active_lt_weights = dict(DEFAULT_LT_WEIGHTS)
_active_opt_weights = dict(DEFAULT_OPT_WEIGHTS)

def set_weights(lt_weights=None, opt_weights=None):
    """Override scoring weights (called by self-calibration engine)."""
    global _active_lt_weights, _active_opt_weights
    if lt_weights:
        _active_lt_weights = lt_weights
    if opt_weights:
        _active_opt_weights = opt_weights

def get_weights():
    """Return current active weights."""
    return {"lt": dict(_active_lt_weights), "opt": dict(_active_opt_weights)}


# ─────────────────────────────────────────────
# DATA COLLECTION
# ─────────────────────────────────────────────

def fetch_ticker_data(ticker):
    """Fetch all relevant data for a single ticker."""
    try:
        t = yf.Ticker(ticker)
        info = t.info

        hist_1y = t.history(period="1y")
        if hist_1y.empty or len(hist_1y) < 20:
            return None

        price = float(hist_1y['Close'].iloc[-1])
        close = hist_1y['Close']

        # Price history points
        price_1m_ago = float(close.iloc[-21]) if len(close) >= 21 else price
        price_3m_ago = float(close.iloc[-63]) if len(close) >= 63 else price
        price_52w_high = float(hist_1y['High'].max())
        price_52w_low = float(hist_1y['Low'].min())
        price_1y_ago = float(close.iloc[0])

        # Volume
        avg_vol_20d = float(hist_1y['Volume'].tail(20).mean())
        avg_vol_5d = float(hist_1y['Volume'].tail(5).mean())
        vol_ratio = avg_vol_5d / avg_vol_20d if avg_vol_20d > 0 else 1.0

        # Moving averages
        sma_20 = float(close.rolling(20).mean().iloc[-1])
        sma_50 = float(close.rolling(50).mean().iloc[-1]) if len(close) >= 50 else None
        sma_200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

        # RSI
        delta = close.diff()
        gain = delta.where(delta > 0, 0).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rs = gain / loss
        rsi_val = float((100 - (100 / (1 + rs))).iloc[-1])
        if np.isnan(rsi_val):
            rsi_val = 50.0

        # Bollinger Band width
        rolling_std = float(close.rolling(20).std().iloc[-1])
        bb_width = (rolling_std * 4) / sma_20 * 100 if sma_20 > 0 else 0

        # Fundamentals
        market_cap = info.get('marketCap', 0)
        revenue = info.get('totalRevenue', 0)
        fcf = info.get('freeCashflow', 0)
        revenue_growth = info.get('revenueGrowth', 0) or 0
        gross_margins = info.get('grossMargins', 0) or 0
        operating_margins = info.get('operatingMargins', 0) or 0
        ps_ratio = info.get('priceToSalesTrailing12Months', None)
        pe_ratio = info.get('trailingPE', None)
        eps = info.get('trailingEps', None)
        beta = info.get('beta', 1.0)
        short_percent = info.get('shortPercentOfFloat', 0) or 0
        enterprise_value = info.get('enterpriseValue', 0)

        # Derived metrics
        ev_revenue = None
        if enterprise_value and revenue and revenue > 0:
            ev_revenue = round(enterprise_value / revenue, 1)

        fcf_margin_pct = None
        if fcf and revenue and revenue > 0:
            fcf_margin_pct = round((fcf / revenue) * 100, 1)

        # Earnings date
        earnings_date = None
        try:
            ed_df = t.get_earnings_dates(limit=4)
            if ed_df is not None and not ed_df.empty:
                now = pd.Timestamp.now(tz=ed_df.index[0].tzinfo) if ed_df.index[0].tzinfo else pd.Timestamp.now()
                future_dates = ed_df[ed_df.index >= now]
                if not future_dates.empty:
                    earnings_date = future_dates.index[0]
                else:
                    earnings_date = ed_df.index[0]
        except Exception:
            pass

        days_to_earnings = None
        if earnings_date is not None:
            try:
                ed = earnings_date.date() if hasattr(earnings_date, 'date') else pd.Timestamp(earnings_date).date()
                days_to_earnings = (ed - datetime.today().date()).days
            except Exception:
                pass

        # P4: Weekly timeframe alignment — fetch 2y weekly bars for SMA20 alignment
        weekly_above_sma20 = None
        try:
            hist_wk = t.history(period="2y", interval="1wk")
            if not hist_wk.empty and len(hist_wk) >= 20:
                wk_close = hist_wk['Close']
                weekly_sma20 = float(wk_close.rolling(20).mean().iloc[-1])
                weekly_above_sma20 = float(wk_close.iloc[-1]) > weekly_sma20
        except Exception:
            pass

        # IV, IV Rank, and Whale Flow — all from a single options chain fetch
        iv_30d = None
        iv_rank = None
        fetched_chains = []   # list of (expiry, chain) tuples reused by whale detector
        options_dates = []
        try:
            options_dates = list(t.options) if t.options else []
        except Exception:
            pass

        if options_dates:
            # Fetch up to 3 expiry chains — one network call each, results cached for whale
            for exp in options_dates[:3]:
                try:
                    chain = t.option_chain(exp)
                    fetched_chains.append((exp, chain))
                except Exception:
                    continue

            # Compute IV from nearest chain
            if fetched_chains:
                try:
                    _, nearest_chain = fetched_chains[0]
                    calls = nearest_chain.calls
                    if not calls.empty and 'impliedVolatility' in calls.columns:
                        current_iv = float(calls['impliedVolatility'].median() * 100)
                        iv_30d = round(current_iv, 1)
                        # P1: Real IV rank from stored history (≥30 obs); fallback synthetic
                        iv_rank = None
                        if DB_HISTORY_AVAILABLE:
                            try:
                                iv_hist = get_iv_history(ticker, days=365)
                                iv_vals = [v for _, v in iv_hist if v is not None]
                                if len(iv_vals) >= 30:
                                    iv_52w_low = min(iv_vals)
                                    iv_52w_high = max(iv_vals)
                                    if iv_52w_high > iv_52w_low:
                                        iv_rank = round(min(100, max(0, (current_iv - iv_52w_low) / (iv_52w_high - iv_52w_low) * 100)), 1)
                            except Exception:
                                pass
                        if iv_rank is None:
                            # Fallback: synthetic range from realized volatility
                            hist_vol = float(close.pct_change().rolling(20).std().iloc[-1] * np.sqrt(252) * 100)
                            iv_52w_low = hist_vol * 0.6
                            iv_52w_high = hist_vol * 1.8
                            if iv_52w_high > iv_52w_low:
                                iv_rank = round(min(100, max(0, (current_iv - iv_52w_low) / (iv_52w_high - iv_52w_low) * 100)), 1)
                except Exception:
                    pass

        # ── WHALE FLOW DETECTION ──
        # Pass pre-fetched chains — zero additional network calls
        whale_data = {"whale_score": 0, "whale_signals": [], "pc_ratio": None,
                      "unusual_calls": 0, "unusual_puts": 0, "whale_bias": "neutral",
                      "top_flow": []}
        try:
            if fetched_chains:
                whale_data = detect_whale_flow_from_chains(fetched_chains, price)
        except Exception:
            pass

        # Performance calculations
        perf_1y = round(((price / price_1y_ago) - 1) * 100, 1) if price_1y_ago > 0 else 0
        perf_3m = round(((price / price_3m_ago) - 1) * 100, 1) if price_3m_ago > 0 else 0
        perf_1m = round(((price / price_1m_ago) - 1) * 100, 1) if price_1m_ago > 0 else 0
        pct_from_high = round(((price / price_52w_high) - 1) * 100, 1)

        # P5: Short interest delta — covering shorts = squeeze setup
        short_delta = None
        if DB_HISTORY_AVAILABLE:
            try:
                si_trend = get_short_interest_trend(ticker, days=60)
                short_delta = si_trend.get("delta")  # negative = covering
            except Exception:
                pass

        return {
            "ticker": ticker,
            "price": round(price, 2),
            "market_cap": market_cap,
            "market_cap_b": round(market_cap / 1e9, 1) if market_cap else None,
            "revenue_b": round(revenue / 1e9, 2) if revenue else None,
            "revenue_growth_pct": round(revenue_growth * 100, 1) if revenue_growth else None,
            "gross_margin_pct": round(gross_margins * 100, 1) if gross_margins else None,
            "operating_margin_pct": round(operating_margins * 100, 1) if operating_margins else None,
            "fcf_m": round(fcf / 1e6, 0) if fcf else None,
            "fcf_margin_pct": fcf_margin_pct,
            "ps_ratio": round(ps_ratio, 1) if ps_ratio else None,
            "pe_ratio": round(pe_ratio, 1) if pe_ratio else None,
            "ev_revenue": ev_revenue,
            "eps": eps,
            "beta": round(beta, 2) if beta else None,
            "short_pct": round(short_percent * 100, 1),
            "rsi": round(rsi_val, 1),
            "sma_20": round(sma_20, 2),
            "sma_50": round(sma_50, 2) if sma_50 else None,
            "sma_200": round(sma_200, 2) if sma_200 else None,
            "bb_width": round(bb_width, 1),
            "vol_ratio": round(vol_ratio, 2),
            "perf_1y": perf_1y,
            "perf_3m": perf_3m,
            "perf_1m": perf_1m,
            "pct_from_52w_high": pct_from_high,
            "price_52w_high": round(price_52w_high, 2),
            "price_52w_low": round(price_52w_low, 2),
            "iv_30d": iv_30d,
            "iv_rank": iv_rank,
            "days_to_earnings": days_to_earnings,
            "price_above_sma20": price > sma_20,
            "price_above_sma50": price > sma_50 if sma_50 else None,
            "price_above_sma200": price > sma_200 if sma_200 else None,
            # P4: Weekly timeframe alignment
            "weekly_above_sma20": weekly_above_sma20,
            # P5: Short interest delta
            "short_delta": short_delta,
            # Whale flow
            "whale_score": whale_data.get("whale_score", 0),
            "whale_signals": whale_data.get("whale_signals", []),
            "whale_bias": whale_data.get("whale_bias", "neutral"),
            "pc_ratio": whale_data.get("pc_ratio"),
            "unusual_calls": whale_data.get("unusual_calls", 0),
            "unusual_puts": whale_data.get("unusual_puts", 0),
            "top_flow": whale_data.get("top_flow", []),
            "_ticker_obj": t,  # Pass through for intel layers (not stored in DB)
            "_fetched_chains": fetched_chains,  # Pass through for timing layer (not stored in DB)
        }
    except Exception as e:
        return None


# ─────────────────────────────────────────────
# WHALE FLOW DETECTION
# ─────────────────────────────────────────────

def detect_whale_flow_from_chains(fetched_chains, current_price):
    """
    Detect unusual options activity from pre-fetched chain data.
    Takes list of (expiry, chain) tuples — zero additional network calls.
    """
    signals = []
    unusual_calls = 0
    unusual_puts = 0
    total_call_volume = 0
    total_put_volume = 0
    top_flow = []

    for exp, chain in fetched_chains:
        for side, df in [("call", chain.calls), ("put", chain.puts)]:
            if df.empty:
                continue
            for _, row in df.iterrows():
                strike = _safe_num(row.get("strike", 0))
                vol = _safe_int(row.get("volume", 0))
                oi = _safe_int(row.get("openInterest", 0))
                iv = _safe_num(row.get("impliedVolatility", 0))
                bid = _safe_num(row.get("bid", 0))
                ask = _safe_num(row.get("ask", 0))
                itm = row.get("inTheMoney", False)
                mid_price = (bid + ask) / 2 if ask > 0 else _safe_num(row.get("lastPrice", 0))
                premium_total = vol * mid_price * 100
                if side == "call":
                    total_call_volume += vol
                else:
                    total_put_volume += vol
                vol_oi_ratio = vol / oi if oi > 0 else (vol if vol > 0 else 0)
                is_unusual = False
                if vol > 500 and vol_oi_ratio > 3:
                    is_unusual = True
                    if side == "call": unusual_calls += 1
                    else: unusual_puts += 1
                otm_distance = abs(strike - current_price) / current_price * 100
                if not itm and vol > 1000 and otm_distance > 5 and premium_total > 50000:
                    is_unusual = True
                    if side == "call": unusual_calls += 1
                    else: unusual_puts += 1
                if premium_total > 200000 and vol > 200:
                    is_unusual = True
                if is_unusual and premium_total > 10000:
                    top_flow.append({
                        "type": side, "strike": strike, "expiry": exp,
                        "volume": vol, "open_interest": oi,
                        "vol_oi_ratio": round(vol_oi_ratio, 1),
                        "premium_total": round(premium_total, 0),
                        "iv": round(iv * 100, 1),
                        "otm_pct": round(otm_distance, 1), "itm": itm,
                    })

    top_flow.sort(key=lambda x: x["premium_total"], reverse=True)
    top_flow = top_flow[:5]
    pc_ratio = round(total_put_volume / total_call_volume, 2) if total_call_volume > 0 else None
    total_unusual = unusual_calls + unusual_puts

    if unusual_calls > unusual_puts + 2: whale_bias = "bullish"
    elif unusual_puts > unusual_calls + 2: whale_bias = "bearish"
    elif total_unusual > 0: whale_bias = "active"
    else: whale_bias = "neutral"

    if unusual_calls > 0:
        signals.append(f"🐋 {unusual_calls} unusual call{'s' if unusual_calls > 1 else ''} detected")
    if unusual_puts > 0:
        signals.append(f"🐋 {unusual_puts} unusual put{'s' if unusual_puts > 1 else ''} detected")
    if top_flow:
        biggest = top_flow[0]
        signals.append(f"💰 Largest flow: ${biggest['premium_total']:,.0f} in ${biggest['strike']:.0f} {biggest['type']}s ({biggest['expiry']})")
    if pc_ratio is not None:
        if pc_ratio > 1.5: signals.append(f"📊 High P/C ratio ({pc_ratio:.2f}) — heavy put activity")
        elif pc_ratio < 0.5: signals.append(f"📊 Low P/C ratio ({pc_ratio:.2f}) — heavy call activity")

    whale_score = 0
    if total_unusual >= 8: whale_score += 40
    elif total_unusual >= 5: whale_score += 30
    elif total_unusual >= 3: whale_score += 20
    elif total_unusual >= 1: whale_score += 10
    if top_flow:
        mp = top_flow[0]["premium_total"]
        if mp > 1000000: whale_score += 30
        elif mp > 500000: whale_score += 20
        elif mp > 100000: whale_score += 15
        elif mp > 50000: whale_score += 8
    if total_unusual > 0:
        if unusual_calls > 0 and unusual_puts == 0: whale_score += 20
        elif unusual_puts > 0 and unusual_calls == 0: whale_score += 20
        elif abs(unusual_calls - unusual_puts) > 3: whale_score += 10
    if pc_ratio is not None:
        if pc_ratio > 2.0 or pc_ratio < 0.3: whale_score += 10
        elif pc_ratio > 1.5 or pc_ratio < 0.5: whale_score += 5

    return {
        "whale_score": min(100, whale_score), "whale_signals": signals,
        "whale_bias": whale_bias, "pc_ratio": pc_ratio,
        "unusual_calls": unusual_calls, "unusual_puts": unusual_puts, "top_flow": top_flow,
    }


def detect_whale_flow(ticker_obj, current_price, expiry_dates):
    """
    Detect unusual options activity (whale flow) from existing chain data.
    Zero additional API calls — uses the same data we fetch for IV.

    Detects:
    1. Volume >> Open Interest on a strike (new positions being opened)
    2. Large absolute volume on OTM options (smart money bets)
    3. Put/Call ratio skew (institutional hedging or directional bets)
    4. Premium sweeps (big $ flowing into specific strikes)

    Returns dict with whale_score (0-100), signals, bias, and top flow details.
    """
    signals = []
    unusual_calls = 0
    unusual_puts = 0
    total_call_volume = 0
    total_put_volume = 0
    total_call_oi = 0
    total_put_oi = 0
    top_flow = []  # Top unusual trades

    for exp in expiry_dates:
        try:
            chain = ticker_obj.option_chain(exp)
        except Exception:
            continue

        for side, df in [("call", chain.calls), ("put", chain.puts)]:
            if df.empty:
                continue

            for _, row in df.iterrows():
                strike = _safe_num(row.get("strike", 0))
                vol = _safe_int(row.get("volume", 0))
                oi = _safe_int(row.get("openInterest", 0))
                iv = _safe_num(row.get("impliedVolatility", 0))
                bid = _safe_num(row.get("bid", 0))
                ask = _safe_num(row.get("ask", 0))
                itm = row.get("inTheMoney", False)

                mid_price = (bid + ask) / 2 if ask > 0 else _safe_num(row.get("lastPrice", 0))
                premium_total = vol * mid_price * 100  # Total $ flowing

                # Track totals
                if side == "call":
                    total_call_volume += vol
                    total_call_oi += oi
                else:
                    total_put_volume += vol
                    total_put_oi += oi

                # ── Detection 1: Volume >> Open Interest (new positions) ──
                # If volume is 3x+ open interest, these are NEW positions being opened
                vol_oi_ratio = vol / oi if oi > 0 else (vol if vol > 0 else 0)

                is_unusual = False

                if vol > 500 and vol_oi_ratio > 3:
                    is_unusual = True
                    if side == "call":
                        unusual_calls += 1
                    else:
                        unusual_puts += 1

                # ── Detection 2: Large OTM bets (conviction trades) ──
                otm_distance = abs(strike - current_price) / current_price * 100
                if not itm and vol > 1000 and otm_distance > 5 and premium_total > 50000:
                    is_unusual = True
                    if side == "call":
                        unusual_calls += 1
                    else:
                        unusual_puts += 1

                # ── Detection 3: Premium sweeps (big money) ──
                if premium_total > 200000 and vol > 200:
                    is_unusual = True

                # Record top flow
                if is_unusual and premium_total > 10000:
                    top_flow.append({
                        "type": side,
                        "strike": strike,
                        "expiry": exp,
                        "volume": vol,
                        "open_interest": oi,
                        "vol_oi_ratio": round(vol_oi_ratio, 1),
                        "premium_total": round(premium_total, 0),
                        "iv": round(iv * 100, 1),
                        "otm_pct": round(otm_distance, 1),
                        "itm": itm,
                    })

    # Sort top flow by premium
    top_flow.sort(key=lambda x: x["premium_total"], reverse=True)
    top_flow = top_flow[:5]  # Keep top 5

    # ── Put/Call Ratio ──
    pc_ratio = None
    if total_call_volume > 0:
        pc_ratio = round(total_put_volume / total_call_volume, 2)

    # ── Determine whale bias ──
    if unusual_calls > unusual_puts + 2:
        whale_bias = "bullish"
    elif unusual_puts > unusual_calls + 2:
        whale_bias = "bearish"
    elif unusual_calls > 0 or unusual_puts > 0:
        whale_bias = "active"
    else:
        whale_bias = "neutral"

    # ── Build signals list ──
    if unusual_calls > 0:
        signals.append(f"🐋 {unusual_calls} unusual call{'s' if unusual_calls > 1 else ''} detected")
    if unusual_puts > 0:
        signals.append(f"🐋 {unusual_puts} unusual put{'s' if unusual_puts > 1 else ''} detected")
    if top_flow:
        biggest = top_flow[0]
        signals.append(
            f"💰 Largest flow: ${biggest['premium_total']:,.0f} in "
            f"${biggest['strike']:.0f} {biggest['type']}s ({biggest['expiry']})"
        )
    if pc_ratio is not None:
        if pc_ratio > 1.5:
            signals.append(f"📊 High P/C ratio ({pc_ratio:.2f}) — heavy put activity")
        elif pc_ratio < 0.5:
            signals.append(f"📊 Low P/C ratio ({pc_ratio:.2f}) — heavy call activity")

    # ── Compute whale score (0-100) ──
    whale_score = 0

    # Unusual activity count (max 40 pts)
    total_unusual = unusual_calls + unusual_puts
    if total_unusual >= 8:
        whale_score += 40
    elif total_unusual >= 5:
        whale_score += 30
    elif total_unusual >= 3:
        whale_score += 20
    elif total_unusual >= 1:
        whale_score += 10

    # Premium size (max 30 pts)
    if top_flow:
        max_premium = top_flow[0]["premium_total"]
        if max_premium > 1000000:
            whale_score += 30
        elif max_premium > 500000:
            whale_score += 20
        elif max_premium > 100000:
            whale_score += 15
        elif max_premium > 50000:
            whale_score += 8

    # Directional conviction — one-sided flow is stronger signal (max 20 pts)
    if total_unusual > 0:
        if unusual_calls > 0 and unusual_puts == 0:
            whale_score += 20  # Pure bullish whale flow
        elif unusual_puts > 0 and unusual_calls == 0:
            whale_score += 20  # Pure bearish whale flow
        elif abs(unusual_calls - unusual_puts) > 3:
            whale_score += 10  # Skewed but mixed

    # P/C ratio extremes (max 10 pts)
    if pc_ratio is not None:
        if pc_ratio > 2.0 or pc_ratio < 0.3:
            whale_score += 10
        elif pc_ratio > 1.5 or pc_ratio < 0.5:
            whale_score += 5

    return {
        "whale_score": min(100, whale_score),
        "whale_signals": signals,
        "whale_bias": whale_bias,
        "pc_ratio": pc_ratio,
        "unusual_calls": unusual_calls,
        "unusual_puts": unusual_puts,
        "top_flow": top_flow,
    }


# ─────────────────────────────────────────────
# SCORING v2 — LONG-TERM VALUE
# ─────────────────────────────────────────────

def _score_component(raw_score_0_to_1, weight):
    """Scale a 0-1 raw score by its weight."""
    return round(max(0, min(1, raw_score_0_to_1)) * weight, 1)


def score_long_term(row, weights=None):
    """
    Score a stock for long-term value (max 100).
    Returns (total_score, reasons_list, breakdown_dict).

    Each component returns a 0-1 raw score, then scaled by weight.
    Negative signals can push a component to 0 or below (clamped).
    """
    w = weights or _active_lt_weights
    score = 0
    reasons = []
    breakdown = {}

    # ── 1. RULE OF 40 (growth% + margin%) ──
    rg = row.get("revenue_growth_pct") or 0
    om = row.get("operating_margin_pct") or 0
    gm = row.get("gross_margin_pct") or 0
    # Use operating margin if available, else estimate from gross margin
    margin = om if om != 0 else (gm * 0.5)  # rough proxy
    rule_of_40 = rg + margin

    if rule_of_40 >= 60:
        raw = 1.0
        reasons.append(f"🚀 Rule of 40: {rule_of_40:.0f} (elite — {rg:.0f}% growth + {margin:.0f}% margin)")
    elif rule_of_40 >= 40:
        raw = 0.7 + 0.3 * ((rule_of_40 - 40) / 20)
        reasons.append(f"✅ Rule of 40: {rule_of_40:.0f} (passing — {rg:.0f}% growth + {margin:.0f}% margin)")
    elif rule_of_40 >= 25:
        raw = 0.3 + 0.4 * ((rule_of_40 - 25) / 15)
        reasons.append(f"📊 Rule of 40: {rule_of_40:.0f} (below threshold)")
    elif rule_of_40 >= 0:
        raw = 0.1 + 0.2 * (rule_of_40 / 25)
    else:
        raw = 0
        reasons.append(f"⚠️ Rule of 40: {rule_of_40:.0f} (negative — shrinking inefficiently)")

    pts = _score_component(raw, w["rule_of_40"])
    breakdown["rule_of_40"] = {"points": pts, "max": w["rule_of_40"], "raw_value": round(rule_of_40, 1), "raw": round(raw, 4)}
    score += pts

    # ── 2. RELATIVE VALUATION (EV/Revenue relative to growth) ──
    ev_rev = row.get("ev_revenue") or row.get("ps_ratio") or 999
    growth_for_val = max(rg, 1)  # avoid div by zero

    # Growth-adjusted valuation: lower EV/Rev per unit of growth = better
    val_ratio = ev_rev / growth_for_val if growth_for_val > 0 else 999

    if ev_rev < 3 and rg > 10:
        raw = 1.0
        reasons.append(f"💎 Deep value: {ev_rev:.1f}x EV/Rev with {rg:.0f}% growth")
    elif val_ratio < 0.3 and ev_rev < 15:
        raw = 0.85
        reasons.append(f"✅ Fair value: {ev_rev:.1f}x EV/Rev for {rg:.0f}% growth")
    elif val_ratio < 0.5 and ev_rev < 20:
        raw = 0.6
    elif ev_rev < 10:
        raw = 0.4
    elif ev_rev < 20:
        raw = 0.2
    else:
        raw = max(0, 0.1 - (ev_rev - 20) / 100)
        if ev_rev > 30:
            reasons.append(f"💸 Expensive: {ev_rev:.1f}x EV/Rev")

    pts = _score_component(raw, w["valuation"])
    breakdown["valuation"] = {"points": pts, "max": w["valuation"], "raw_value": round(ev_rev, 1), "raw": round(raw, 4)}
    score += pts

    # ── 3. FCF MARGIN (cash generation efficiency, not absolute) ──
    fcf_margin = row.get("fcf_margin_pct")
    fcf_m = row.get("fcf_m") or 0

    if fcf_margin is not None:
        if fcf_margin >= 25:
            raw = 1.0
            reasons.append(f"💵 Excellent FCF margin ({fcf_margin:.0f}%)")
        elif fcf_margin >= 15:
            raw = 0.7 + 0.3 * ((fcf_margin - 15) / 10)
        elif fcf_margin >= 5:
            raw = 0.3 + 0.4 * ((fcf_margin - 5) / 10)
        elif fcf_margin >= 0:
            raw = 0.15
        else:
            raw = 0
            if fcf_margin < -10:
                reasons.append(f"🔴 Cash burn: FCF margin {fcf_margin:.0f}%")
    else:
        # Fall back to absolute FCF with size-awareness
        rev_b = row.get("revenue_b") or 1
        if fcf_m > 0:
            estimated_margin = (fcf_m / (rev_b * 1000)) * 100 if rev_b > 0 else 0
            raw = min(1.0, max(0, estimated_margin / 25))
        else:
            raw = 0

    pts = _score_component(raw, w["fcf_margin"])
    breakdown["fcf_margin"] = {"points": pts, "max": w["fcf_margin"],
                                "raw_value": fcf_margin if fcf_margin is not None else None, "raw": round(raw, 4)}
    score += pts

    # ── 4. TECHNICAL TREND (SMA positioning) ──
    price_val = row.get("price", 0)
    sma20 = row.get("sma_20")
    sma50 = row.get("sma_50")
    sma200 = row.get("sma_200")

    trend_score = 0
    trend_signals = 0
    trend_max = 0

    if sma200 is not None:
        trend_max += 2
        if price_val > sma200:
            trend_score += 2
            trend_signals += 1
        else:
            trend_signals -= 1

    if sma50 is not None:
        trend_max += 1.5
        if price_val > sma50:
            trend_score += 1.5
            trend_signals += 1

    if sma20 is not None:
        trend_max += 1
        if price_val > sma20:
            trend_score += 1
            trend_signals += 0.5

    # Golden cross bonus (50 > 200)
    if sma50 and sma200 and sma50 > sma200:
        trend_score += 0.5
        trend_max += 0.5

    if trend_max > 0:
        raw = trend_score / trend_max
    else:
        raw = 0.5

    if trend_signals >= 3:
        reasons.append("📈 Strong uptrend (above all SMAs)")
    elif trend_signals <= -1:
        reasons.append("📉 Below key moving averages — weak trend")

    pts = _score_component(raw, w["trend"])
    breakdown["trend"] = {"points": pts, "max": w["trend"], "raw_value": round(trend_score, 1), "raw": round(raw, 4)}
    score += pts

    # ── 5. EARNINGS QUALITY (positive EPS, good margins) ──
    eps = row.get("eps")
    pe = row.get("pe_ratio")

    quality_raw = 0
    if eps is not None and eps > 0:
        quality_raw += 0.4
        if pe and 10 < pe < 40:
            quality_raw += 0.2
            reasons.append(f"✅ Profitable: P/E {pe:.0f}")
        elif pe and pe > 0:
            quality_raw += 0.1
    elif rg > 30:
        quality_raw += 0.2  # pre-profit but growing fast is OK

    if gm > 75:
        quality_raw += 0.3
    elif gm > 60:
        quality_raw += 0.2
    elif gm > 40:
        quality_raw += 0.1
    elif gm > 0:
        quality_raw += 0.05

    raw = min(1.0, quality_raw)

    pts = _score_component(raw, w["earnings_quality"])
    breakdown["earnings_quality"] = {"points": pts, "max": w["earnings_quality"], "raw": round(raw, 4)}
    score += pts

    # ── 6. DISCOUNT + MOMENTUM ──
    disc = row.get("pct_from_52w_high") or 0
    perf_3m = row.get("perf_3m") or 0
    perf_1m = row.get("perf_1m") or 0

    # Discount is valuable only if momentum is turning positive (not falling knife)
    discount_raw = 0
    if disc < -30:
        discount_raw = 0.6
        if perf_1m > 0:
            discount_raw = 1.0
            reasons.append(f"🏷️ Down {abs(disc):.0f}% from high but rebounding (+{perf_1m:.0f}% this month)")
        else:
            reasons.append(f"🏷️ Down {abs(disc):.0f}% from high — potential value or value trap")
    elif disc < -15:
        discount_raw = 0.3
        if perf_1m > 0:
            discount_raw = 0.6
    elif disc > -5:
        # Near highs — strong if momentum is positive
        if perf_3m > 10:
            discount_raw = 0.5
            reasons.append(f"💪 Near highs with strong momentum (+{perf_3m:.0f}% 3m)")
        else:
            discount_raw = 0.2

    # P5: Short interest delta modifier
    # Covering shorts (negative delta) = squeeze setup → boost score
    # Shorts piling in (positive delta) = headwind → reduce score
    short_delta = row.get("short_delta")
    if short_delta is not None:
        if short_delta < -5:
            discount_raw = min(1.0, discount_raw + 0.20)
            reasons.append(f"🔻 Shorts covering ({short_delta:+.1f}pp 60d) — squeeze setup")
        elif short_delta < -2:
            discount_raw = min(1.0, discount_raw + 0.10)
        elif short_delta > 5:
            discount_raw = max(0, discount_raw - 0.15)
            reasons.append(f"📈 Shorts building ({short_delta:+.1f}pp 60d) — headwind")
        elif short_delta > 2:
            discount_raw = max(0, discount_raw - 0.07)

    raw = min(1.0, discount_raw)

    pts = _score_component(raw, w["discount_momentum"])
    breakdown["discount_momentum"] = {"points": pts, "max": w["discount_momentum"],
                                       "raw_value": round(disc, 1), "raw": round(raw, 4)}
    score += pts

    return round(score, 1), reasons, breakdown


# ─────────────────────────────────────────────
# SCORING v2 — OPTIONS / SHORT-TERM
# ─────────────────────────────────────────────

def score_options(row, weights=None):
    """
    Score a stock for short-term options play potential (max 100).
    Returns (total_score, reasons_list, breakdown_dict).
    """
    w = weights or _active_opt_weights
    score = 0
    reasons = []
    breakdown = {}

    # ── 1. EARNINGS CATALYST ──
    dte = row.get("days_to_earnings")
    if dte is not None and dte > 0:
        if 5 <= dte <= 14:
            raw = 1.0
            reasons.append(f"🎯 Earnings in {dte} days — prime options window")
        elif 15 <= dte <= 30:
            raw = 0.7
            reasons.append(f"📅 Earnings in {dte} days — building toward catalyst")
        elif 1 <= dte <= 4:
            raw = 0.6
            reasons.append(f"⚡ Earnings imminent ({dte}d) — elevated risk/reward")
        elif 31 <= dte <= 45:
            raw = 0.3
        else:
            raw = 0.1
    else:
        raw = 0.1  # No catalyst is not zero, but low

    pts = _score_component(raw, w["earnings_catalyst"])
    breakdown["earnings_catalyst"] = {"points": pts, "max": w["earnings_catalyst"],
                                       "raw_value": dte, "raw": round(raw, 4)}
    score += pts

    # ── 2. IV CONTEXT (IV Rank, not raw IV) ──
    iv = row.get("iv_30d") or 0
    ivr = row.get("iv_rank")

    if ivr is not None:
        # IV Rank tells us if IV is cheap or expensive vs its own history
        if ivr < 20:
            raw = 0.9  # IV is historically low — options are cheap (good for buying)
            reasons.append(f"🟢 IV Rank {ivr:.0f}% — options cheap, good for buying premium")
        elif ivr < 40:
            raw = 0.6
        elif ivr > 80:
            raw = 0.8  # Very high IV — good for selling premium
            reasons.append(f"🔴 IV Rank {ivr:.0f}% — options expensive, good for selling premium")
        elif ivr > 60:
            raw = 0.5
        else:
            raw = 0.3  # Mid-range IV — not ideal for either
    else:
        # Fall back to raw IV
        if iv > 60:
            raw = 0.7
            reasons.append(f"🌋 High IV ({iv:.0f}%) — volatility play")
        elif iv > 40:
            raw = 0.4
        else:
            raw = 0.2

    pts = _score_component(raw, w["iv_context"])
    breakdown["iv_context"] = {"points": pts, "max": w["iv_context"],
                                "raw_value": ivr if ivr is not None else iv, "raw": round(raw, 4)}
    score += pts

    # ── 3. DIRECTIONAL CONVICTION ──
    rsi = row.get("rsi") or 50
    above_sma20 = row.get("price_above_sma20")
    above_sma50 = row.get("price_above_sma50")
    vr = row.get("vol_ratio") or 1.0

    # Build directional signal strength
    bull_signals = 0
    bear_signals = 0

    if rsi < 30:
        bull_signals += 2  # Oversold = mean reversion bullish
    elif rsi < 40:
        bull_signals += 1
    elif rsi > 70:
        bear_signals += 2  # Overbought = mean reversion bearish
    elif rsi > 60:
        bear_signals += 1

    if above_sma20:
        bull_signals += 1
    else:
        bear_signals += 1
    if above_sma50:
        bull_signals += 1
    else:
        bear_signals += 1

    # Volume confirms direction
    if vr > 1.5:
        max_dir = max(bull_signals, bear_signals)
        if max_dir == bull_signals:
            bull_signals += 1
        else:
            bear_signals += 1

    # P4: Weekly timeframe alignment confirms or contradicts daily bias
    weekly_above = row.get("weekly_above_sma20")
    if weekly_above is True:
        bull_signals += 1
    elif weekly_above is False:
        bear_signals += 1

    total_conviction = max(bull_signals, bear_signals)
    direction = "bullish" if bull_signals > bear_signals else "bearish" if bear_signals > bull_signals else "neutral"

    if total_conviction >= 4:
        raw = 1.0
        reasons.append(f"💪 Strong {direction} conviction (RSI {rsi:.0f}, {'above' if above_sma20 else 'below'} SMA20, vol {vr:.1f}x)")
    elif total_conviction >= 3:
        raw = 0.7
        reasons.append(f"📊 Moderate {direction} lean")
    elif total_conviction >= 2:
        raw = 0.4
    else:
        raw = 0.15  # No clear direction

    pts = _score_component(raw, w["directional"])
    breakdown["directional"] = {"points": pts, "max": w["directional"],
                                 "raw_value": {"direction": direction, "conviction": total_conviction}, "raw": round(raw, 4)}
    score += pts

    # ── 4. TECHNICAL SETUP ──
    bb = row.get("bb_width") or 20

    tech_raw = 0
    # BB squeeze (potential breakout)
    if bb < 8:
        tech_raw += 0.5
        reasons.append(f"🗜️ Tight BB squeeze ({bb:.1f}%) — breakout imminent")
    elif bb < 12:
        tech_raw += 0.3
    elif bb < 15:
        tech_raw += 0.15

    # RSI extremes (mean reversion or momentum continuation)
    if rsi < 25 or rsi > 80:
        tech_raw += 0.35
        if rsi < 25:
            reasons.append(f"🟢 Deeply oversold RSI ({rsi:.0f})")
        else:
            reasons.append(f"🔴 Extremely overbought RSI ({rsi:.0f})")
    elif rsi < 35 or rsi > 70:
        tech_raw += 0.2

    raw = min(1.0, tech_raw)

    pts = _score_component(raw, w["technical"])
    breakdown["technical"] = {"points": pts, "max": w["technical"],
                               "raw_value": {"bb_width": bb, "rsi": rsi}, "raw": round(raw, 4)}
    score += pts

    # ── 5. LIQUIDITY ──
    # Higher liquidity = easier to execute, tighter spreads
    beta_val = row.get("beta") or 1.0
    mcap = row.get("market_cap_b") or 0

    if mcap > 50:
        raw = 1.0  # Mega-cap = very liquid options market
    elif mcap > 20:
        raw = 0.8
    elif mcap > 5:
        raw = 0.5
    elif mcap > 1:
        raw = 0.3
    else:
        raw = 0.1
        reasons.append("⚠️ Small cap — options may have wide spreads")

    pts = _score_component(raw, w["liquidity"])
    breakdown["liquidity"] = {"points": pts, "max": w["liquidity"],
                               "raw_value": mcap, "raw": round(raw, 4)}
    score += pts

    # ── 6. ASYMMETRY POTENTIAL (+ WHALE FLOW) ──
    short_pct = row.get("short_pct") or 0
    whale_score_raw = row.get("whale_score") or 0
    whale_bias = row.get("whale_bias") or "neutral"

    asym_raw = 0

    # Short squeeze potential
    if short_pct > 15:
        asym_raw += 0.3
        reasons.append(f"📌 High short interest ({short_pct:.0f}%) — squeeze potential")
    elif short_pct > 8:
        asym_raw += 0.15

    # Beta amplification
    if beta_val > 1.8:
        asym_raw += 0.2
        reasons.append(f"⚡ High beta ({beta_val:.1f}) — amplified moves")
    elif beta_val > 1.3:
        asym_raw += 0.1

    # Whale flow integration — this is the big new signal
    if whale_score_raw >= 50:
        asym_raw += 0.5
        reasons.append(f"🐋 Strong whale flow (score {whale_score_raw}) — institutional positioning detected")
    elif whale_score_raw >= 30:
        asym_raw += 0.3
        reasons.append(f"🐋 Moderate whale activity (score {whale_score_raw})")
    elif whale_score_raw >= 10:
        asym_raw += 0.15

    # Whale directional alignment with technical signals boosts conviction
    if whale_bias in ("bullish", "bearish") and whale_bias == direction:
        asym_raw += 0.15  # Whales agree with technicals

    raw = min(1.0, asym_raw)

    pts = _score_component(raw, w["asymmetry"])
    breakdown["asymmetry"] = {"points": pts, "max": w["asymmetry"],
                               "raw_value": {"short_pct": short_pct, "beta": beta_val}, "raw": round(raw, 4)}
    score += pts

    return round(score, 1), reasons, breakdown


# ─────────────────────────────────────────────
# OPTIONS PLAY BUILDER (unchanged from v1)
# ─────────────────────────────────────────────

def fetch_options_chain(ticker):
    """Fetch full options chain data for play building."""
    try:
        t = yf.Ticker(ticker)
        expiry_dates = t.options
        if not expiry_dates:
            return None

        chains = []
        for exp in expiry_dates[:6]:
            try:
                chain = t.option_chain(exp)
                for _, r in chain.calls.iterrows():
                    chains.append({
                        "type": "call", "expiry": exp,
                        "strike": _safe_num(r["strike"]),
                        "lastPrice": _safe_num(r.get("lastPrice", 0)),
                        "bid": _safe_num(r.get("bid", 0)),
                        "ask": _safe_num(r.get("ask", 0)),
                        "volume": _safe_num(r.get("volume", 0)),
                        "openInterest": _safe_num(r.get("openInterest", 0)),
                        "iv": _safe_num(r.get("impliedVolatility", 0)),
                        "inTheMoney": r.get("inTheMoney", False),
                    })
                for _, r in chain.puts.iterrows():
                    chains.append({
                        "type": "put", "expiry": exp,
                        "strike": _safe_num(r["strike"]),
                        "lastPrice": _safe_num(r.get("lastPrice", 0)),
                        "bid": _safe_num(r.get("bid", 0)),
                        "ask": _safe_num(r.get("ask", 0)),
                        "volume": _safe_num(r.get("volume", 0)),
                        "openInterest": _safe_num(r.get("openInterest", 0)),
                        "iv": _safe_num(r.get("impliedVolatility", 0)),
                        "inTheMoney": r.get("inTheMoney", False),
                    })
            except Exception:
                continue

        return chains if chains else None
    except Exception:
        return None


def calc_expected_move(price, iv, days):
    """Calculate expected price move based on IV and days to expiry."""
    if not iv or not days or days <= 0:
        return 0
    return price * (iv / 100) * np.sqrt(days / 365)


def _passes_liquidity_filter(strike, min_volume=10, min_oi=50, max_spread_pct=25):
    """Check if a strike meets minimum liquidity requirements."""
    vol = _safe_num(strike.get("volume", 0))
    oi = _safe_num(strike.get("openInterest", 0))
    bid = _safe_num(strike.get("bid", 0))
    ask = _safe_num(strike.get("ask", 0))

    if vol < min_volume and oi < min_oi:
        return False

    if bid > 0 and ask > 0:
        mid = (bid + ask) / 2
        if mid > 0 and ((ask - bid) / mid * 100) > max_spread_pct:
            return False

    return True


def find_best_strike(chains, option_type, expiry, price, target_delta="atm", require_liquidity=True):
    """Find the best strike for a given setup, with optional liquidity filter."""
    filtered = [c for c in chains if c["type"] == option_type and c["expiry"] == expiry]
    if not filtered:
        return None

    # Apply liquidity filter — no fallback; illiquid chains produce no play
    if require_liquidity:
        liquid = [c for c in filtered if _passes_liquidity_filter(c)]
        if not liquid:
            return None
        filtered = liquid

    if target_delta == "atm":
        return min(filtered, key=lambda x: abs(x["strike"] - price))
    elif target_delta == "otm_near":
        if option_type == "call":
            otm = [c for c in filtered if c["strike"] > price]
            target = price * 1.05
        else:
            otm = [c for c in filtered if c["strike"] < price]
            target = price * 0.95
        return min(otm, key=lambda x: abs(x["strike"] - target)) if otm else None
    elif target_delta == "otm_far":
        if option_type == "call":
            otm = [c for c in filtered if c["strike"] > price]
            target = price * 1.10
        else:
            otm = [c for c in filtered if c["strike"] < price]
            target = price * 0.90
        return min(otm, key=lambda x: abs(x["strike"] - target)) if otm else None
    elif target_delta == "itm_near":
        if option_type == "call":
            itm = [c for c in filtered if c["strike"] < price]
            target = price * 0.97
        else:
            itm = [c for c in filtered if c["strike"] > price]
            target = price * 1.03
        return min(itm, key=lambda x: abs(x["strike"] - target)) if itm else None
    return None


def find_best_expiry(chains, days_to_earnings=None):
    """Find the ideal expiry date based on catalyst timing."""
    expiries = sorted(set(c["expiry"] for c in chains))
    if not expiries:
        return None, None

    today = datetime.today().date()

    if days_to_earnings and days_to_earnings > 0:
        earnings_date = today + timedelta(days=days_to_earnings)
        post_earnings = [e for e in expiries
                         if datetime.strptime(e, "%Y-%m-%d").date() > earnings_date]
        if post_earnings:
            return post_earnings[0], "post-earnings"

    target_dte = 35
    best = min(expiries, key=lambda e: abs((datetime.strptime(e, "%Y-%m-%d").date() - today).days - target_dte))
    return best, "standard"


def generate_plays(ticker, price, chains, days_to_earnings=None, rsi=50, iv_30d=None,
                   price_above_sma20=True, price_above_sma50=True, perf_3m=0,
                   lt_score=0, opt_score=0, iv_rank=None, whale_bias="neutral"):
    """Generate specific options plays based on the setup.
    Enhanced with liquidity filters, iron condor, position sizing, and no forced fallbacks.
    """
    plays = []
    if not chains or not price:
        return plays

    expiry, expiry_reason = find_best_expiry(chains, days_to_earnings)
    if not expiry:
        return plays

    exp_date = datetime.strptime(expiry, "%Y-%m-%d").date()
    dte = (exp_date - datetime.today().date()).days
    expected_move = calc_expected_move(price, iv_30d or 30, dte)

    # Determine directional bias
    bullish_signals = 0
    bearish_signals = 0
    # RSI: symmetric treatment — deeply oversold/overbought both get strong signals
    if rsi and rsi < 25:    bullish_signals += 3  # Deeply oversold
    elif rsi and rsi < 35:  bullish_signals += 2
    elif rsi and rsi < 40:  bullish_signals += 1
    elif rsi and rsi > 80:  bearish_signals += 3  # Extremely overbought
    elif rsi and rsi > 70:  bearish_signals += 2  # Overbought
    elif rsi and rsi > 65:  bearish_signals += 1
    if price_above_sma20: bullish_signals += 1
    if price_above_sma50: bullish_signals += 1
    if perf_3m and perf_3m > 10: bullish_signals += 1
    elif perf_3m and perf_3m < -10: bearish_signals += 1

    is_earnings_play = days_to_earnings is not None and 1 <= days_to_earnings <= 30
    is_high_iv = (iv_30d or 0) > 50
    is_extreme_iv = (iv_30d or 0) > 80  # Buying premium is poor value at this IV
    bias = "bullish" if bullish_signals > bearish_signals else "bearish" if bearish_signals > bullish_signals else "neutral"

    # ── PLAY 1: Directional (Long Calls or Puts) ──
    # Skip naked long premium when IV is extreme — the credit spread (Play 6) is better then
    if bias == "bullish" and not is_extreme_iv:
        strike_opt = find_best_strike(chains, "call", expiry, price, "otm_near")
        if strike_opt:
            mid_price = (strike_opt["bid"] + strike_opt["ask"]) / 2 if strike_opt["ask"] > 0 else strike_opt["lastPrice"]
            breakeven = strike_opt["strike"] + mid_price
            max_loss = mid_price * 100
            pct_to_breakeven = ((breakeven / price) - 1) * 100

            plays.append({
                "strategy": "Long Call", "emoji": "📈", "direction": "Bullish",
                "action": f"BUY {ticker} ${strike_opt['strike']:.0f} Call",
                "expiry": expiry, "dte": dte, "strike": strike_opt["strike"],
                "entry_price": round(mid_price, 2),
                "bid": strike_opt["bid"], "ask": strike_opt["ask"],
                "breakeven": round(breakeven, 2),
                "pct_to_breakeven": round(pct_to_breakeven, 1),
                "max_loss": round(max_loss, 0), "max_gain": "Unlimited",
                "volume": _safe_int(strike_opt["volume"]),
                "open_interest": _safe_int(strike_opt["openInterest"]),
                "iv": round(strike_opt["iv"] * 100, 1),
                "rationale": f"Bullish bias — RSI {rsi:.0f}, {'above' if price_above_sma20 else 'below'} SMA20. "
                             f"{'Earnings catalyst in ' + str(days_to_earnings) + 'd. ' if is_earnings_play else ''}"
                             f"Expected move: ±${expected_move:.2f} ({expected_move/price*100:.1f}%)",
                "risk_notes": "Max loss limited to premium paid."
            })

    elif bias == "bearish" and not is_extreme_iv:
        strike_opt = find_best_strike(chains, "put", expiry, price, "otm_near")
        if strike_opt:
            mid_price = (strike_opt["bid"] + strike_opt["ask"]) / 2 if strike_opt["ask"] > 0 else strike_opt["lastPrice"]
            breakeven = strike_opt["strike"] - mid_price
            max_loss = mid_price * 100

            plays.append({
                "strategy": "Long Put", "emoji": "📉", "direction": "Bearish",
                "action": f"BUY {ticker} ${strike_opt['strike']:.0f} Put",
                "expiry": expiry, "dte": dte, "strike": strike_opt["strike"],
                "entry_price": round(mid_price, 2),
                "bid": strike_opt["bid"], "ask": strike_opt["ask"],
                "breakeven": round(breakeven, 2),
                "pct_to_breakeven": round(((price - breakeven) / price) * 100, 1),
                "max_loss": round(max_loss, 0), "max_gain": f"${breakeven * 100:,.0f}",
                "volume": _safe_int(strike_opt["volume"]),
                "open_interest": _safe_int(strike_opt["openInterest"]),
                "iv": round(strike_opt["iv"] * 100, 1),
                "rationale": f"Bearish bias — RSI {rsi:.0f}, {'above' if price_above_sma20 else 'below'} SMA20. "
                             f"{'Earnings catalyst in ' + str(days_to_earnings) + 'd. ' if is_earnings_play else ''}"
                             f"Expected move: ±${expected_move:.2f} ({expected_move/price*100:.1f}%)",
                "risk_notes": "Max loss limited to premium paid."
            })

    # ── PLAY 2: Straddle (earnings / volatility play) ──
    if is_earnings_play or (is_high_iv and bias == "neutral"):
        atm_call = find_best_strike(chains, "call", expiry, price, "atm")
        atm_put = find_best_strike(chains, "put", expiry, price, "atm")
        if atm_call and atm_put:
            call_mid = (atm_call["bid"] + atm_call["ask"]) / 2 if atm_call["ask"] > 0 else atm_call["lastPrice"]
            put_mid = (atm_put["bid"] + atm_put["ask"]) / 2 if atm_put["ask"] > 0 else atm_put["lastPrice"]
            total_premium = call_mid + put_mid
            be_up = atm_call["strike"] + total_premium
            be_down = atm_put["strike"] - total_premium
            move_needed = (total_premium / price) * 100

            plays.append({
                "strategy": "Straddle", "emoji": "🎯", "direction": "Neutral (big move expected)",
                "action": f"BUY {ticker} ${atm_call['strike']:.0f} Call + ${atm_put['strike']:.0f} Put",
                "expiry": expiry, "dte": dte, "strike": f"{atm_call['strike']:.0f}",
                "entry_price": round(total_premium, 2),
                "bid": None, "ask": None,
                "breakeven": f"${be_down:.2f} / ${be_up:.2f}",
                "pct_to_breakeven": round(move_needed, 1),
                "max_loss": round(total_premium * 100, 0), "max_gain": "Unlimited",
                "volume": _safe_int(atm_call["volume"] + atm_put["volume"]),
                "open_interest": _safe_int(atm_call["openInterest"] + atm_put["openInterest"]),
                "iv": round((atm_call["iv"] + atm_put["iv"]) / 2 * 100, 1),
                "rationale": f"{'Earnings in ' + str(days_to_earnings) + 'd. ' if is_earnings_play else 'High IV environment. '}"
                             f"Needs >{move_needed:.1f}% move to profit. Expected move: ±{expected_move/price*100:.1f}%.",
                "risk_notes": f"Max loss ${total_premium * 100:,.0f} if stock doesn't move."
            })

    # ── PLAY 3: Strangle (cheaper volatility play) ──
    if is_earnings_play:
        otm_call = find_best_strike(chains, "call", expiry, price, "otm_near")
        otm_put = find_best_strike(chains, "put", expiry, price, "otm_near")
        if otm_call and otm_put:
            call_mid = (otm_call["bid"] + otm_call["ask"]) / 2 if otm_call["ask"] > 0 else otm_call["lastPrice"]
            put_mid = (otm_put["bid"] + otm_put["ask"]) / 2 if otm_put["ask"] > 0 else otm_put["lastPrice"]
            total_premium = call_mid + put_mid
            if total_premium > 0:
                move_needed_up = ((otm_call["strike"] + total_premium) / price - 1) * 100
                move_needed_down = (1 - (otm_put["strike"] - total_premium) / price) * 100

                plays.append({
                    "strategy": "Strangle", "emoji": "🎲", "direction": "Neutral (big move expected)",
                    "action": f"BUY {ticker} ${otm_call['strike']:.0f} Call + ${otm_put['strike']:.0f} Put",
                    "expiry": expiry, "dte": dte,
                    "strike": f"{otm_put['strike']:.0f}/{otm_call['strike']:.0f}",
                    "entry_price": round(total_premium, 2),
                    "bid": None, "ask": None,
                    "breakeven": f"${otm_put['strike'] - total_premium:.2f} / ${otm_call['strike'] + total_premium:.2f}",
                    "pct_to_breakeven": round(max(move_needed_up, move_needed_down), 1),
                    "max_loss": round(total_premium * 100, 0), "max_gain": "Unlimited",
                    "volume": _safe_int(otm_call["volume"] + otm_put["volume"]),
                    "open_interest": _safe_int(otm_call["openInterest"] + otm_put["openInterest"]),
                    "iv": round((otm_call["iv"] + otm_put["iv"]) / 2 * 100, 1),
                    "rationale": f"Cheaper than straddle for earnings in {days_to_earnings}d. "
                                 f"Needs >{max(move_needed_up, move_needed_down):.1f}% move.",
                    "risk_notes": f"Max loss ${total_premium * 100:,.0f}."
                })

    # ── PLAY 4: Bull Call Spread ──
    if bias == "bullish":
        long_call = find_best_strike(chains, "call", expiry, price, "atm")
        short_call = find_best_strike(chains, "call", expiry, price, "otm_far")
        if long_call and short_call and short_call["strike"] > long_call["strike"]:
            long_mid = (long_call["bid"] + long_call["ask"]) / 2 if long_call["ask"] > 0 else long_call["lastPrice"]
            short_mid = (short_call["bid"] + short_call["ask"]) / 2 if short_call["ask"] > 0 else short_call["lastPrice"]
            net_debit = long_mid - short_mid
            if net_debit > 0:
                spread_width = short_call["strike"] - long_call["strike"]
                max_profit = (spread_width - net_debit) * 100
                max_loss_val = net_debit * 100
                breakeven_val = long_call["strike"] + net_debit
                reward_risk = max_profit / max_loss_val if max_loss_val > 0 else 0

                plays.append({
                    "strategy": "Bull Call Spread", "emoji": "📊",
                    "direction": "Bullish (defined risk)",
                    "action": f"BUY {ticker} ${long_call['strike']:.0f}C / SELL ${short_call['strike']:.0f}C",
                    "expiry": expiry, "dte": dte,
                    "strike": f"{long_call['strike']:.0f}/{short_call['strike']:.0f}",
                    "entry_price": round(net_debit, 2), "bid": None, "ask": None,
                    "breakeven": round(breakeven_val, 2),
                    "pct_to_breakeven": round(((breakeven_val / price) - 1) * 100, 1),
                    "max_loss": round(max_loss_val, 0),
                    "max_gain": f"${max_profit:,.0f}",
                    "volume": _safe_int(long_call["volume"] + short_call["volume"]),
                    "open_interest": _safe_int(long_call["openInterest"] + short_call["openInterest"]),
                    "iv": round(long_call["iv"] * 100, 1),
                    "rationale": f"Defined-risk bullish. R/R: {reward_risk:.1f}:1. "
                                 f"{'Earnings in ' + str(days_to_earnings) + 'd. ' if is_earnings_play else ''}",
                    "risk_notes": f"Max loss ${max_loss_val:,.0f}, max gain ${max_profit:,.0f}."
                })

    # ── PLAY 5: Bear Put Spread ──
    if bias == "bearish":
        long_put = find_best_strike(chains, "put", expiry, price, "atm")
        short_put = find_best_strike(chains, "put", expiry, price, "otm_far")
        if long_put and short_put and long_put["strike"] > short_put["strike"]:
            long_mid = (long_put["bid"] + long_put["ask"]) / 2 if long_put["ask"] > 0 else long_put["lastPrice"]
            short_mid = (short_put["bid"] + short_put["ask"]) / 2 if short_put["ask"] > 0 else short_put["lastPrice"]
            net_debit = long_mid - short_mid
            if net_debit > 0:
                spread_width = long_put["strike"] - short_put["strike"]
                max_profit = (spread_width - net_debit) * 100
                max_loss_val = net_debit * 100
                breakeven_val = long_put["strike"] - net_debit
                reward_risk = max_profit / max_loss_val if max_loss_val > 0 else 0

                plays.append({
                    "strategy": "Bear Put Spread", "emoji": "📊",
                    "direction": "Bearish (defined risk)",
                    "action": f"BUY {ticker} ${long_put['strike']:.0f}P / SELL ${short_put['strike']:.0f}P",
                    "expiry": expiry, "dte": dte,
                    "strike": f"{long_put['strike']:.0f}/{short_put['strike']:.0f}",
                    "entry_price": round(net_debit, 2), "bid": None, "ask": None,
                    "breakeven": round(breakeven_val, 2),
                    "pct_to_breakeven": round(((price - breakeven_val) / price) * 100, 1),
                    "max_loss": round(max_loss_val, 0),
                    "max_gain": f"${max_profit:,.0f}",
                    "volume": _safe_int(long_put["volume"] + short_put["volume"]),
                    "open_interest": _safe_int(long_put["openInterest"] + short_put["openInterest"]),
                    "iv": round(long_put["iv"] * 100, 1),
                    "rationale": f"Defined-risk bearish. R/R: {reward_risk:.1f}:1.",
                    "risk_notes": f"Max loss ${max_loss_val:,.0f}, max gain ${max_profit:,.0f}."
                })

    # ── PLAY 6: Credit Spread (sell premium in high IV) ──
    if is_high_iv and not is_earnings_play:
        if bias != "bearish":
            short_put = find_best_strike(chains, "put", expiry, price, "otm_near")
            long_put = find_best_strike(chains, "put", expiry, price, "otm_far")
            if short_put and long_put and short_put["strike"] > long_put["strike"]:
                short_mid = (short_put["bid"] + short_put["ask"]) / 2 if short_put["ask"] > 0 else short_put["lastPrice"]
                long_mid = (long_put["bid"] + long_put["ask"]) / 2 if long_put["ask"] > 0 else long_put["lastPrice"]
                net_credit = short_mid - long_mid
                if net_credit > 0:
                    spread_width = short_put["strike"] - long_put["strike"]
                    max_loss_val = (spread_width - net_credit) * 100
                    max_profit = net_credit * 100
                    breakeven_val = short_put["strike"] - net_credit

                    plays.append({
                        "strategy": "Bull Put Credit Spread", "emoji": "💰",
                        "direction": "Neutral-to-bullish (sell premium)",
                        "action": f"SELL {ticker} ${short_put['strike']:.0f}P / BUY ${long_put['strike']:.0f}P",
                        "expiry": expiry, "dte": dte,
                        "strike": f"{short_put['strike']:.0f}/{long_put['strike']:.0f}",
                        "entry_price": round(net_credit, 2), "bid": None, "ask": None,
                        "breakeven": round(breakeven_val, 2),
                        "pct_to_breakeven": round(((price - breakeven_val) / price) * 100, 1),
                        "max_loss": round(max_loss_val, 0),
                        "max_gain": f"${max_profit:,.0f}",
                        "volume": _safe_int(short_put["volume"] + long_put["volume"]),
                        "open_interest": _safe_int(short_put["openInterest"] + long_put["openInterest"]),
                        "iv": round(short_put["iv"] * 100, 1),
                        "rationale": f"Sell elevated IV ({iv_30d:.0f}%). Collect ${net_credit:.2f}. "
                                     f"Win if {ticker} stays above ${breakeven_val:.2f}.",
                        "risk_notes": f"Max loss ${max_loss_val:,.0f}. Margin required."
                    })

    # ── PLAY 7: Iron Condor (high IV, neutral, no earnings — sell premium both sides) ──
    if is_high_iv and not is_earnings_play and bias == "neutral":
        # Sell OTM call spread + sell OTM put spread
        short_call = find_best_strike(chains, "call", expiry, price, "otm_near")
        long_call = find_best_strike(chains, "call", expiry, price, "otm_far")
        short_put = find_best_strike(chains, "put", expiry, price, "otm_near")
        long_put = find_best_strike(chains, "put", expiry, price, "otm_far")

        if short_call and long_call and short_put and long_put \
           and long_call["strike"] > short_call["strike"] \
           and short_put["strike"] > long_put["strike"]:
            sc_mid = (short_call["bid"] + short_call["ask"]) / 2 if short_call["ask"] > 0 else short_call["lastPrice"]
            lc_mid = (long_call["bid"] + long_call["ask"]) / 2 if long_call["ask"] > 0 else long_call["lastPrice"]
            sp_mid = (short_put["bid"] + short_put["ask"]) / 2 if short_put["ask"] > 0 else short_put["lastPrice"]
            lp_mid = (long_put["bid"] + long_put["ask"]) / 2 if long_put["ask"] > 0 else long_put["lastPrice"]

            call_credit = sc_mid - lc_mid
            put_credit = sp_mid - lp_mid
            total_credit = call_credit + put_credit

            if total_credit > 0:
                call_width = long_call["strike"] - short_call["strike"]
                put_width = short_put["strike"] - long_put["strike"]
                max_width = max(call_width, put_width)
                max_loss_val = (max_width - total_credit) * 100
                max_profit = total_credit * 100
                be_upper = short_call["strike"] + total_credit
                be_lower = short_put["strike"] - total_credit
                rr_ic = max_profit / max_loss_val if max_loss_val > 0 else 0

                plays.append({
                    "strategy": "Iron Condor", "emoji": "🦅",
                    "direction": "Neutral (sell premium both sides)",
                    "action": (f"SELL {ticker} ${short_put['strike']:.0f}P/${long_put['strike']:.0f}P + "
                               f"${short_call['strike']:.0f}C/${long_call['strike']:.0f}C"),
                    "expiry": expiry, "dte": dte,
                    "strike": f"{long_put['strike']:.0f}/{short_put['strike']:.0f}/{short_call['strike']:.0f}/{long_call['strike']:.0f}",
                    "entry_price": round(total_credit, 2), "bid": None, "ask": None,
                    "breakeven": f"${be_lower:.2f} / ${be_upper:.2f}",
                    "pct_to_breakeven": round(min(
                        ((price - be_lower) / price) * 100,
                        ((be_upper - price) / price) * 100
                    ), 1),
                    "max_loss": round(max_loss_val, 0),
                    "max_gain": f"${max_profit:,.0f}",
                    "volume": _safe_int(short_call["volume"] + long_call["volume"] + short_put["volume"] + long_put["volume"]),
                    "open_interest": _safe_int(short_call["openInterest"] + long_call["openInterest"] + short_put["openInterest"] + long_put["openInterest"]),
                    "iv": round((short_call["iv"] + short_put["iv"]) / 2 * 100, 1),
                    "rationale": (f"Sell elevated IV ({iv_30d:.0f}%) on both sides. Collect ${total_credit:.2f}. "
                                  f"R/R: {rr_ic:.1f}:1. Win if {ticker} stays ${be_lower:.0f}-${be_upper:.0f}. "
                                  f"Expected move: ±${expected_move:.2f}."),
                    "risk_notes": f"Max loss ${max_loss_val:,.0f}. Profit if stock stays range-bound. Margin required."
                })

    # ── Enrich all plays with execution quality metrics for RC scoring ──
    for play in plays:
        _enrich_play_metrics(play, price, iv_30d, expected_move)

    return plays


def _enrich_play_metrics(play, price, iv_30d, expected_move):
    """
    Add execution quality metrics to a play dict for unified Reality Check scoring.
    Computes: risk_reward_ratio, bid_ask_spread_pct, iv_percentile, breakeven_distance_pct.
    """
    entry = play.get("entry_price", 0) or 0
    max_loss = play.get("max_loss", 0) or 1
    max_gain_raw = play.get("max_gain", 0)
    strategy = (play.get("strategy") or "").lower()
    strike = play.get("strike", 0)

    # ── Risk/Reward Ratio ──
    if "spread" in strategy or "credit" in strategy:
        # Defined-risk: parse max_gain string like "$1,234"
        gain_val = 0
        if isinstance(max_gain_raw, str):
            try:
                gain_val = float(max_gain_raw.replace("$", "").replace(",", ""))
            except (ValueError, AttributeError):
                gain_val = 0
        else:
            gain_val = float(max_gain_raw) if max_gain_raw else 0
        play["risk_reward_ratio"] = round(gain_val / max_loss, 2) if max_loss > 0 else 0

    elif "straddle" in strategy or "strangle" in strategy:
        # Volatility play: profit if stock moves more than premium paid
        if entry > 0 and expected_move > 0:
            # At 1 std-dev move, profit ≈ expected_move - entry_price (per share)
            profit_1sd = max(0, expected_move - entry)
            play["risk_reward_ratio"] = round(profit_1sd / entry, 2)
        else:
            play["risk_reward_ratio"] = 0

    else:
        # Naked long call/put: R/R based on expected move vs premium
        if entry > 0 and expected_move > 0 and price > 0:
            breakeven = play.get("breakeven", 0)
            if isinstance(breakeven, str):
                # Multi-breakeven (straddles) — use entry as denominator
                play["risk_reward_ratio"] = round(expected_move / entry, 2)
            else:
                breakeven = float(breakeven) if breakeven else 0
                if "call" in strategy or "bullish" in play.get("direction", "").lower():
                    # If stock moves up by expected_move, intrinsic = (price + expected_move) - strike
                    strike_val = float(strike) if not isinstance(strike, str) else price
                    intrinsic_at_1sd = max(0, (price + expected_move) - strike_val)
                    profit = intrinsic_at_1sd - entry
                    play["risk_reward_ratio"] = round(max(0, profit) / entry, 2) if entry > 0 else 0
                else:
                    # Put: intrinsic = strike - (price - expected_move)
                    strike_val = float(strike) if not isinstance(strike, str) else price
                    intrinsic_at_1sd = max(0, strike_val - (price - expected_move))
                    profit = intrinsic_at_1sd - entry
                    play["risk_reward_ratio"] = round(max(0, profit) / entry, 2) if entry > 0 else 0
        else:
            play["risk_reward_ratio"] = 0

    # ── Bid/Ask Spread Percentage ──
    bid = play.get("bid")
    ask = play.get("ask")
    if bid is not None and ask is not None and bid > 0 and ask > 0:
        mid = (bid + ask) / 2
        play["bid_ask_spread_pct"] = round((ask - bid) / mid * 100, 1) if mid > 0 else 999.0
    else:
        # Multi-leg plays: estimate from entry vs typical spread
        # Use IV as proxy — higher IV = typically wider spreads
        iv_val = play.get("iv", 30)
        if iv_val > 80:
            play["bid_ask_spread_pct"] = 12.0  # high IV → wide spreads
        elif iv_val > 50:
            play["bid_ask_spread_pct"] = 7.0
        else:
            play["bid_ask_spread_pct"] = 4.0  # moderate estimate

    # ── IV Percentile (pass through) ──
    play["iv_percentile"] = iv_30d if iv_30d is not None else None

    # ── Breakeven Distance (absolute %) ──
    play["breakeven_distance_pct"] = abs(play.get("pct_to_breakeven", 0))


# ─────────────────────────────────────────────
# SCAN RUNNER
# ─────────────────────────────────────────────

def run_scan(tickers=None, enable_sec=True, enable_sentiment=True, callback=None):
    """Run a full scan with v2 scoring + intel layers. Returns list of scored results."""
    if tickers is None:
        tickers = ALL_TICKERS

    # ── Pre-fetch threat intel caches once for the whole scan ─────────────────
    _NEWS_INTEL_AVAILABLE = False
    try:
        from intel.news_intel import warm_caches as _warm_threat_caches
        from intel.news_intel import score_ticker_threat_context as _score_threat
        _warm_threat_caches(all_tickers=set(tickers))
        _NEWS_INTEL_AVAILABLE = True
        logger.info("✅ Threat intel caches warmed")
    except Exception as _nie:
        logger.warning(f"⚠️ News intel unavailable: {_nie}")

    results = []
    for i, ticker in enumerate(tickers):
        if callback:
            callback(ticker, i, len(tickers))

        data = fetch_ticker_data(ticker)
        if data:
            lt_score, lt_reasons, lt_breakdown = score_long_term(data)
            opt_score, opt_reasons, opt_breakdown = score_options(data)

            data["lt_score"] = lt_score
            data["lt_reasons"] = lt_reasons
            data["lt_breakdown"] = lt_breakdown
            data["opt_score"] = opt_score
            data["opt_reasons"] = opt_reasons
            data["opt_breakdown"] = opt_breakdown

            # Store component scores at top level for DB
            for key, val in lt_breakdown.items():
                data[f"lt_{key}"] = val.get("points", 0)
            for key, val in opt_breakdown.items():
                data[f"opt_{key}"] = val.get("points", 0)

            # ── Intel Layer: SEC / Insider ──
            ticker_obj = data.pop("_ticker_obj", None)

            if enable_sec and SEC_AVAILABLE and ticker_obj:
                try:
                    sec = analyze_sec_intel(ticker_obj, ticker)
                    data["sec_score"] = sec.get("sec_score", 0)
                    data["sec_signals"] = sec.get("sec_signals", [])
                    data["insider_buys_30d"] = sec.get("insider_buys_30d", 0)
                    data["insider_sells_30d"] = sec.get("insider_sells_30d", 0)
                    data["analyst_consensus"] = sec.get("analyst_consensus")
                    data["sec_intel"] = sec
                except Exception as e:
                    logger.warning(f"SEC intel failed for {ticker}: {e}")
                    data["sec_score"] = 0
                    data["sec_intel"] = None
            else:
                data["sec_score"] = 0
                data["sec_intel"] = None

            # ── Intel Layer: Sentiment ──
            if enable_sentiment and SENTIMENT_AVAILABLE and ticker_obj:
                try:
                    sent = analyze_sentiment(ticker_obj, ticker)
                    data["sentiment_score"] = sent.get("sentiment_score", 0)
                    data["sentiment_bull_pct"] = sent.get("sentiment_bull_pct")
                    data["sentiment_signals"] = sent.get("sentiment_signals", [])
                    data["sentiment_sources"] = sent.get("sentiment_sources", {})
                    data["sentiment"] = sent
                except Exception as e:
                    logger.warning(f"Sentiment failed for {ticker}: {e}")
                    data["sentiment_score"] = 0
                    data["sentiment"] = None
            else:
                data["sentiment_score"] = 0
                data["sentiment"] = None

            # ── Intel Layer: Timing Intelligence ──
            fetched_chains_for_timing = data.pop("_fetched_chains", [])
            if TIMING_AVAILABLE:
                try:
                    timing = compute_timing_intelligence(ticker, data, fetched_chains_for_timing)
                    data["horizon"] = timing.get("horizon")
                    data["horizon_reason"] = timing.get("horizon_reason")
                    data["horizon_confidence"] = timing.get("horizon_confidence")
                    data["recommended_expiry"] = timing.get("recommended_expiry")
                    data["recommended_dte"] = timing.get("recommended_dte")
                    data["timing_signals"] = timing.get("timing_signals", [])
                    data["timing_debug"] = timing.get("timing_debug", {})
                except Exception as e:
                    logger.warning(f"Timing intel failed for {ticker}: {e}")
                    data["horizon"] = None
                    data["timing_signals"] = []

            # Whale flow is already in data from fetch_ticker_data
            # Combine all intel signals into opt_reasons for dashboard
            all_intel_signals = []
            whale_sigs = data.get("whale_signals", [])
            if whale_sigs:
                all_intel_signals.extend(whale_sigs)
            sec_sigs = data.get("sec_signals", [])
            if sec_sigs:
                all_intel_signals.extend(sec_sigs)
            sent_sigs = data.get("sentiment_signals", [])
            if sent_sigs:
                all_intel_signals.extend(sent_sigs)

            if all_intel_signals:
                data["opt_reasons"] = opt_reasons + all_intel_signals
                data["lt_reasons"] = lt_reasons + [s for s in sec_sigs if "insider" in s.lower() or "analyst" in s.lower()]

            # ── Intel Layer: Threat Context (news + outage + macro) ────────────
            if _NEWS_INTEL_AVAILABLE:
                try:
                    sector_for_threat = data.get("sector", "cyber")
                    threat = _score_threat(ticker, sector_for_threat)
                    # Apply modifiers to live scores
                    new_opt = min(100, max(0, data["opt_score"] + threat["opt_modifier"]))
                    new_lt  = min(100, max(0, data["lt_score"]  + threat["lt_modifier"]))
                    data["opt_score"] = new_opt
                    data["lt_score"]  = new_lt
                    # Append threat signals to opt_reasons
                    if threat["signals"]:
                        data["opt_reasons"] = data.get("opt_reasons", []) + threat["signals"]
                    data["threat_score"]    = threat["threat_score"]
                    data["outage_status"]   = threat["outage_status"]
                    data["breach_victim"]   = threat["breach_victim"]
                    data["demand_signal"]   = threat["demand_signal"]
                    data["spx_change_pct"]  = threat["spx_change_pct"]
                except Exception as _te:
                    logger.warning(f"Threat scoring failed for {ticker}: {_te}")
                    data.setdefault("threat_score",  100)
                    data.setdefault("outage_status", "none")
                    data.setdefault("breach_victim", False)
                    data.setdefault("demand_signal", False)
            else:
                data.setdefault("threat_score",  100)
                data.setdefault("outage_status", "none")
                data.setdefault("breach_victim", False)
                data.setdefault("demand_signal", False)

            meta = _get_ticker_meta(ticker)
            data["sector"] = meta.get("sector", "cyber")
            data["subsector"] = meta.get("subsector", "")
            data["scoring_profile"] = meta.get("scoring_profile", "saas")
            results.append(data)

        time.sleep(0.15)

    return results
