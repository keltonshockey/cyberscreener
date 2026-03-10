"""
Augur Character Attribute → Scoring Weight Mapping.

Each of the 6 Augur attributes influences 2 scoring weight components.
Attributes range 1-10 (neutral = 6, pool of 36 total).
Points above/below neutral shift the mapped weight components proportionally.
"""

import copy

# ── Attribute → Component Mapping ──
# Each attribute maps to 2 components with an influence factor.
# Format: (score_type, component_name, influence_factor)
# Higher influence_factor = attribute has stronger effect on that component.

ATTRIBUTE_MAP = {
    "prudentia": [
        ("lt", "valuation", 1.5),         # Caution → strong valuation focus
        ("lt", "earnings_quality", 1.0),   # Caution → earnings quality matters
    ],
    "audacia": [
        ("opt", "directional", 1.5),       # Boldness → strong directional conviction
        ("opt", "asymmetry", 1.0),         # Boldness → asymmetric risk appetite
    ],
    "sapientia": [
        ("lt", "fcf_margin", 1.2),         # Wisdom → free cash flow discipline
        ("lt", "rule_of_40", 1.2),         # Wisdom → growth + margin efficiency
    ],
    "fortuna": [
        ("lt", "discount_momentum", 1.5),  # Momentum → discount + momentum plays
        ("lt", "trend", 1.0),              # Momentum → trend-following
    ],
    "prospectus": [
        ("opt", "earnings_catalyst", 1.5), # Vision → earnings catalysts
        ("opt", "iv_context", 1.0),        # Vision → IV awareness
    ],
    "liquiditas": [
        ("opt", "liquidity", 1.2),         # Liquidity → trade execution quality
        ("opt", "technical", 1.0),         # Liquidity → technical setup
    ],
}

ATTRIBUTES = list(ATTRIBUTE_MAP.keys())
NEUTRAL_VALUE = 6
ATTRIBUTE_POOL = 36  # 6 attributes × 6 neutral = 36 total points


def validate_attributes(attrs: dict) -> tuple:
    """
    Validate attribute values. Returns (is_valid, error_message).
    Each attribute must be 1-10, total must equal ATTRIBUTE_POOL (36).
    """
    for attr in ATTRIBUTES:
        val = attrs.get(attr)
        if val is None:
            return False, f"Missing attribute: {attr}"
        if not isinstance(val, int) or val < 1 or val > 10:
            return False, f"{attr} must be an integer 1-10 (got {val})"

    total = sum(attrs[a] for a in ATTRIBUTES)
    if total != ATTRIBUTE_POOL:
        return False, f"Attribute total must be {ATTRIBUTE_POOL} (got {total})"

    return True, ""


def compute_user_weights(profile: dict, base_lt_weights: dict, base_opt_weights: dict) -> tuple:
    """
    Compute personalized LT and Opt weight dicts from an Augur profile.

    Args:
        profile: dict with keys matching ATTRIBUTES (e.g. {"prudentia": 8, "audacia": 4, ...})
        base_lt_weights: system LT weights (e.g. {"rule_of_40": 32.9, "valuation": 17.4, ...})
        base_opt_weights: system Opt weights

    Returns:
        (user_lt_weights, user_opt_weights) — both normalized to sum to 100.

    Each attribute point above/below neutral (6) shifts the mapped components:
        delta = (attribute_value - 6) / 6  → range [-0.833, +0.667]
        component_weight *= (1 + delta * influence_factor)
    Then normalize each weight dict to sum to 100.
    """
    user_lt = copy.deepcopy(base_lt_weights)
    user_opt = copy.deepcopy(base_opt_weights)

    for attr_name, mappings in ATTRIBUTE_MAP.items():
        attr_val = profile.get(attr_name, NEUTRAL_VALUE)
        delta = (attr_val - NEUTRAL_VALUE) / NEUTRAL_VALUE  # -0.833 to +0.667

        for score_type, component, influence in mappings:
            target = user_lt if score_type == "lt" else user_opt
            if component in target:
                multiplier = 1.0 + delta * influence
                # Clamp to prevent negative or absurdly high weights
                multiplier = max(0.3, min(2.0, multiplier))
                target[component] *= multiplier

    # Normalize both to sum to 100
    user_lt = _normalize_weights(user_lt)
    user_opt = _normalize_weights(user_opt)

    return user_lt, user_opt


def _normalize_weights(weights: dict) -> dict:
    """Normalize weight values to sum to 100, preserving ratios."""
    total = sum(weights.values())
    if total == 0:
        return weights
    factor = 100.0 / total
    return {k: round(v * factor, 1) for k, v in weights.items()}


def describe_augur(profile: dict) -> dict:
    """
    Generate a description of an Augur's personality based on attributes.
    Returns {dominant_trait, title_suggestion, style_description}.
    """
    attrs = {a: profile.get(a, NEUTRAL_VALUE) for a in ATTRIBUTES}
    dominant = max(attrs, key=attrs.get)
    dominant_val = attrs[dominant]

    titles = {
        "prudentia": "Oracle of Prudence",
        "audacia": "Champion of Fortune",
        "sapientia": "Sage of the Markets",
        "fortuna": "Rider of Momentum",
        "prospectus": "Seer of Catalysts",
        "liquiditas": "Master of Execution",
    }

    styles = {
        "prudentia": "Conservative value investor. Seeks undervalued companies with strong earnings.",
        "audacia": "Aggressive options trader. Seeks asymmetric risk/reward with high conviction.",
        "sapientia": "Fundamentals-driven analyst. Focuses on cash flow discipline and efficient growth.",
        "fortuna": "Momentum trader. Follows trends, discounts, and short-term price dynamics.",
        "prospectus": "Catalyst hunter. Times entries around earnings, IV cycles, and market events.",
        "liquiditas": "Technical executor. Prioritizes liquid markets and clean chart setups.",
    }

    return {
        "dominant_trait": dominant,
        "dominant_value": dominant_val,
        "title_suggestion": titles.get(dominant, "Novice Augur"),
        "style": styles.get(dominant, ""),
        "attributes": attrs,
    }


def rescore_with_user_weights(raw_scores: dict, user_weights: dict) -> float:
    """
    Recompute a total score from raw 0-1 component scores and user-specific weights.

    Args:
        raw_scores: {"rule_of_40": 0.85, "valuation": 0.6, ...} (0-1 per component)
        user_weights: {"rule_of_40": 28.5, "valuation": 22.1, ...} (sum to 100)

    Returns:
        Total score (0-100).
    """
    score = 0.0
    for component, weight in user_weights.items():
        raw = raw_scores.get(component, 0)
        score += max(0, min(1, raw)) * weight
    return round(score, 1)
