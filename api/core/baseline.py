"""
Baseline vs Layers scoring (SESSION-BASELINE-WEIGHTS, 2026-06-11).

The BASELINE score funds only components with pre-registered statistical
justification (see core/weights_baseline.json + PROMOTION_CRITERIA.md):
  LT  = Valuation only      (decade PIT: t=+11.4 @12mo, sign-consistent)
  Opt = Asymmetry only      (OOS: IC +0.083 @21d, t=+10.1)
Direction still comes from compute_directional_bias (PR #6) — it picks the
contract and the label but carries zero baseline score weight.

Every demoted component keeps being COMPUTED and PERSISTED exactly as before:
score_long_term / score_options still run with the reference (legacy default)
weights, so the per-component point columns and breakdown JSON remain
comparable across the transition — that forward history is what future
promotion decisions need. The baseline score is then derived from the
breakdown's RAW (0-1) component values times the baseline weights.

Legacy mode: CYBERSCREENER_LEGACY_SCORES=1 restores the legacy composite as
the live score (one-transition-cycle comparison/debug flag, default off).
"""
import json
import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path(__file__).parent / "weights_baseline.json"

_config_cache: dict | None = None


def load_config(force: bool = False) -> dict:
    global _config_cache
    if _config_cache is None or force:
        _config_cache = json.loads(CONFIG_PATH.read_text())
    return _config_cache


def baseline_active() -> bool:
    """Baseline scoring is the default; the legacy composite stays computable
    behind an env flag for one transition cycle."""
    return os.environ.get("CYBERSCREENER_LEGACY_SCORES", "0") != "1"


def score_version() -> str:
    cfg = load_config()
    return cfg["score_version"] if baseline_active() else cfg["legacy_score_version"]


def _component_raw(breakdown: dict, component: str) -> float:
    """Raw 0-1 value of one component from a score breakdown. Missing or
    malformed entries read 0 — a data hole must never add score."""
    entry = breakdown.get(component) or {}
    raw = entry.get("raw")
    if raw is None:
        # derive from points/max when raw is absent (older breakdown rows)
        max_w = entry.get("max") or 0
        raw = (entry.get("points") or 0) / max_w if max_w else 0
    try:
        return max(0.0, min(1.0, float(raw)))
    except (TypeError, ValueError):
        return 0.0


def _baseline_score(breakdown: dict, weights: dict) -> float:
    return round(sum(_component_raw(breakdown, c) * w for c, w in weights.items()), 1)


def compute_baseline_lt(lt_breakdown: dict) -> float:
    """Baseline LT score (0-100): evidence-backed components only."""
    return _baseline_score(lt_breakdown, load_config()["baseline"]["lt"])


def compute_baseline_opt(opt_breakdown: dict) -> float:
    """Baseline Opt score (0-100): evidence-backed components only.
    Deliberately NO earnings multiplier — that is a layer (zero base effect)."""
    return _baseline_score(opt_breakdown, load_config()["baseline"]["opt"])


def layers_payload() -> dict:
    """The /layers API payload: baseline membership, evidence, and every
    user-addable layer with its honesty caption and reference weight."""
    cfg = load_config()
    return {
        "score_version": score_version(),
        "baseline_active": baseline_active(),
        "baseline": cfg["baseline"],
        "baseline_evidence": cfg["baseline_evidence"],
        "direction_picker": cfg["direction_picker"],
        "ref_weights": {k: v for k, v in cfg["ref_weights"].items() if k != "_doc"},
        "layers": cfg["layers"],
        "view_semantics": (
            "A layer view recomputes the stack score as the reference-weighted "
            "composite over {baseline components + selected layers}, "
            "renormalized to 100. Baseline alone equals the pure baseline "
            "score; all layers selected reproduces the legacy composite "
            "(minus the earnings multiplier). Layer views are EXPERIMENTAL "
            "and unvalidated - the baseline is the only scored claim."
        ),
    }
