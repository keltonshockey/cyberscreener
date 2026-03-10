"""
Backtest Engine v3 — Batch-optimized. Loads all prices in one query,
builds score-return pairs once, reuses across analyses.

Analyses:
1. Score vs Returns (quintile analysis): Did high scores predict high returns?
2. Component Attribution: Which score components best predicted returns?
3. Earnings Timing: Optimal entry window relative to earnings dates?
4. Self-Calibration: Auto-adjust scoring weights based on what actually predicted returns.
"""

import json
import numpy as np
from bisect import bisect_left
from datetime import datetime, timedelta
from collections import defaultdict

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from db.models import get_db, get_all_scores_for_backtest, save_score_weights, get_latest_weights


def _to_native(obj):
    """Recursively convert NumPy types to native Python types for JSON serialization."""
    if isinstance(obj, dict):
        return {k: _to_native(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_to_native(v) for v in obj]
    if isinstance(obj, np.bool_):
        return bool(obj)
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    return obj


# ─────────────────────────────────────────────
# BATCH PRICE CACHE — eliminates N+1 queries
# ─────────────────────────────────────────────

def _load_all_prices(days_back=365):
    """Load ALL prices into memory in one query. Returns {ticker: [(date_str, price), ...]} sorted by date."""
    conn = get_db()
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    rows = conn.execute(
        "SELECT ticker, date, close_price FROM prices WHERE date >= ? ORDER BY ticker, date",
        (cutoff,)
    ).fetchall()
    conn.close()

    price_map = defaultdict(list)
    for r in rows:
        price_map[r["ticker"]].append((r["date"], r["close_price"]))
    return dict(price_map)


def _nearest_price(price_map, ticker, target_date_str, window_days=5):
    """O(log n) nearest price lookup from in-memory cache."""
    entries = price_map.get(ticker)
    if not entries:
        return None

    dates = [e[0] for e in entries]
    idx = bisect_left(dates, target_date_str)

    best_price = None
    best_diff = window_days + 1

    target_dt = datetime.strptime(target_date_str, "%Y-%m-%d")
    for i in range(max(0, idx - window_days), min(len(entries), idx + window_days + 1)):
        d_str, price = entries[i]
        diff = abs((datetime.strptime(d_str, "%Y-%m-%d") - target_dt).days)
        if diff <= window_days and diff < best_diff:
            best_diff = diff
            best_price = price

    return best_price


def _get_forward_return_cached(price_map, ticker, score_date_str, forward_days):
    """Calculate forward return using cached prices."""
    entry_price = _nearest_price(price_map, ticker, score_date_str, window_days=3)
    if not entry_price:
        return None

    target_date = datetime.strptime(score_date_str, "%Y-%m-%d") + timedelta(days=forward_days)
    exit_price = _nearest_price(price_map, ticker, target_date.strftime("%Y-%m-%d"), window_days=5)
    if not exit_price:
        return None

    return round(((exit_price / entry_price) - 1) * 100, 2)


def _build_score_return_pairs(scores, price_map, forward_period=30, score_field="lt_score"):
    """Build (score, forward_return) pairs from pre-loaded data. No DB calls."""
    pairs = []
    for s in scores:
        score_val = s.get(score_field)
        if score_val is None:
            continue

        scan_date = s.get("scan_date", "")
        if not scan_date:
            continue

        try:
            date_str = scan_date[:10]
        except Exception:
            continue

        fwd_return = _get_forward_return_cached(price_map, s["ticker"], date_str, forward_period)
        if fwd_return is not None:
            pairs.append({
                "ticker": s["ticker"],
                "date": date_str,
                "score": score_val,
                "forward_return": fwd_return,
                "record": s,
            })

    return pairs


# ─────────────────────────────────────────────
# DEDUPLICATE: Sample one score per ticker per day
# ─────────────────────────────────────────────

def _deduplicate_scores(scores):
    """Keep only the latest score per ticker per day (avoid duplicate scans inflating count)."""
    seen = {}
    for s in scores:
        scan_date = s.get("scan_date", "")
        if not scan_date:
            continue
        key = (s["ticker"], scan_date[:10])
        if key not in seen:
            seen[key] = s
    return list(seen.values())


# ─────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────

def run_full_backtest(days=180, forward_period=30):
    """Run all three backtest analyses with shared data. One DB load, zero N+1."""
    # Single load of all data
    scores_raw = get_all_scores_for_backtest(days)
    scores = _deduplicate_scores(scores_raw)
    price_map = _load_all_prices(days_back=days + forward_period + 60)

    # Build pairs once per forward period, reuse across analyses
    lt_pairs = _build_score_return_pairs(scores, price_map, forward_period, "lt_score")
    opt_pairs = _build_score_return_pairs(scores, price_map, forward_period, "opt_score")

    # Earnings timing needs 14d and 30d pairs
    opt_pairs_14d = _build_score_return_pairs(scores, price_map, 14, "opt_score") if forward_period != 14 else opt_pairs
    opt_pairs_30d = opt_pairs if forward_period == 30 else _build_score_return_pairs(scores, price_map, 30, "opt_score")

    result = {
        "score_vs_returns": _score_vs_returns(lt_pairs, opt_pairs, forward_period, days),
        "layer_attribution": _layer_attribution(lt_pairs, opt_pairs, forward_period, days),
        "earnings_timing": _earnings_timing(opt_pairs_14d, opt_pairs_30d, days),
        "metadata": {
            "lookback_days": days,
            "forward_period": forward_period,
            "score_records": len(scores),
            "price_records": sum(len(v) for v in price_map.values()),
            "timestamp": datetime.now().isoformat(),
        }
    }
    return _to_native(result)


def backtest_score_vs_returns(days=180, forward_period=30):
    """Standalone quintile analysis (used by calibration)."""
    scores = _deduplicate_scores(get_all_scores_for_backtest(days))
    price_map = _load_all_prices(days_back=days + forward_period + 60)
    lt_pairs = _build_score_return_pairs(scores, price_map, forward_period, "lt_score")
    opt_pairs = _build_score_return_pairs(scores, price_map, forward_period, "opt_score")
    return _to_native(_score_vs_returns(lt_pairs, opt_pairs, forward_period, days))


def backtest_layer_attribution(days=180, forward_period=30):
    """Standalone layer attribution (used by calibration)."""
    scores = _deduplicate_scores(get_all_scores_for_backtest(days))
    price_map = _load_all_prices(days_back=days + forward_period + 60)
    lt_pairs = _build_score_return_pairs(scores, price_map, forward_period, "lt_score")
    opt_pairs = _build_score_return_pairs(scores, price_map, forward_period, "opt_score")
    return _to_native(_layer_attribution(lt_pairs, opt_pairs, forward_period, days))


def backtest_earnings_timing(days=180):
    """Standalone earnings timing (used by /backtest/earnings-timing endpoint)."""
    scores = _deduplicate_scores(get_all_scores_for_backtest(days))
    price_map = _load_all_prices(days_back=days + 30 + 60)
    opt_pairs_14d = _build_score_return_pairs(scores, price_map, 14, "opt_score")
    opt_pairs_30d = _build_score_return_pairs(scores, price_map, 30, "opt_score")
    return _to_native(_earnings_timing(opt_pairs_14d, opt_pairs_30d, days))


# ─────────────────────────────────────────────
# ANALYSIS FUNCTIONS (operate on pre-built pairs)
# ─────────────────────────────────────────────

def _score_vs_returns(lt_pairs, opt_pairs, forward_period, days):
    return {
        "lt_analysis": _quintile_analysis(lt_pairs, "lt_score"),
        "opt_analysis": _quintile_analysis(opt_pairs, "opt_score"),
        "forward_period_days": forward_period,
        "lookback_days": days,
        "timestamp": datetime.now().isoformat(),
    }


def _quintile_analysis(pairs, score_field):
    """Run quintile analysis on pre-built pairs."""
    if len(pairs) < 10:
        return {
            "status": "insufficient_data",
            "data_points": len(pairs),
            "message": f"Need at least 10 data points, have {len(pairs)}. Run more scans or backfill first.",
        }

    pairs.sort(key=lambda x: x["score"])
    n = len(pairs)
    quintile_size = n // 5

    quintiles = {}
    for q in range(5):
        start = q * quintile_size
        end = (q + 1) * quintile_size if q < 4 else n
        bucket = pairs[start:end]

        scores = [p["score"] for p in bucket]
        returns = [p["forward_return"] for p in bucket]

        quintiles[f"Q{q+1}"] = {
            "avg_score": round(np.mean(scores), 1),
            "min_score": round(min(scores), 1),
            "max_score": round(max(scores), 1),
            "avg_return": round(np.mean(returns), 2),
            "median_return": round(np.median(returns), 2),
            "win_rate": round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1),
            "count": len(bucket),
        }

    all_scores = [p["score"] for p in pairs]
    all_returns = [p["forward_return"] for p in pairs]
    correlation = round(float(np.corrcoef(all_scores, all_returns)[0, 1]), 3) if len(pairs) > 2 else 0

    q5_return = quintiles["Q5"]["avg_return"]
    q1_return = quintiles["Q1"]["avg_return"]
    quintile_spread = round(q5_return - q1_return, 2)

    quintile_returns = [quintiles[f"Q{q+1}"]["avg_return"] for q in range(5)]
    monotonic_violations = sum(1 for i in range(4) if quintile_returns[i+1] < quintile_returns[i])

    return {
        "status": "ok",
        "score_type": score_field,
        "data_points": len(pairs),
        "correlation": correlation,
        "quintile_spread": quintile_spread,
        "monotonic_violations": monotonic_violations,
        "is_predictive": correlation > 0.05 and quintile_spread > 1.0,
        "quintiles": quintiles,
        "interpretation": _interpret_quintile(correlation, quintile_spread, monotonic_violations),
    }


