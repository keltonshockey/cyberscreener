"""
Point-in-time extraction from SEC companyfacts — the discipline that makes this
a backtest rather than a hindsight exercise.

THE WHOLE GAME (RESULT_LT_RECONSTRUCTION_2026-06-08 §3.1): for snapshot date D,
take the value whose `filed` <= D with the latest period `end`. A later
restatement of the same period carries a later `filed` and is therefore
automatically excluded. yfinance / "companyfacts latest" give the RESTATED
value and are forbidden — using them would leak the future into every snapshot.

Ported verbatim (numerically) from `~/mill-local-edits/lt_reconstruct.py` on
mill, the June engine that produced RESULT_LT_RECONSTRUCTION_2026-06-08 §7.
Behaviour is preserved exactly so Milestone A's reproduction is a real
regression gate; the reorganisation here is structural only.

Annual (FY / 10-K) figures are used for duration concepts. That is a deliberate
June choice — it avoids XBRL quarter-stitching errors at the cost of updating
only ~once a year. Milestone B re-tests the growth components at quarterly-TTM
resolution precisely because that coarseness may have starved them.
"""

from __future__ import annotations

import datetime as dt

# ── Concept mappings (filer-dependent; first concept with data wins) ──────────
REV = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]
OPINC = ["OperatingIncomeLoss"]
GROSS = ["GrossProfit"]
OCF = ["NetCashProvidedByUsedInOperatingActivities",
       "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]
EPS = ["EarningsPerShareDiluted", "EarningsPerShareBasic"]
SHARES = ["EntityCommonStockSharesOutstanding"]  # dei namespace, not us-gaap
DEBT_LT = ["LongTermDebtNoncurrent", "LongTermDebt"]
DEBT_CUR = ["LongTermDebtCurrent", "DebtCurrent"]
CASH = ["CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]

# A duration fact must span more than this many days to count as annual. 300
# rather than 365 because filers' fiscal years are not exactly 365 days.
ANNUAL_MIN_DAYS = 300


def parse_date(s: str) -> dt.date:
    """SEC dates are ISO; tolerate a trailing timestamp."""
    return dt.date.fromisoformat(s[:10])


def annual_facts(group: dict, concepts: list[str]) -> list[tuple[dt.date, dt.date, float]]:
    """
    (end, filed, val) for ANNUAL (fp=FY, form 10-K*) duration facts.

    Returns the first concept in `concepts` that has any data — filers disagree
    on which revenue tag they use, so the fallback order is load-bearing.
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
                form = f.get("form", "")
                duration = (parse_date(f["end"]) - parse_date(f["start"])).days
                if f.get("fp") == "FY" and form.startswith("10-K") and duration > ANNUAL_MIN_DAYS:
                    out.append((parse_date(f["end"]), parse_date(f["filed"]), f["val"]))
        if out:
            return out
    return []


def instant_facts(group: dict, concepts: list[str]) -> list[tuple[dt.date, dt.date, float]]:
    """(end, filed, val) for instant (balance-sheet) facts — no `start` key."""
    for c in concepts:
        node = group.get(c)
        if not node:
            continue
        out = []
        for _unit, arr in node.get("units", {}).items():
            for f in arr:
                if f.get("end") and "filed" in f and "start" not in f:
                    out.append((parse_date(f["end"]), parse_date(f["filed"]), f["val"]))
        if out:
            return out
    return []


def as_of_annual(facts, D: dt.date):
    """
    Latest annual value knowable on D → (end, val), or None.

    Two filters, both essential:
      `filed <= D`      — nothing that had not yet been filed on D
      earliest `filed`  — among facts for the same period end, take the FIRST
                          filing. That is the as-filed number; later entries for
                          the same end are restatements.
    """
    cand = [(e, fl, v) for (e, fl, v) in facts if fl <= D]
    if not cand:
        return None
    best_end = max(e for (e, _fl, _v) in cand)
    same = sorted([(fl, v) for (e, fl, v) in cand if e == best_end])
    return best_end, same[0][1]


def prior_annual(facts, D: dt.date, cur_end: dt.date):
    """The fiscal year ending ~1yr before `cur_end`, knowable on D — for YoY growth."""
    cand = [(e, fl, v) for (e, fl, v) in facts
            if fl <= D and e < cur_end and (cur_end - e).days >= ANNUAL_MIN_DAYS]
    if not cand:
        return None
    best_end = max(e for (e, _fl, _v) in cand)
    same = sorted([(fl, v) for (e, fl, v) in cand if e == best_end])
    return best_end, same[0][1]


def as_of_instant(facts, D: dt.date):
    """Latest instant value knowable on D → val, or None."""
    cand = [(e, fl, v) for (e, fl, v) in facts if fl <= D]
    if not cand:
        return None
    best_end = max(e for (e, _fl, _v) in cand)
    same = sorted([(fl, v) for (e, fl, v) in cand if e == best_end])
    return same[0][1]
