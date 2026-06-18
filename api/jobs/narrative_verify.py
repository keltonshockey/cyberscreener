"""
Grounding / fact-check gates for the narrative pipeline (the part that matters
most — NARRATIVE_LAYER_PLAN.md anti-slop design). Pure functions, no network, no
model — fully testable offline.

Gates (any failure => the story is rejected; the pipeline regens once, then falls
to a signals-only floor):
  * number_match    — every numeric in the prose must match a signal-snapshot
                      value (within tolerance) or a fetched figure.
  * citation        — every claim must map to a provided signal or a fetched
                      source id.
  * fabricated_source — used_sources / claim source-ids must all be fetched ids
                      (cite-only-fetched: no invented URLs).
  * boilerplate     — reject generic "leading provider of..." filler.
"""

import re
from datetime import datetime

# Numbers that are part of metric NAMES, not measurements (so we don't reject
# "Rule-of-40", "52-week", "20/50 SMA", "10-K", "RSI 30").
_THIS_YEAR = datetime.utcnow().year
STRUCTURAL_NUMBERS = {8, 10, 14, 20, 30, 40, 50, 52, 100, 200} | {
    y for y in range(_THIS_YEAR - 6, _THIS_YEAR + 2)
}

_NUM_RE = re.compile(r"(?<![\w.])\$?-?\d+(?:,\d{3})*(?:\.\d+)?%?")

_BOILERPLATE_RES = [
    re.compile(p, re.I) for p in (
        r"\bleading provider\b",
        r"\bis a leading\b",
        r"\bworld[- ]class\b",
        r"\bcutting[- ]edge\b",
        r"\bbest[- ]in[- ]class\b",
        r"\bmarket leader\b",
        r"\bindustry leader\b",
        r"\btrusted by\b",
        r"\binnovative solutions\b",
        r"\bglobal leader\b",
    )
]


def extract_numbers(text: str) -> list:
    """All numeric tokens in `text` as floats (strips $ , %)."""
    out = []
    for m in _NUM_RE.findall(text or ""):
        tok = m.replace("$", "").replace(",", "").replace("%", "")
        try:
            out.append(float(tok))
        except ValueError:
            continue
    return out


def _flatten_numeric(obj) -> list:
    """Every numeric value reachable in a snapshot dict/list."""
    vals = []
    if isinstance(obj, bool):
        return vals
    if isinstance(obj, (int, float)):
        vals.append(float(obj))
    elif isinstance(obj, dict):
        for v in obj.values():
            vals.extend(_flatten_numeric(v))
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            vals.extend(_flatten_numeric(v))
    elif isinstance(obj, str):
        vals.extend(extract_numbers(obj))
    return vals


def _measured_numbers(snapshot: dict, facts: list) -> list:
    """Numbers from signal values + fetched facts — matched WITH tolerance."""
    allowed = _flatten_numeric(snapshot or {})
    for f in facts or []:
        allowed += extract_numbers(f.get("title", ""))
        allowed += extract_numbers(f.get("date", ""))
    return allowed


def _num_supported(n: float, measured: list, rel: float = 0.02, abs_tol: float = 0.5) -> bool:
    # Metric-name constants (Rule-of-40, 52-week, SMA periods) must match exactly
    # so a tolerance window around them can't whitewash a wrong figure (99 vs 100).
    if n in STRUCTURAL_NUMBERS:
        return True
    for a in measured:
        if abs(n - a) <= max(abs_tol, rel * abs(a)):
            return True
    return False


def check_numbers(text: str, snapshot: dict, facts: list) -> list:
    """Return the list of unsupported numbers found in `text` (empty == clean)."""
    measured = _measured_numbers(snapshot, facts)
    return [n for n in extract_numbers(text) if not _num_supported(n, measured)]


def check_boilerplate(text: str) -> list:
    """Return boilerplate phrases found (empty == clean)."""
    hits = []
    for rx in _BOILERPLATE_RES:
        m = rx.search(text or "")
        if m:
            hits.append(m.group(0))
    return hits


def valid_source_ids(facts: list) -> set:
    """Citable ids: each fetched fact id, plus the literal "signal" for claims
    grounded directly on a snapshot value."""
    return {f["id"] for f in (facts or [])} | {"signal"}


def verify(parsed: dict, snapshot: dict, facts: list) -> tuple:
    """Run every gate. Returns (ok: bool, reasons: list[str]).

    reasons codes: number_mismatch, unsupported_citation, fabricated_source,
    boilerplate, empty_story.
    """
    reasons = []
    lt = (parsed or {}).get("lt_story") or ""
    st = (parsed or {}).get("st_story") or ""
    claims = (parsed or {}).get("claims") or []
    used = (parsed or {}).get("used_sources") or []
    valid_ids = valid_source_ids(facts)

    if not lt.strip() and not st.strip():
        return False, ["empty_story"]

    # number-match across both sections
    bad_nums = check_numbers(lt, snapshot, facts) + check_numbers(st, snapshot, facts)
    if bad_nums:
        reasons.append("number_mismatch")

    # boilerplate
    if check_boilerplate(lt) or check_boilerplate(st):
        reasons.append("boilerplate")

    # citation: every claim must carry a valid source id
    for c in claims:
        sid = (c or {}).get("source_id")
        if sid not in valid_ids:
            reasons.append("unsupported_citation")
            break

    # cite-only-fetched: any EXTERNAL source cited must be a fetched fact id.
    # "signal" is the in-house grounding id (not an external source), so it is
    # exempt from the fabrication check.
    fetched_ids = {f["id"] for f in (facts or [])}
    for sid in used:
        if sid == "signal":
            continue
        if sid not in fetched_ids:
            reasons.append("fabricated_source")
            break

    return (len(reasons) == 0), reasons