def _interpret_quintile(correlation, spread, violations):
    """Human-readable interpretation of backtest results."""
    parts = []
    if correlation > 0.15:
        parts.append(f"Strong positive correlation ({correlation:.3f}) — scores predict returns well.")
    elif correlation > 0.05:
        parts.append(f"Moderate positive correlation ({correlation:.3f}) — scores have some predictive power.")
    elif correlation > -0.05:
        parts.append(f"Weak/no correlation ({correlation:.3f}) — scores don't reliably predict returns.")
    else:
        parts.append(f"Negative correlation ({correlation:.3f}) — scores are inversely related to returns. Scoring needs revision.")

    if spread > 5:
        parts.append(f"Q5 outperformed Q1 by {spread:.1f}% — significant spread.")
    elif spread > 1:
        parts.append(f"Q5 outperformed Q1 by {spread:.1f}% — modest but positive spread.")
    else:
        parts.append(f"Q5-Q1 spread is only {spread:.1f}% — not meaningful.")

    if violations == 0:
        parts.append("Perfectly monotonic: higher scores = higher returns across all quintiles.")
    elif violations <= 1:
        parts.append(f"Mostly monotonic ({violations} violation) — generally higher scores = higher returns.")
    else:
        parts.append(f"Non-monotonic ({violations} violations) — score-return relationship is noisy.")

    return " ".join(parts)


