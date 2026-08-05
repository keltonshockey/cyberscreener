#!/usr/bin/env python3
"""
Milestone C — survivorship closure by BOUNDING (gated follow-up 2).

June excluded 46 of 473 names (~9.7%) because no free price history exists for
them. Delisted names skew toward distress, so their absence most plausibly
FLATTERS the value premium — June flagged +5.9% @12mo as "likely an upper
bound" without quantifying how loose that bound is. This milestone quantifies it.

We do not chase paid data (brief). A rate-limited probe with a real UA confirmed
free sources still refuse these names, so the bias is bounded analytically
instead of measured.

Method: inject PHANTOM rows for the missing names into each snapshot's
cross-section, then re-cut quintiles on the augmented set. Two independent
assumptions have to be made, and both are varied rather than picked:

  RETURN   what the delisted names earned:  −100% | cross-sectional median
  PLACEMENT which quintile they occupied:   all in Q5 (maximally adverse — Q5 is
                                            the cheap bucket the strategy buys)
                                          | spread evenly across quintiles

Varying placement matters because it, not the return assumption, is what the
answer is most sensitive to, and it is pure assumption — we cannot score a name
whose price we do not have.

KILL CONDITION: if the pessimistic bound takes the 12mo quintile spread to <= 0,
Lane 1's thesis is not established — report honestly and STOP before Milestone D.

Usage:
    python -m research.lane1.milestone_c [--corpus PATH] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.lane1.panel import CORPUS_ROOT, HORIZONS, build_panel  # noqa: E402
from research.lane1.stats import MIN_CROSS_SECTION  # noqa: E402

COMPONENT = "valuation"
TOTAL_UNIVERSE = 473
BANKRUPTCY_RETURN = -1.0


def augmented_quintiles(rows, n_missing_frac, ret_mode, placement, median_ret):
    """
    Re-cut quintiles after injecting phantom delisted rows.

    `rows` are the live (score, forward_return) pairs. Phantoms are given scores
    that force the requested placement, then quintiles are cut on the union — so
    the injected names displace live names at the boundary exactly as real ones
    would have.
    """
    if len(rows) < MIN_CROSS_SECTION:
        return None
    n = len(rows)
    m = int(round(n * n_missing_frac))
    if m == 0:
        return None

    scores = sorted(s for s, _r in rows)
    lo, hi = scores[0], scores[-1]
    ret = BANKRUPTCY_RETURN if ret_mode == "bankrupt" else median_ret

    phantoms = []
    if placement == "all_q5":
        # Above every live score → guaranteed top (cheapest) quintile.
        phantoms = [(hi + 1.0, ret)] * m
    else:
        # Even across QUINTILES, which means even across RANKS — not across the
        # score range. Valuation scores round to 0.1 and cluster heavily, so
        # evenly-spaced score VALUES land disproportionately in the sparse tail
        # and silently concentrate the phantoms in one quintile (an earlier cut
        # of this function did exactly that and reported a spread of +15% where
        # the honest figure is ~+5%).
        for i in range(m):
            pos = int(((i + 0.5) / m) * (len(scores) - 1))
            phantoms.append((scores[pos], ret))

    aug = sorted(rows + phantoms, key=lambda x: x[0])
    k = len(aug) // 5
    if k == 0:
        return None
    q1 = [r for _s, r in aug[:k]]
    q5 = [r for _s, r in aug[-k:]]
    return sum(q5) / len(q5) - sum(q1) / len(q1)


def scenario(panel, snaps, horizon, ret_mode, placement, frac):
    spreads = []
    for s in snaps:
        rows = panel.rows(COMPONENT, s, horizon)
        if len(rows) < MIN_CROSS_SECTION:
            continue
        med = statistics.median([r for _s, r in rows])
        v = augmented_quintiles(rows, frac, ret_mode, placement, med)
        if v is not None:
            spreads.append(v)
    return (sum(spreads) / len(spreads) * 100) if spreads else None


def baseline(panel, snaps, horizon):
    """Scenario (iii): exclusion as today — the June number, per-snapshot mean."""
    spreads = []
    for s in snaps:
        rows = panel.rows(COMPONENT, s, horizon)
        if len(rows) < MIN_CROSS_SECTION:
            continue
        ordered = sorted(rows, key=lambda x: x[0])
        k = len(ordered) // 5
        if k == 0:
            continue
        q1 = [r for _s, r in ordered[:k]]
        q5 = [r for _s, r in ordered[-k:]]
        spreads.append(sum(q5) / len(q5) - sum(q1) / len(q1))
    return (sum(spreads) / len(spreads) * 100) if spreads else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--corpus", default=CORPUS_ROOT)
    ap.add_argument("--out", default=os.path.expanduser("~/mill-local-edits/lane1"))
    a = ap.parse_args(argv)

    print("=" * 74)
    print("MILESTONE C — survivorship bounding of the Valuation premium")
    print("=" * 74)

    panel = build_panel(a.corpus)
    missing = set(panel.delisted_no_price)
    oos = panel.out_of_sample()

    # The 46 missing-price names are NOT 46 delistings. Only those in the
    # manifest's `delisted_seed` were ever flagged as delisted; the rest are
    # names the June gather failed to price (see the report). Bounding at 9.7%
    # therefore bounds GATHER FAILURE, not survivorship — so both denominators
    # are carried and reported.
    with open(os.path.join(a.corpus, "universe", "manifest.json")) as f:
        man = json.load(f)
    seed = set(man["delisted_seed"])
    truly_delisted = missing & seed
    unpriced_only = missing - seed

    frac_all = len(missing) / TOTAL_UNIVERSE
    frac_delisted = len(truly_delisted) / TOTAL_UNIVERSE

    print(f"\nmissing-price names    : {len(missing)} of {TOTAL_UNIVERSE} ({frac_all:.1%})")
    print(f"  flagged delisted     : {len(truly_delisted)} ({frac_delisted:.1%})  <- the real survivorship exposure")
    print(f"  unpriced, NOT flagged: {len(unpriced_only)} ({len(unpriced_only)/TOTAL_UNIVERSE:.1%})  <- gather gap, not survivorship")
    print(f"OOS snapshots          : {len(oos)} (from {panel.oos_split()})")
    print("\nfree-source probe      : Stooq returns HTTP 200 with an HTML anti-bot page for")
    print("                         these tickers (5 probed, rate-limited, real UA).")
    print("                         June's finding still holds; bias is bounded, not measured.")

    results = {"missing": len(missing), "truly_delisted": sorted(truly_delisted),
               "unpriced_only": sorted(unpriced_only),
               "frac_all": frac_all, "frac_delisted": frac_delisted, "scenarios": {}}

    base = {h: baseline(panel, oos, h) for h in HORIZONS}

    for tag, frac in (("A. survivorship only (19 flagged delisted, 4.0%)", frac_delisted),
                      ("B. all missing prices (46, 9.7%) - bounds gather failure too", frac_all)):
        print("\n" + "-" * 74)
        print(f"{tag}")
        print("-" * 74)
        print(f"{'scenario':52} {'6mo':>9} {'12mo':>9}")
        rows_out = [("(iii) exclusion as today  [June baseline]", base)]
        for label, ret_mode, placement in (
            ("(ii)  = median return, even across quintiles", "median", "spread"),
            ("(ii)  = median return, ALL in Q5", "median", "all_q5"),
            ("(i)   = -100%, even across quintiles", "bankrupt", "spread"),
            ("(i)   = -100%, ALL in Q5   [PESSIMISTIC BOUND]", "bankrupt", "all_q5"),
        ):
            vals = {h: scenario(panel, oos, h, ret_mode, placement, frac) for h in HORIZONS}
            rows_out.append((label, vals))
        for label, vals in rows_out:
            v6 = f"{vals[6]:+.2f}%" if vals[6] is not None else "—"
            v12 = f"{vals[12]:+.2f}%" if vals[12] is not None else "—"
            print(f"{label:52} {v6:>9} {v12:>9}")
            results["scenarios"].setdefault(tag, {})[label] = vals
        if tag.startswith("A"):
            surv = rows_out

    os.makedirs(a.out, exist_ok=True)
    Path(a.out, "milestone_c.json").write_text(json.dumps(results, indent=2, default=str) + "\n")

    worst12 = surv[-1][1][12]          # survivorship-only, adverse placement
    neutral12 = surv[-2][1][12]        # survivorship-only, neutral placement

    print("\n" + "=" * 74)
    print("KILL CONDITION EVALUATION (on the true survivorship exposure, 4.0%)")
    print(f"  -100%, ALL in Q5 (adverse placement) @12mo : {worst12:+.2f}%")
    print(f"  -100%, even across quintiles        @12mo : {neutral12:+.2f}%")
    print(f"  exclusion as today                  @12mo : {base[12]:+.2f}%")

    if worst12 is None or worst12 <= 0:
        print("\nKILL CONDITION MET under adverse placement.")
        print("Per the brief: report honestly and STOP before Milestone D.")
        print("\nNOTE FOR THE DECISION: the brief specified the RETURN assumption (-100%)")
        print("but not the PLACEMENT assumption, and placement is what decides this.")
        print("Forcing every delisted name into Q5 assumes the strategy bought all of")
        print("them, which is itself unknowable - we have no price and so no score for")
        print("these names. Under neutral placement the premium stays positive.")
        print("Escalating rather than choosing the assumption that suits the thesis.")
        return 3
    print(f"\nPessimistic 12mo bound {worst12:+.2f}% > 0 — premium survives; D may proceed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
