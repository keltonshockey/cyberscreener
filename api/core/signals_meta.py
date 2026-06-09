"""
Signal relevance metadata (UI_OVERHAUL_PLAN §6b) — the authoritative, server-side
home for what was previously inferred client-side in `frontend/src/utils/signals.js`.

Every scoring signal carries four pieces of relevance metadata so the feed (and,
later, the score) can reason over it instead of guessing:

  • ``stack``          — ``lt`` / ``options`` / ``both``: which stack the signal
                         informs. The Forum (long-term) view hides options-only
                         signals; Pactum foregrounds them.
  • ``polarity``       — ``tailwind`` / ``headwind`` / ``event``: directional read
                         for color + grouping (Thesis drivers / Risks / Catalysts).
  • ``sector_context`` — applicability tag. Most signals are ``general``; a few are
                         sector-specific (e.g. threat-landscape demand only applies
                         to cyber vendors, and is a headwind for a breach victim).
                         ``suppress`` means the signal is noise for THIS stock —
                         it should neither show nor (eventually) score.
  • ``dedupe_key``     — normalized identity so repeats collapse to one row.

``impact`` (positive/negative/neutral) is derived from polarity, replacing the old
emoji-sniffing heuristic in ``save_scan`` (the API no longer emits emoji, so the
old ``"🚀" in reason`` test always returned neutral).
"""

import re

# Stack relevance — does the signal speak to a long-term thesis or a tactical trade?
_OPTIONS_RE = re.compile(
    r"iv rank|implied vol|\biv\b|premium|directional|straddle|strangle|theta|"
    r"p/c ratio|put/call|\bdte\b|expiry|condor|spread|delta|squeeze|breakout|"
    r"unusual (call|put)|whale|flow|beta|high short", re.I)
_LT_RE = re.compile(
    r"rule of 40|fcf|ev/rev|valuation|p/e|\bpe\b|dividend|moat|compounder|"
    r"free cash|margin|revenue|profitable|deep value|fair value|expensive|"
    r"uptrend|moving average", re.I)

# Catalyst (an event with a date/trigger) vs ongoing risk.
_CATALYST_RE = re.compile(
    r"earnings|8-k|analyst|target|filing|insider|catalyst|squeeze|breakout|"
    r"oversold|overbought", re.I)
_RISK_RE = re.compile(
    r"\brisk|headwind|cooling|expensive|burn|weak|below|overbought|dilut|"
    r"\bdebt|miss|shrinking|value trap|wide spread|building.*headwind", re.I)

# Sector-specific: threat-landscape / demand signals only mean something for
# security vendors; for a breach victim they are a headwind; else noise.
_THREAT_RE = re.compile(r"threat landscape|active threat|demand signal|breach", re.I)

# Positive / negative wording — used to derive polarity when no other rule fires.
_POSITIVE_RE = re.compile(
    r"elite|passing|deep value|fair value|excellent|strong|profitable|"
    r"near highs|covering|cheap|prime window|squeeze setup|breakout imminent|"
    r"institutional positioning|good for", re.I)
_NEGATIVE_RE = re.compile(
    r"below threshold|negative|expensive|cash burn|weak|shrinking|value trap|"
    r"wide spread|headwind|overbought|high short interest", re.I)

_NORM_STRIP = re.compile(r"[\d.,$%+\-—·()]+")
_NORM_WS = re.compile(r"\s+")


def dedupe_key(text):
    """Normalized identity: lowercase, drop numbers/punctuation, collapse space.

    "Analyst target $30.01" and "Analyst target $28.50" collapse to the same key
    so the feed shows the signal once with a count instead of N near-identical rows.
    """
    t = _NORM_STRIP.sub(" ", (text or "").lower())
    return _NORM_WS.sub(" ", t).strip()


def _infer_stack(t):
    opt = bool(_OPTIONS_RE.search(t))
    lt = bool(_LT_RE.search(t))
    if opt and not lt:
        return "options"
    if lt and not opt:
        return "lt"
    return "both"


def classify_signal(text, *, sector=None, breach_victim=False):
    """Return relevance metadata for a single signal string.

    Args:
        text: the (emoji-free) signal/reason text.
        sector: the ticker's coarse sector ("cyber", "energy", ...), for the
            sector-context gate.
        breach_victim: True if this ticker is itself a breach victim.

    Returns dict: ``{stack, polarity, sector_context, dedupe_key, impact, applies}``.
    ``applies`` is False when the signal is noise for this stock (it should be
    hidden and must not contribute to the score — the §6b scoring gate).
    """
    t = text or ""
    stack = _infer_stack(t)
    sector_context = "general"
    applies = True

    # Polarity: explicit risk wording wins, then catalyst, then positive/negative.
    if _RISK_RE.search(t) or _NEGATIVE_RE.search(t):
        polarity = "headwind"
    elif _POSITIVE_RE.search(t):
        polarity = "tailwind"
    elif _CATALYST_RE.search(t):
        polarity = "event"
    else:
        polarity = "event"

    # Sector-context gate — threat/demand is only relevant to security vendors.
    if _THREAT_RE.search(t):
        if breach_victim:
            sector_context, polarity = "breach-headwind", "headwind"
        elif sector == "cyber":
            sector_context = "cyber-demand"
            if polarity == "event":
                polarity = "tailwind"
        else:
            sector_context, applies = "suppress", False

    impact = (
        "positive" if polarity == "tailwind"
        else "negative" if polarity == "headwind"
        else "neutral"
    )

    return {
        "stack": stack,
        "polarity": polarity,
        "sector_context": sector_context,
        "dedupe_key": dedupe_key(t),
        "impact": impact,
        "applies": applies,
    }