def _layer_attribution(lt_pairs, opt_pairs, forward_period, days):
    """Which score components best predicted returns? Operates on pre-built pairs."""
    if len(lt_pairs) < 10:
        return {"status": "insufficient_data", "data_points": len(lt_pairs)}

    lt_components = ["lt_rule_of_40", "lt_valuation", "lt_fcf_margin",
                     "lt_trend", "lt_earnings_quality", "lt_discount_momentum"]

    lt_attribution = {}
    for comp in lt_components:
        comp_scores = []
        returns = []
        for p in lt_pairs:
            val = p["record"].get(comp)
            if val is not None:
                comp_scores.append(val)
                returns.append(p["forward_return"])
        if len(comp_scores) > 5:
            corr = float(np.corrcoef(comp_scores, returns)[0, 1])
            if np.isnan(corr):
                corr = 0
            lt_attribution[comp] = {
                "correlation": round(corr, 3),
                "avg_value": round(np.mean(comp_scores), 1),
                "data_points": len(comp_scores),
                "predictive": abs(corr) > 0.05,
            }

    opt_components = ["opt_earnings_catalyst", "opt_iv_context", "opt_directional",
                      "opt_technical", "opt_liquidity", "opt_asymmetry"]

    opt_attribution = {}
    for comp in opt_components:
        comp_scores = []
        returns = []
        for p in opt_pairs:
            val = p["record"].get(comp)
            if val is not None:
                comp_scores.append(val)
                returns.append(p["forward_return"])
        if len(comp_scores) > 5:
            corr = float(np.corrcoef(comp_scores, returns)[0, 1])
            if np.isnan(corr):
                corr = 0
            opt_attribution[comp] = {
                "correlation": round(corr, 3),
                "avg_value": round(np.mean(comp_scores), 1),
                "data_points": len(comp_scores),
                "predictive": abs(corr) > 0.05,
            }

    raw_indicators = ["revenue_growth_pct", "gross_margin_pct", "ps_ratio", "pe_ratio",
                      "fcf_m", "rsi", "bb_width", "vol_ratio", "iv_30d", "beta", "short_pct",
                      "perf_3m", "pct_from_52w_high"]

    indicator_correlations = {}
    for ind in raw_indicators:
        vals = []
        rets = []
        for p in lt_pairs:
            v = p["record"].get(ind)
            if v is not None:
                vals.append(v)
                rets.append(p["forward_return"])
        if len(vals) > 5:
            corr = float(np.corrcoef(vals, rets)[0, 1])
            if not np.isnan(corr):
                indicator_correlations[ind] = round(corr, 3)

    return {
        "status": "ok",
        "forward_period_days": forward_period,
        "lookback_days": days,
        "lt_component_attribution": lt_attribution,
        "opt_component_attribution": opt_attribution,
        "raw_indicator_correlations": indicator_correlations,
        "data_points": len(lt_pairs),
        "timestamp": datetime.now().isoformat(),
    }


