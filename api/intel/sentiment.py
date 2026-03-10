"""
Sentiment Intel Layer v2

Sources — all via yfinance (no external HTTP calls, Railway-safe):
  1. Yahoo Finance news headlines (ticker.news) — last 7 days, scored via
     FinBERT (HuggingFace Inference API) with keyword-bag fallback
  2. Analyst recommendation trend (upgrades/downgrades) — last 30 days

P3 Enhancement: FinBERT via HuggingFace Inference API
  - POST to https://api-inference.huggingface.co/models/ProsusAI/finbert
  - Requires HF_API_TOKEN env var (optional — falls back to keyword-bag if absent/fails)
  - MD5-keyed in-process cache avoids re-scoring identical text

Returns:
  {
    "sentiment_score": 0-100,
    "sentiment_signals": [...],
    "sentiment_bull_pct": float,
    "sentiment_sources": { "news": {...}, "recommendations": {...} }
  }
"""

import os
import logging
import hashlib
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# ── P3: FinBERT via HuggingFace Inference API ─────────────────────────────────

_HF_API_TOKEN = os.environ.get("HF_API_TOKEN", "")
_FINBERT_URL = "https://api-inference.huggingface.co/models/ProsusAI/finbert"
_finbert_cache: dict = {}   # md5(text) → "positive"/"negative"/"neutral"
_finbert_available: bool = True  # flipped False on repeated failures


def _score_text_finbert(text: str) -> str:
    """
    Score a text snippet using FinBERT via HuggingFace Inference API.
    Returns "bullish", "bearish", or "neutral".
    Falls back to keyword-bag if API unavailable.
    """
    global _finbert_available
    if not _finbert_available or not _HF_API_TOKEN:
        return _score_text(text)

    cache_key = hashlib.md5(text.encode()).hexdigest()
    if cache_key in _finbert_cache:
        return _finbert_cache[cache_key]

    try:
        import requests
        headers = {"Authorization": f"Bearer {_HF_API_TOKEN}"}
        resp = requests.post(
            _FINBERT_URL,
            headers=headers,
            json={"inputs": text[:512]},  # FinBERT max input
            timeout=8,
        )
        if resp.status_code == 200:
            data = resp.json()
            # FinBERT returns [[{label, score}, ...]]
            if data and isinstance(data, list) and isinstance(data[0], list):
                labels = {item["label"].lower(): item["score"] for item in data[0]}
                # Map FinBERT labels: positive → bullish, negative → bearish
                pos = labels.get("positive", 0)
                neg = labels.get("negative", 0)
                neu = labels.get("neutral", 0)
                best = max(pos, neg, neu)
                if best == pos and pos > 0.5:
                    result = "bullish"
                elif best == neg and neg > 0.5:
                    result = "bearish"
                else:
                    result = "neutral"
                _finbert_cache[cache_key] = result
                return result
        elif resp.status_code == 503:
            # Model loading — don't mark unavailable, just fall back this call
            logger.debug("FinBERT model loading (503), using keyword fallback")
            return _score_text(text)
        else:
            logger.debug(f"FinBERT API error {resp.status_code}, using keyword fallback")
    except Exception as e:
        logger.debug(f"FinBERT exception: {e}, disabling for session")
        _finbert_available = False

    return _score_text(text)  # keyword-bag fallback

_BULLISH_KEYWORDS = {
    "beat", "beats", "surge", "surges", "rally", "rallies", "upgrade", "upgraded",
    "buy", "outperform", "overweight", "strong", "growth", "record", "raise",
    "raised", "upside", "momentum", "breakout", "bullish", "positive", "win",
    "partnership", "contract", "expansion", "ai", "artificial intelligence",
    "accelerat", "exceed", "boom", "soar", "jump", "spike", "rebound",
}
_BEARISH_KEYWORDS = {
    "miss", "misses", "missed", "decline", "declines", "downgrade", "downgraded",
    "sell", "underperform", "underweight", "weak", "loss", "losses", "cut",
    "cuts", "layoff", "layoffs", "breach", "hack", "lawsuit", "investigation",
    "bearish", "negative", "concern", "warning", "risk", "disappoint",
    "fall", "drop", "slump", "tumble", "plunge", "below",
}


def _score_text(text: str) -> str:
    lower = text.lower()
    bull = sum(1 for w in _BULLISH_KEYWORDS if w in lower)
    bear = sum(1 for w in _BEARISH_KEYWORDS if w in lower)
    if bull > bear:
        return "bullish"
    elif bear > bull:
        return "bearish"
    return "neutral"


def _get_news_sentiment(ticker_obj, ticker_sym: str) -> dict:
    """Score Yahoo Finance news headlines from last 7 days via yfinance."""
    result = {"bull": 0, "bear": 0, "neutral": 0, "total": 0, "status": "unavailable"}
    try:
        news = ticker_obj.news
        if not news:
            result["status"] = "no_news"
            return result

        cutoff = datetime.now() - timedelta(days=7)
        for item in news[:30]:
            pub = item.get("providerPublishTime", 0)
            try:
                if pub and datetime.fromtimestamp(pub) < cutoff:
                    continue
            except Exception:
                pass
            text = f"{item.get('title', '')} {item.get('summary', '')}"
            label = _score_text_finbert(text)  # P3: FinBERT with keyword-bag fallback
            result[label] += 1
            result["total"] += 1

        result["status"] = "ok" if result["total"] > 0 else "no_recent_news"
    except Exception as e:
        logger.debug(f"News sentiment error for {ticker_sym}: {e}")
        result["status"] = "error"
    return result


