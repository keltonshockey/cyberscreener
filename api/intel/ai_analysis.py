"""
AI Play Analysis — Claude API integration for qualitative play evaluation.

Uses Claude (Haiku) to analyze generated plays with market context,
sector narrative, and risk factors the rule-based engine can't capture.

Requires ANTHROPIC_API_KEY env var to be set.
"""

import os
import json
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)

# ── Cache for analyses (ticker -> {data, timestamp}) ──
_analysis_cache = {}
_CACHE_TTL = 1800  # 30 minutes

# ── Rate limiting ──
_user_usage = {}  # user_id -> {count, reset_time}
_MAX_DAILY_ANALYSES = 20


def _check_rate_limit(user_id: str) -> bool:
    """Check if user has remaining analyses today."""
    now = time.time()
    if user_id not in _user_usage:
        _user_usage[user_id] = {"count": 0, "reset_time": now + 86400}

    usage = _user_usage[user_id]
    if now > usage["reset_time"]:
        usage["count"] = 0
        usage["reset_time"] = now + 86400

    return usage["count"] < _MAX_DAILY_ANALYSES


def _increment_usage(user_id: str):
    if user_id in _user_usage:
        _user_usage[user_id]["count"] += 1


def is_available() -> bool:
    """Check if AI analysis is available (API key configured)."""
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def analyze_plays(
    ticker: str,
    price: float,
    plays: list,
    ticker_data: dict,
    user_id: str = "anonymous",
) -> dict:
    """
    Analyze generated plays using Claude API.

    Returns:
        {
            "context": "2-sentence market context",
            "plays": [{"strategy": ..., "confidence": 1-5, "risk": ..., "recommendation": ...}],
            "top_pick": "strategy name + why",
            "blind_spot": "what the algorithm might be missing",
            "model": "claude-3-5-haiku-20241022",
            "cached": bool,
        }
    """
    # Check cache first
    cache_key = f"{ticker}:{len(plays)}"
    if cache_key in _analysis_cache:
        cached = _analysis_cache[cache_key]
        if time.time() - cached["timestamp"] < _CACHE_TTL:
            return {**cached["data"], "cached": True}

    # Rate limiting
    if not _check_rate_limit(user_id):
        return {
            "error": f"Rate limit reached ({_MAX_DAILY_ANALYSES} analyses/day). Try again tomorrow.",
            "cached": False,
        }

    # Check API key
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"error": "AI analysis not configured (ANTHROPIC_API_KEY not set)", "cached": False}

    try:
        import anthropic
    except ImportError:
        return {"error": "anthropic package not installed", "cached": False}

    # Build the analysis prompt
    plays_summary = []
    for i, p in enumerate(plays):
        plays_summary.append({
            "idx": i + 1,
            "strategy": p.get("strategy", "Unknown"),
            "direction": p.get("direction", ""),
            "action": p.get("action", ""),
            "entry_price": p.get("entry_price"),
            "max_loss": p.get("max_loss"),
            "max_gain": p.get("max_gain"),
            "risk_reward_ratio": p.get("risk_reward_ratio", 0),
            "rc_score": p.get("rc_score", 0),
            "dte": p.get("dte"),
            "iv": p.get("iv"),
            "volume": p.get("volume"),
            "open_interest": p.get("open_interest"),
        })

    prompt = f"""You are a senior options analyst. Analyze these generated plays for {ticker} (${price:.2f}).

Ticker Data:
- RSI: {ticker_data.get('rsi', 'N/A')}
- IV 30d: {ticker_data.get('iv_30d', 'N/A')}%
- IV Rank: {ticker_data.get('iv_rank', 'N/A')}%
- Days to Earnings: {ticker_data.get('days_to_earnings', 'N/A')}
- LT Score: {ticker_data.get('lt_score', 'N/A')}/100
- Opt Score: {ticker_data.get('opt_score', 'N/A')}/100
- Beta: {ticker_data.get('beta', 'N/A')}
- 3mo Performance: {ticker_data.get('perf_3m', 'N/A')}%
- % from 52w High: {ticker_data.get('pct_from_52w_high', 'N/A')}%
- Sector: {ticker_data.get('sector', 'unknown')}

Generated Plays:
{json.dumps(plays_summary, indent=2)}

Provide your analysis as JSON with this exact structure:
{{
  "context": "2-sentence market context for this ticker right now",
  "plays": [
    {{
      "strategy": "strategy name",
      "confidence": <1-5 integer>,
      "risk": "key risk in one sentence",
      "take_it": <true/false>
    }}
  ],
  "top_pick": "which play and why in 1-2 sentences",
  "blind_spot": "one thing the algorithm might be missing"
}}

Be direct and actionable. Focus on what a trader needs to know NOW."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        response = client.messages.create(
            model="claude-3-5-haiku-20241022",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )

        # Parse response
        text = response.content[0].text.strip()

        # Try to extract JSON from response
        if text.startswith("{"):
            result = json.loads(text)
        else:
            # Try to find JSON in the response
            import re
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                result = json.loads(json_match.group())
            else:
                result = {
                    "context": text[:200],
                    "plays": [],
                    "top_pick": "See context above",
                    "blind_spot": "Could not parse structured response",
                }

        result["model"] = "claude-3-5-haiku-20241022"
        result["cached"] = False

        # Cache the result
        _analysis_cache[cache_key] = {"data": result, "timestamp": time.time()}
        _increment_usage(user_id)

        return result

    except Exception as e:
        logger.error(f"AI analysis failed for {ticker}: {e}")
        return {"error": f"Analysis failed: {str(e)}", "cached": False}