def _earnings_timing(opt_pairs_14d, opt_pairs_30d, days):
    """Optimal entry window relative to earnings."""
    def _analyze_by_earnings_window(pairs):
        buckets = {
            "1-4d pre": [],
            "5-14d pre": [],
            "15-30d pre": [],
            "30+d or no earnings": [],
        }
        for p in pairs:
            dte = p["record"].get("days_to_earnings")
            if dte is not None and 1 <= dte <= 4:
                buckets["1-4d pre"].append(p)
            elif dte is not None and 5 <= dte <= 14:
                buckets["5-14d pre"].append(p)
            elif dte is not None and 15 <= dte <= 30:
                buckets["15-30d pre"].append(p)
            else:
                buckets["30+d or no earnings"].append(p)

        result = {}
        for bucket_name, bucket_pairs in buckets.items():
            if bucket_pairs:
                returns = [p["forward_return"] for p in bucket_pairs]
                result[bucket_name] = {
                    "avg_return": round(np.mean(returns), 2),
                    "median_return": round(np.median(returns), 2),
                    "win_rate": round(sum(1 for r in returns if r > 0) / len(returns) * 100, 1),
                    "count": len(returns),
                    "std_dev": round(float(np.std(returns)), 2),
                }
            else:
                result[bucket_name] = {"count": 0}
        return result

    return {
        "status": "ok",
        "lookback_days": days,
        "forward_14d": _analyze_by_earnings_window(opt_pairs_14d),
        "forward_30d": _analyze_by_earnings_window(opt_pairs_30d),
        "data_points_14d": len(opt_pairs_14d),
        "data_points_30d": len(opt_pairs_30d),
        "timestamp": datetime.now().isoformat(),
    }


# ─────────────────────────────────────────────
# SELF-CALIBRATION ENGINE
# ─────────────────────────────────────────────