def _get_recommendation_sentiment(ticker_obj, ticker_sym: str) -> dict:
    """
    Parse recent analyst recommendation changes from yfinance.
    Upgrades → bullish signal, downgrades → bearish signal.
    """
    result = {"upgrades": 0, "downgrades": 0, "total": 0, "status": "unavailable"}
    try:
        recs = ticker_obj.recommendations
        if recs is None or recs.empty:
            result["status"] = "no_data"
            return result

        cutoff = datetime.now() - timedelta(days=30)

        for idx, row in recs.iterrows():
            try:
                # Index is datetime
                if hasattr(idx, 'to_pydatetime'):
                    rec_date = idx.to_pydatetime().replace(tzinfo=None)
                else:
                    rec_date = datetime.strptime(str(idx)[:10], "%Y-%m-%d")
                if rec_date < cutoff:
                    continue
            except Exception:
                continue

            action = str(row.get("Action", "")).lower()
            to_grade = str(row.get("To Grade", "")).lower()

            is_upgrade = any(w in action for w in ["upgrade", "init", "initiated", "reiterated"]) or \
                         any(w in to_grade for w in ["buy", "outperform", "overweight", "strong buy"])
            is_downgrade = any(w in action for w in ["downgrade"]) or \
                           any(w in to_grade for w in ["sell", "underperform", "underweight", "reduce"])

            if is_upgrade:
                result["upgrades"] += 1
            elif is_downgrade:
                result["downgrades"] += 1
            result["total"] += 1

        result["status"] = "ok"
    except Exception as e:
        logger.debug(f"Recommendations error for {ticker_sym}: {e}")
        result["status"] = "error"
    return result


def _compute_sentiment_score(news: dict, recs: dict) -> tuple:
    """
    Compute sentiment_score (0-100).

    Weights:
      News headlines:       60 pts
      Analyst rec changes:  40 pts
    """
    score = 0
    signals = []
    bull_pct = None

    # ── News (60 pts) ──
    if news.get("status") == "ok" and news["total"] > 0:
        bull_pct_raw = news["bull"] / news["total"] * 100
        bull_pct = round(bull_pct_raw, 1)

        if bull_pct_raw >= 70:
            score += 60
            signals.append(f"📰 Strong bullish news flow: {news['bull']}/{news['total']} positive headlines")
        elif bull_pct_raw >= 55:
            score += 45
            signals.append(f"📰 Bullish news flow: {news['bull']}/{news['total']} positive headlines")
        elif bull_pct_raw >= 40:
            score += 30
        elif news["bear"] > news["bull"] * 1.5:
            score += 5
            signals.append(f"📰 Bearish news flow: {news['bear']} negative vs {news['bull']} positive headlines")
        else:
            score += 20  # Mixed/neutral
    else:
        score += 20  # No news = neutral assumption

    # ── Analyst rec changes (40 pts) ──
    if recs.get("status") == "ok" and recs["total"] > 0:
        net = recs["upgrades"] - recs["downgrades"]
        if net >= 3:
            score += 40
            signals.append(f"📈 {recs['upgrades']} analyst upgrades vs {recs['downgrades']} downgrades (30d)")
        elif net >= 1:
            score += 28
            signals.append(f"📈 Net analyst upgrades: +{net} (30d)")
        elif net == 0 and recs["upgrades"] > 0:
            score += 20
        elif net == -1:
            score += 10
            signals.append(f"📉 Net analyst downgrade: {recs['downgrades']} downgrades (30d)")
        elif net <= -2:
            score += 0
            signals.append(f"📉 {recs['downgrades']} analyst downgrades vs {recs['upgrades']} upgrades (30d)")
    else:
        score += 20  # No rec data = neutral

    return min(score, 100), signals, bull_pct


def analyze_sentiment(ticker_obj, ticker_sym: str) -> dict:
    """Main entry point. Called by scanner.run_scan() when enable_sentiment=True."""
    try:
        news = _get_news_sentiment(ticker_obj, ticker_sym)
        recs = _get_recommendation_sentiment(ticker_obj, ticker_sym)
        sentiment_score, signals, bull_pct = _compute_sentiment_score(news, recs)

        return {
            "sentiment_score": sentiment_score,
            "sentiment_signals": signals,
            "sentiment_bull_pct": bull_pct,
            "sentiment_sources": {
                "news": news,
                "recommendations": recs,
            },
        }
    except Exception as e:
        logger.warning(f"Sentiment failed for {ticker_sym}: {e}")
        return {
            "sentiment_score": 0,
            "sentiment_signals": [],
            "sentiment_bull_pct": None,
            "sentiment_sources": {},
        }
