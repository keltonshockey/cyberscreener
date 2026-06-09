"""
Quality gates — two-stage eligibility + conviction pipeline for the LT stack.

Motivation (the GEN value-trap): a serial acquirer can read as hyper-growth SaaS
because the model can't tell organic demand from M&A accounting, and an elite-on-
paper / cheap / net-sold-for-a-year name can top the board with zero corroboration.
This module gates that WITHOUT touching the raw LT/Opt component scores (so it does
not collide with the valuation/options weight work): it is a pure post-processor.

Two stages:
  1. evaluate_eligibility(row)  — Tier A HARD-EXCLUDE on solvency + liquidity
     failures (non-negotiable for live capital). An excluded name leaves the board.
  2. conviction_modifiers(row)  — Tier B CAP-DON'T-KILL conviction penalties. The
     name stays visible; it just can't top the board / reach High conviction.

Every gate fires ONLY when its input is present in `row`; a missing input is a
no-op (graceful degradation), so wiring this in never silently drops a name on
absent data. `assess()` bundles both stages.

PIT validation (mill `~/lt-recon-data`, 127 monthly snaps 2014-12..2025-06, two
regime halves split 2021-04; see RESULT_QUALITY_GATES). Thresholds are economically
motivated and validated for SIGN-CONSISTENCY across both halves, not fit to data:
  - A5 interest-coverage <1.0 : worse high-LT left-tail in BOTH halves (-2.1, -2.6).  [EARNS]
  - B3 secular-decline         : worse high-LT mean (-6.8, -4.6) AND tail in BOTH.     [EARNS]
  - B1 organic-normalization   : return-NEUTRAL on aggregate (Rule-of-40 IC is 3x
        weaker on M&A names in regime A: +0.017 vs +0.055); included as a value-trap
        de-rater at no aggregate cost, NOT as an alpha source.                          [risk-control]
  - B2 corroboration cap       : the testable proxy (1y trend) did NOT improve returns;
        kept as a cap-don't-kill risk control per standing decision (3 of its 4 live
        signals — sentiment/whale/insider — are unvalidatable on the historical corpus). [risk-control]
  - A4 Altman-Z, A6 net-debt/EBITDA, A7 accumulated-deficit: REJECTED (mis-calibrated
        for an asset-light universe / regime-inconsistent / wrong sign). Not implemented.

Input fields consumed (all optional). Those marked (live) are already on the scores
row today; (needs-scanner) require a small scanner addition before the gate activates:
  Tier A: price (live), market_cap_b (live), dollar_volume (needs-scanner:
          close*averageVolume), interest_coverage (needs-scanner: EBIT/interest_expense).
  Tier B: lt_breakdown.rule_of_40.points (live); acquisition_flag (needs-scanner: a
          bool from goodwill-step / shares-growth / business-acquisition cash-flow);
          rev_cagr_3y + op_margin_delta_3y (needs-scanner: multi-year trend);
          sentiment_bull_pct (live), whale_score (live), insider_buys_30d (live),
          perf_1y (needs-scanner; perf_3m used as a fallback corroboration proxy).
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field

# ── Tier A thresholds (hard-exclude) ──────────────────────────────────────────
PRICE_FLOOR = 5.0            # $ — sub-$5 = delisting/penny risk, untradeable at size
MCAP_FLOOR_B = 0.3           # $B — $300M micro-cap floor
DOLLAR_VOL_FLOOR = 2_000_000  # $/day median — investability
INTEREST_COV_FLOOR = 1.0     # EBIT / interest expense; <1.0 = can't cover interest

# ── Tier B thresholds (conviction modifiers) ──────────────────────────────────
RULE_OF_40_MAX = 25.0        # component max (DEFAULT_LT_WEIGHTS)
R40_ORGANIC_CAP = 15.0       # M&A names get at most 60% Rule-of-40 credit on the board
SECULAR_REV_CAGR_MAX = 2.0   # % 3y revenue CAGR
SECULAR_LT_PENALTY = 8.0     # board points removed for organic secular decline
LT_WEIGHT_IN_CONVICTION = 0.4  # combined = opt*0.6 + lt*0.4

HIGH_FLOOR = 55.0            # combined-conviction High threshold (matches killer-plays)
SOLID_FLOOR = 45.0


def _component_points(row, key):
    """rule_of_40 (etc.) points from the stored lt_breakdown (dict or JSON str)."""
    bd = row.get("lt_breakdown")
    if isinstance(bd, str):
        try:
            bd = json.loads(bd)
        except (ValueError, TypeError):
            return None
    if not isinstance(bd, dict):
        return None
    entry = bd.get(key)
    if isinstance(entry, dict):
        return entry.get("points")
    return entry if isinstance(entry, (int, float)) else None


def is_acquisition_inflated(row):
    """M&A-flag. Prefer an explicit scanner-provided bool; else derive from any of
    the inorganic step signatures when present. None of these present -> False."""
    if row.get("acquisition_flag") is not None:
        return bool(row["acquisition_flag"])
    acq = row.get("acq_spend_pct_rev")
    gw = row.get("goodwill_step_pct_rev")
    sh = row.get("shares_growth_pct")
    if acq is None and gw is None and sh is None:
        return False
    return (acq or 0) > 5 or (gw or 0) > 10 or (sh or 0) > 8


def is_secular_decline(row):
    """Multi-year ORGANIC revenue stagnation + margin erosion. A flag, not an oracle
    — 'being replaced by AI' isn't reliably automatable. Requires both inputs."""
    cagr = row.get("rev_cagr_3y")
    dmargin = row.get("op_margin_delta_3y")
    if cagr is None or dmargin is None:
        return False
    return cagr < SECULAR_REV_CAGR_MAX and dmargin < 0