def calibrate_weights(days=180, forward_period=30, dry_run=False):
    """
    Auto-adjust scoring weights based on component-return correlations.
    Uses batch-optimized backtest internally.
    """
    attribution = backtest_layer_attribution(days, forward_period)
    if attribution.get("status") != "ok":
        return {"status": "insufficient_data", "message": "Need more backtest data to calibrate."}

    from core.scanner import get_weights, set_weights, DEFAULT_LT_WEIGHTS, DEFAULT_OPT_WEIGHTS
    current = get_weights()
    results = {}

    lt_attr = attribution.get("lt_component_attribution", {})
    if lt_attr:
        lt_new = _compute_new_weights(current["lt"], lt_attr, DEFAULT_LT_WEIGHTS, "lt_")
        results["lt_weights"] = {
            "current": current["lt"],
            "proposed": lt_new["weights"],
            "changes": lt_new["changes"],
            "reason": lt_new["reason"],
        }

    opt_attr = attribution.get("opt_component_attribution", {})
    if opt_attr:
        opt_new = _compute_new_weights(current["opt"], opt_attr, DEFAULT_OPT_WEIGHTS, "opt_")
        results["opt_weights"] = {
            "current": current["opt"],
            "proposed": opt_new["weights"],
            "changes": opt_new["changes"],
            "reason": opt_new["reason"],
        }

    if not dry_run:
        if "lt_weights" in results:
            new_lt = results["lt_weights"]["proposed"]
            set_weights(lt_weights=new_lt)

            # Quick re-check with new weights
            scores = _deduplicate_scores(get_all_scores_for_backtest(days))
            price_map = _load_all_prices(days_back=days + forward_period + 60)
            lt_pairs = _build_score_return_pairs(scores, price_map, forward_period, "lt_score")
            new_backtest = _quintile_analysis(lt_pairs, "lt_score")

            save_score_weights(
                "lt", new_lt,
                correlation=new_backtest.get("correlation"),
                quintile_spread=new_backtest.get("quintile_spread"),
                data_points=new_backtest.get("data_points"),
                notes=f"Auto-calibrated from {days}d backtest",
            )
            results["lt_weights"]["backtest_after"] = {
                "correlation": new_backtest.get("correlation"),
                "quintile_spread": new_backtest.get("quintile_spread"),
            }

        if "opt_weights" in results:
            new_opt = results["opt_weights"]["proposed"]
            set_weights(opt_weights=new_opt)
            save_score_weights(
                "opt", new_opt,
                data_points=attribution.get("data_points"),
                notes=f"Auto-calibrated from {days}d backtest",
            )

    results["status"] = "calibrated" if not dry_run else "dry_run"
    results["timestamp"] = datetime.now().isoformat()
    return results


def _compute_new_weights(current_weights, attributions, default_weights, component_prefix):
    """Compute new weights from attributions."""
    raw_weights = {}
    changes = {}

    for comp_name, current_w in current_weights.items():
        attr_key = f"{component_prefix}{comp_name}"
        attr = attributions.get(attr_key, {})
        corr = attr.get("correlation", 0)

        if corr > 0.1:
            mult = 1.0 + min(0.3, corr * 2)
        elif corr > 0.02:
            mult = 1.0 + corr * 5
        elif corr > -0.02:
            mult = 1.0
        elif corr > -0.1:
            mult = 1.0 + corr * 3
        else:
            mult = max(0.7, 1.0 + corr * 2)

        new_w = current_w * mult
        raw_weights[comp_name] = new_w
        changes[comp_name] = {
            "correlation": corr,
            "multiplier": round(mult, 3),
            "old": current_w,
            "new_raw": round(new_w, 1),
        }

    total = sum(raw_weights.values())
    if total > 0:
        normalized = {k: round(v / total * 100, 1) for k, v in raw_weights.items()}
    else:
        normalized = dict(default_weights)

    for k in normalized:
        if normalized[k] < 3:
            normalized[k] = 3.0

    total = sum(normalized.values())
    normalized = {k: round(v / total * 100, 1) for k, v in normalized.items()}

    for comp_name in changes:
        changes[comp_name]["new_final"] = normalized[comp_name]

    boosted = [k for k, v in changes.items() if v["multiplier"] > 1.05]
    reduced = [k for k, v in changes.items() if v["multiplier"] < 0.95]

    reason_parts = []
    if boosted:
        reason_parts.append(f"Boosted: {', '.join(boosted)}")
    if reduced:
        reason_parts.append(f"Reduced: {', '.join(reduced)}")
    if not boosted and not reduced:
        reason_parts.append("No significant changes — current weights are reasonable.")

    return {
        "weights": normalized,
        "changes": changes,
        "reason": " | ".join(reason_parts),
    }
