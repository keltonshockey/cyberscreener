#!/usr/bin/env python3
"""
Milestone A regression gate — reproduce the June reconstruction from the corpus.

If this does not reproduce, either the corpus changed or the port is wrong, and
NOTHING downstream is trustworthy. The brief's instruction is explicit: STOP.

Reference (RESULT_LT_RECONSTRUCTION_2026-06-08 §7):

    panel        427 names, 127 monthly snapshots 2014-12-01..2025-06-01
    valuation    IC +0.0380 t +6.85 (6mo)   H1 +0.0153  H2 +0.0611
                 IC +0.0551 t +11.40 (12mo) H1 +0.0325  H2 +0.0780
    val Q5-Q1    6mo  IN +1.67%  OOS +2.48%
                 12mo IN +3.07%  OOS +5.93%

Usage:
    python -m research.lane1.reproduce_june [--corpus PATH] [--out DIR] [--json]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.lane1.panel import CORPUS_ROOT, HORIZONS, build_panel  # noqa: E402
from research.lane1.scoring import COMPONENTS  # noqa: E402
from research.lane1.stats import pooled_quintiles  # noqa: E402

# The June headline, and the tolerance each figure must land inside.
#
# Tolerance rationale: the port is intended to be numerically IDENTICAL, so IC
# and half-means are held to 0.0005 — tight enough that any real methodology
# drift (a changed split point, a different tie rule, a leaked restatement)
# breaks it, loose enough to absorb float-summation ordering. Quintile spreads
# are percentages of pooled returns and get 0.05pp on the same logic.
JUNE_REFERENCE = {
    "panel": {"n_names": 427, "n_snaps": 127, "delisted_no_price": 46},
    "valuation": {
        6: {"mean_ic": 0.0380, "t": 6.85, "ic_h1": 0.0153, "ic_h2": 0.0611},
        12: {"mean_ic": 0.0551, "t": 11.40, "ic_h1": 0.0325, "ic_h2": 0.0780},
    },
    "valuation_quintile": {
        6: {"in": 1.67, "oos": 2.48},
        12: {"in": 3.07, "oos": 5.93},
    },
}
IC_TOL = 0.0005
T_TOL = 0.02
SPREAD_TOL_PP = 0.05


def component_quintile(panel, component, snap_list, horizon):
    per_snap = [panel.rows(component, s, horizon) for s in snap_list]
    return pooled_quintiles(per_snap)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--corpus", default=CORPUS_ROOT)
    ap.add_argument("--out", default=os.path.expanduser("~/mill-local-edits/lane1"))
    ap.add_argument("--json", action="store_true", help="also write reproduce_june.json")
    a = ap.parse_args(argv)

    print(f"corpus: {a.corpus}")
    print("building PIT panel (as-filed, filed<=D) ...", flush=True)
    panel = build_panel(a.corpus)

    coverage = sorted(len(panel.entries[s]) for s in panel.snaps)
    median_cov = coverage[len(coverage) // 2]
    print(f"panel: {panel.n_names} names, {len(panel.snaps)} snapshots "
          f"{panel.snaps[0]}..{panel.snaps[-1]}, median {median_cov} names/snapshot")
    print(f"delisted without prices (survivorship gap): {len(panel.delisted_no_price)}")
    print(f"sub-period midpoint: {panel.midpoint()}   OOS split: {panel.oos_split()} "
          f"({len(panel.in_sample())} in / {len(panel.out_of_sample())} out)")
    print()

    failures: list[str] = []

    def check(label, got, want, tol):
        ok = abs(got - want) <= tol
        print(f"  {'OK  ' if ok else 'FAIL'} {label:34} got {got:+.4f}  want {want:+.4f}  (tol {tol})")
        if not ok:
            failures.append(f"{label}: got {got:+.6f}, want {want:+.4f} (tol {tol})")

    print("PANEL SHAPE vs June")
    for key, want in (("n_names", panel.n_names), ("n_snaps", len(panel.snaps)),
                      ("delisted_no_price", len(panel.delisted_no_price))):
        ref = JUNE_REFERENCE["panel"][key]
        ok = want == ref
        print(f"  {'OK  ' if ok else 'FAIL'} {key:34} got {want}  want {ref}")
        if not ok:
            failures.append(f"panel.{key}: got {want}, want {ref}")
    print()

    results = {"panel": {"n_names": panel.n_names, "n_snaps": len(panel.snaps),
                         "median_coverage": median_cov,
                         "delisted_no_price": len(panel.delisted_no_price),
                         "midpoint": str(panel.midpoint()),
                         "oos_split": str(panel.oos_split())},
               "components": {}}

    print("FULL COMPONENT TABLE (June's §7.1 / §7.2 shape)")
    for horizon in HORIZONS:
        print(f"\n  @{horizon}mo")
        print(f"  {'component':22} {'mean IC':>9} {'t':>8} {'N':>5} {'H1':>9} {'H2':>9}  consistent")
        for comp in COMPONENTS + ["lt_score"]:
            ev = panel.evaluate(comp, horizon)
            results["components"].setdefault(comp, {})[horizon] = ev
            print(f"  {comp:22} {ev['mean_ic']:+9.4f} {ev['t']:+8.2f} {ev['n_snaps']:5d} "
                  f"{ev['ic_h1']:+9.4f} {ev['ic_h2']:+9.4f}  {ev['sign_consistent']}")

    print("\n\nREGRESSION GATE — Valuation vs June")
    for horizon in HORIZONS:
        ref = JUNE_REFERENCE["valuation"][horizon]
        ev = results["components"]["valuation"][horizon]
        print(f"\n  @{horizon}mo")
        check(f"valuation@{horizon} mean_ic", ev["mean_ic"], ref["mean_ic"], IC_TOL)
        check(f"valuation@{horizon} t", ev["t"], ref["t"], T_TOL)
        check(f"valuation@{horizon} ic_h1", ev["ic_h1"], ref["ic_h1"], IC_TOL)
        check(f"valuation@{horizon} ic_h2", ev["ic_h2"], ref["ic_h2"], IC_TOL)

    print("\n\nREGRESSION GATE — Valuation quintile spread vs June")
    ins, oos = panel.in_sample(), panel.out_of_sample()
    results["valuation_quintile"] = {}
    for horizon in HORIZONS:
        ref = JUNE_REFERENCE["valuation_quintile"][horizon]
        qi = component_quintile(panel, "valuation", ins, horizon)
        qo = component_quintile(panel, "valuation", oos, horizon)
        results["valuation_quintile"][horizon] = {
            "in_pct": qi[0] * 100 if qi else None,
            "oos_pct": qo[0] * 100 if qo else None,
        }
        print(f"\n  @{horizon}mo")
        check(f"valuation@{horizon} Q5-Q1 IN  %", qi[0] * 100, ref["in"], SPREAD_TOL_PP)
        check(f"valuation@{horizon} Q5-Q1 OOS %", qo[0] * 100, ref["oos"], SPREAD_TOL_PP)

    os.makedirs(a.out, exist_ok=True)
    if a.json:
        out_path = Path(a.out) / "reproduce_june.json"
        out_path.write_text(json.dumps(results, indent=2, default=str) + "\n")
        print(f"\nwrote {out_path}")

    print("\n" + "=" * 72)
    if failures:
        print(f"REPRODUCTION FAILED — {len(failures)} check(s) outside tolerance:")
        for f in failures:
            print(f"  - {f}")
        print("\nPer the brief: STOP. Either the corpus changed or the port is wrong,")
        print("and nothing downstream is trustworthy until this is resolved.")
        return 1
    print("REPRODUCTION PASSED — the port reproduces June within tolerance.")
    print("Milestone A regression gate is GREEN; downstream milestones may proceed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