def has_corroboration(row):
    """>=1 live corroborating signal permits High conviction. Under-followed names
    stay ELIGIBLE — this only caps the tier, never excludes (cap-don't-kill)."""
    signals = (
        (row.get("sentiment_bull_pct") or 0) > 0,
        (row.get("whale_score") or 0) > 0,
        (row.get("insider_buys_30d") or 0) > 0,
        (row.get("perf_1y") if row.get("perf_1y") is not None else row.get("perf_3m") or 0) > 0,
    )
    return any(signals)


@dataclass
class QualityAssessment:
    eligible: bool = True
    exclude_reasons: list = field(default_factory=list)
    lt_penalty: float = 0.0          # subtract from lt_score for the gated LT board
    conviction_penalty: float = 0.0  # subtract from combined conviction
    tier_cap: str | None = None      # 'SOLID' caps a name below High (no corroboration)
    modifier_reasons: list = field(default_factory=list)


def evaluate_eligibility(row) -> tuple[bool, list]:
    """Tier A — hard-exclude. Returns (eligible, reasons)."""
    reasons = []
    price = row.get("price")
    if price is not None and price < PRICE_FLOOR:
        reasons.append(f"price ${price:.2f} < ${PRICE_FLOOR:.0f} floor")
    mcap = row.get("market_cap_b")
    if mcap is not None and mcap < MCAP_FLOOR_B:
        reasons.append(f"market cap ${mcap:.2f}B < ${MCAP_FLOOR_B:.1f}B floor")
    dvol = row.get("dollar_volume")
    if dvol is not None and dvol < DOLLAR_VOL_FLOOR:
        reasons.append(f"dollar volume ${dvol/1e6:.1f}M/day < ${DOLLAR_VOL_FLOOR/1e6:.0f}M floor")
    icov = row.get("interest_coverage")
    if icov is not None and icov < INTEREST_COV_FLOOR:
        reasons.append(f"interest coverage {icov:.2f}x < {INTEREST_COV_FLOOR:.1f}x")
    return (len(reasons) == 0, reasons)


def conviction_modifiers(row) -> tuple[float, float, str | None, list]:
    """Tier B — cap-don't-kill. Returns (lt_penalty, conviction_penalty, tier_cap, reasons).
    Isolated from raw component scores: reads, never mutates, lt_breakdown."""
    lt_penalty = 0.0
    tier_cap = None
    reasons = []

    # B1 organic-growth normalization — discount M&A-inflated Rule-of-40 on the board.
    if is_acquisition_inflated(row):
        r40 = _component_points(row, "rule_of_40")
        if r40 is not None and r40 > R40_ORGANIC_CAP:
            excess = r40 - R40_ORGANIC_CAP
            lt_penalty += excess
            reasons.append(
                f"organic-normalization: M&A-inflated Rule-of-40 {r40:.0f} capped to "
                f"{R40_ORGANIC_CAP:.0f} (-{excess:.0f} board pts)")

    # B3 secular-decline down-weight.
    if is_secular_decline(row):
        lt_penalty += SECULAR_LT_PENALTY
        reasons.append(
            f"secular-decline: 3y rev CAGR {row['rev_cagr_3y']:.1f}% + eroding margin "
            f"(-{SECULAR_LT_PENALTY:.0f} board pts)")

    # B2 interest-corroboration cap — no High tier without >=1 corroborating signal.
    if not has_corroboration(row):
        tier_cap = "SOLID"
        reasons.append("no corroboration (sentiment/whale/insider/1y-trend all flat) "
                       "-> capped below High")

    conviction_penalty = lt_penalty * LT_WEIGHT_IN_CONVICTION
    return lt_penalty, conviction_penalty, tier_cap, reasons


def assess(row) -> QualityAssessment:
    """Full two-stage assessment for one scored row."""
    eligible, ex_reasons = evaluate_eligibility(row)
    if not eligible:
        return QualityAssessment(eligible=False, exclude_reasons=ex_reasons)
    lt_pen, conv_pen, cap, mod_reasons = conviction_modifiers(row)
    return QualityAssessment(eligible=True, lt_penalty=lt_pen,
                             conviction_penalty=conv_pen, tier_cap=cap,
                             modifier_reasons=mod_reasons)


def gated_tier(combined_conviction, assessment: QualityAssessment) -> str:
    """HIGH / SOLID / WATCH from a gated combined-conviction score, respecting the
    Tier-B tier cap. Mirrors the killer-plays thresholds (55 / 45)."""
    score = combined_conviction - assessment.conviction_penalty
    if score >= HIGH_FLOOR and assessment.tier_cap != "SOLID":
        return "HIGH"
    if score >= SOLID_FLOOR:
        return "SOLID"
    return "WATCH"
