"""
Quarterly-TTM fundamentals — Milestone B (gated follow-up 1).

June used ANNUAL (FY / 10-K) figures deliberately, "to avoid XBRL
quarter-stitching errors". The cost is that rule_of_40, fcf_margin and
earnings_quality only update once a year, so their flatness in the June run
could be a RESOLUTION ARTIFACT rather than an absence of signal. This module
builds the quarterly-TTM alternative so that question can be answered instead
of assumed.

Quarter-stitching is genuinely the hard part, and it is where a backtest quietly
starts lying. Two traps handled explicitly:

  1. **Q4 is usually not filed.** Most registrants file 10-Qs for Q1–Q3 and roll
     Q4 into the 10-K. A naive "sum the quarterly facts" therefore silently
     builds a 3-quarter TTM for every fiscal year — understating revenue ~25%
     and inventing growth wherever the mix of available quarters changes.
  2. **Many filers report CUMULATIVE year-to-date**, not discrete quarters: the
     Q3 10-Q carries a 270-day period, not a 90-day one. Summing those
     double-counts massively.

Both are solved by derivation-by-subtraction over exact (start, end) periods,
never by assuming a shape. Every derived quarter is built only from facts with
`filed <= D`, so the PIT discipline of `pit.py` is preserved end to end.

`ttm_validation_report()` exists because this module could be wrong in ways that
still produce plausible numbers: it checks derived TTM against the independently
filed annual figure at fiscal year ends, which is the one place the two must
agree.
"""

from __future__ import annotations

import datetime as dt

from .pit import parse_date

# Duration classification, in days. Fiscal quarters are not exactly 91 days and
# 52/53-week filers drift, so these are deliberately wide.
QUARTER_MIN, QUARTER_MAX = 45, 135
ANNUAL_MIN, ANNUAL_MAX = 300, 430

# A TTM built from 4 quarters must span roughly a year.
TTM_SPAN_MIN, TTM_SPAN_MAX = 300, 430


def duration_facts(group: dict, concepts: list[str]) -> list[tuple[dt.date, dt.date, dt.date, float]]:
    """
    (start, end, filed, val) for every duration fact on 10-K/10-Q forms.

    Unlike `pit.annual_facts` this keeps ALL durations — quarterly, cumulative
    YTD and annual — because the stitcher needs the longer periods to derive the
    quarters that were never filed on their own.
    """
    for c in concepts:
        node = group.get(c)
        if not node:
            continue
        out = []
        for _unit, arr in node.get("units", {}).items():
            for f in arr:
                if not (f.get("start") and f.get("end") and "filed" in f):
                    continue
                if not f.get("form", "").startswith(("10-K", "10-Q")):
                    continue
                out.append((parse_date(f["start"]), parse_date(f["end"]),
                            parse_date(f["filed"]), f["val"]))
        if out:
            return out
    return []


def _as_filed_map(facts, D: dt.date) -> dict[tuple[dt.date, dt.date], float]:
    """
    {(start, end): val} for everything knowable at D, keeping the FIRST filing
    of each period — the as-filed number, never a later restatement.
    """
    best: dict[tuple[dt.date, dt.date], tuple[dt.date, float]] = {}
    for (s, e, fl, v) in facts:
        if fl > D or v is None:
            continue
        key = (s, e)
        if key not in best or fl < best[key][0]:
            best[key] = (fl, v)
    return {k: v for k, (_fl, v) in best.items()}


def discrete_quarters(facts, D: dt.date) -> dict[dt.date, float]:
    """
    {period_end: quarterly value} knowable at D.

    Direct quarterly facts are taken as-is. Anything else is derived by
    subtracting the immediately shorter period sharing the same `start`:

        Q4  = FY(start..end)      − 9mo(start..end−~90d)
        Q3  = 9mo(start..end)     − H1(start..end−~90d)

    A derivation is only accepted when the residual period is itself
    quarter-length, which is what stops a 6-month gap being booked as a quarter.
    """
    periods = _as_filed_map(facts, D)
    quarters: dict[dt.date, float] = {}

    # Pass 1 — periods that are already a quarter.
    for (s, e), v in periods.items():
        if QUARTER_MIN <= (e - s).days <= QUARTER_MAX:
            # Prefer the shortest qualifying period for a given end.
            if e not in quarters or (e - s).days < QUARTER_MAX:
                quarters.setdefault(e, v)

    # Pass 2 — derive the missing ones (typically Q4, and every quarter for
    # filers who report cumulative YTD).
    by_start: dict[dt.date, list[tuple[dt.date, float]]] = {}
    for (s, e), v in periods.items():
        by_start.setdefault(s, []).append((e, v))

    for s, ends in by_start.items():
        ends.sort()
        for i, (e, v) in enumerate(ends):
            if e in quarters:
                continue
            span = (e - s).days
            if span <= QUARTER_MAX:
                continue
            # Find the next-shortest period with the same start.
            for (pe, pv) in reversed(ends[:i]):
                residual = (e - pe).days
                if QUARTER_MIN <= residual <= QUARTER_MAX:
                    quarters[e] = v - pv
                    break
    return quarters


def ttm(facts, D: dt.date, as_of_end: dt.date | None = None) -> tuple[dt.date, float] | None:
    """
    Trailing-twelve-month sum knowable at D → (latest quarter end, value).

    Requires four quarters whose combined span is about a year; returns None
    rather than a short sum, because a 3-quarter "TTM" is exactly the silent
    understatement this module exists to avoid.
    """
    quarters = discrete_quarters(facts, D)
    if not quarters:
        return None
    ends = sorted(e for e in quarters if as_of_end is None or e <= as_of_end)
    if len(ends) < 4:
        return None
    window = ends[-4:]
    # The four must be contiguous in time, not four scattered survivors.
    span = (window[-1] - window[0]).days
    if not (TTM_SPAN_MIN - 120 <= span + 91 <= TTM_SPAN_MAX + 60):
        return None
    return window[-1], sum(quarters[e] for e in window)


def ttm_prior(facts, D: dt.date, cur_end: dt.date) -> float | None:
    """TTM ending ~1 year before `cur_end`, knowable at D — the YoY denominator."""
    quarters = discrete_quarters(facts, D)
    ends = sorted(quarters)
    target = [e for e in ends if (cur_end - e).days >= ANNUAL_MIN - 60]
    if not target:
        return None
    prior_end = target[-1]
    window = [e for e in ends if e <= prior_end][-4:]
    if len(window) < 4:
        return None
    return sum(quarters[e] for e in window)


def ttm_validation_report(facts, D: dt.date, annual_facts_list) -> list[dict]:
    """
    Cross-check derived TTM against the independently filed ANNUAL figure at
    fiscal year ends. They measure the same thing by different routes, so a
    material disagreement means the stitcher is wrong — the check that makes
    this module falsifiable rather than merely plausible.
    """
    quarters = discrete_quarters(facts, D)
    out = []
    for (end, filed, val) in annual_facts_list:
        if filed > D:
            continue
        ends = sorted(e for e in quarters if e <= end)
        if len(ends) < 4:
            continue
        window = ends[-4:]
        if window[-1] != end:
            continue
        stitched = sum(quarters[e] for e in window)
        if val:
            out.append({"end": end, "annual": val, "ttm": stitched,
                        "rel_err": abs(stitched - val) / abs(val)})
    return out
