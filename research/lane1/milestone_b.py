#!/usr/bin/env python3
"""
Milestone B — quarterly-TTM re-test of the growth components.

The June run scored rule_of_40, fcf_margin and earnings_quality from ANNUAL
figures, so they updated roughly once a year. That coarseness is a plausible
reason they looked flat, and June explicitly gated a quarterly-TTM re-test
before permanently down-weighting them. This is that re-test.

Evaluation frame is identical to Milestone A — same universe, same snapshots,
same forward returns, same window-based half split — so any change in IC is
attributable to RESOLUTION and nothing else.

Bar (PROMOTION_CRITERIA.md + the brief):
    |t| >= 3 after Bonferroni across what is tested, AND the same sign in both
    PIT sub-periods, AND a positive OOS quintile spread.

KILL CONDITION: if no growth component earns SUPPORTED, they are dropped
permanently from Lane 1 scope. That is a clean negative result, not a failure.

Usage:
    python -m research.lane1.milestone_b [--corpus PATH] [--out DIR]
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
from research.lane1.pit import REV, annual_facts  # noqa: E402
from research.lane1.quarterly import duration_facts, ttm_validation_report  # noqa: E402
from research.lane1.stats import pooled_quintiles  # noqa: E402

# The components under test. Valuation is carried along as a CONTROL: it already
# passed at annual resolution, so if the quarterly pipeline were broken we would
# expect to see it degrade, which is the signal that the plumbing is at fault
# rather than the hypothesis.
GROWTH_COMPONENTS = ["rule_of_40", "fcf_margin", "earnings_quality"]
CONTROL = "valuation"

T_BAR = 3.0
# Stitcher acceptance: derived TTM must match the independently filed annual
# figure at fiscal year ends. 1% tolerance, and most names must clear it.
TTM_REL_TOL = 0.01
TTM_MIN_PASS_RATE = 0.90


def validate_stitcher(corpus_root: str, limit: int = 120) -> dict:
    """
    Cross-check stitched TTM against filed annual figures before ANY inference.

    If this fails, every quarterly number downstream is suspect and the
    milestone's negative result would be an artifact of the plumbing rather
    than evidence about the signal.
    """
    import datetime as dt
    edgar = os.path.join(corpus_root, "edgar")
    with open(os.path.join(corpus_root, "universe", "manifest.json")) as f:
        tickers = json.load(f)["tickers"]

    D = dt.date(2025, 6, 1)
    checks, per_name = [], []
    for t in tickers[:limit]:
        fp = os.path.join(edgar, f"{t}.facts.json")
        if not os.path.exists(fp):
            continue
        try:
            with open(fp) as f:
                g = json.load(f).get("facts", {}).get("us-gaap", {})
        except Exception:
            continue
        rows = ttm_validation_report(duration_facts(g, REV), D, annual_facts(g, REV))
        if rows:
            per_name.append((t, sum(1 for r in rows if r["rel_err"] <= TTM_REL_TOL) / len(rows)))
            checks.extend(rows)

    if not checks:
        return {"n": 0, "pass_rate": 0.0, "median_rel_err": None, "names": 0}
    errs = sorted(r["rel_err"] for r in checks)
    return {
        "n": len(checks),
        "names": len(per_name),
        "pass_rate": sum(1 for e in errs if e <= TTM_REL_TOL) / len(errs),
        "median_rel_err": statistics.median(errs),
        "p95_rel_err": errs[int(len(errs) * 0.95)],
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--corpus", default=CORPUS_ROOT)
    ap.add_argument("--out", default=os.path.expanduser("~/mill-local-edits/lane1"))
    a = ap.parse_args(argv)

    print("=" * 74)
    print("MILESTONE B — quarterly-TTM re-test of the growth components")
    print("=" * 74)

    # ── Gate: is the stitcher trustworthy? ───────────────────────────────────
    print("\n[1] Validating quarter-stitching against filed annual figures ...", flush=True)
    v = validate_stitcher(a.corpus)
    print(f"    {v['n']} fiscal-year cross-checks across {v['names']} names")
    if v["n"]:
        print(f"    median |TTM-annual|/annual : {v['median_rel_err']:.5f}")
        print(f"    p95                        : {v['p95_rel_err']:.5f}")
        print(f"    within {TTM_REL_TOL:.0%}                 : {v['pass_rate']:.1%} "
              f"(need >= {TTM_MIN_PASS_RATE:.0%})")
    if v["n"] == 0 or v["pass_rate"] < TTM_MIN_PASS_RATE:
        print("\n    STITCHER FAILED VALIDATION — stopping.")
        print("    A negative result from an unvalidated stitcher would be an artifact,")
        print("    not evidence. Fix the stitching before re-running Milestone B.")
        return 2
    print("    stitcher OK — proceeding")

    # ── Build both panels ────────────────────────────────────────────────────
    print("\n[2] Building panels (annual = June baseline, quarterly = TTM) ...", flush=True)
    p_ann = build_panel(a.corpus, resolution="annual")
    p_qtr = build_panel(a.corpus, resolution="quarterly")
    print(f"    annual   : {p_ann.n_names} names, median "
          f"{sorted(len(p_ann.entries[s]) for s in p_ann.snaps)[len(p_ann.snaps)//2]} names/snap")
    print(f"    quarterly: {p_qtr.n_names} names, median "
          f"{sorted(len(p_qtr.entries[s]) for s in p_qtr.snaps)[len(p_qtr.snaps)//2]} names/snap")

    tested = GROWTH_COMPONENTS
    n_hyp = len(tested) * len(HORIZONS)
    print(f"\n[3] Hypotheses tested: {n_hyp} ({len(tested)} components x {len(HORIZONS)} horizons)")
    print(f"    Bonferroni-adjusted bar: |t| >= {T_BAR} AND same sign both halves "
          f"AND positive OOS quintile spread")

    ins, oos = p_qtr.in_sample(), p_qtr.out_of_sample()
    results, supported = {}, []

    print("\n[4] Results — quarterly-TTM vs June annual\n")
    header = (f"    {'component':20} {'horizon':>7} {'ann IC':>9} {'qtr IC':>9} "
              f"{'qtr t':>8} {'H1':>9} {'H2':>9} {'OOS Q5-Q1':>10}  verdict")
    print(header)
    print("    " + "-" * (len(header) - 4))

    for comp in tested + [CONTROL]:
        for h in HORIZONS:
            ev_a = p_ann.evaluate(comp, h)
            ev_q = p_qtr.evaluate(comp, h)
            q_oos = pooled_quintiles([p_qtr.rows(comp, s, h) for s in oos])
            spread = q_oos[0] * 100 if q_oos else float("nan")

            passes = (abs(ev_q["t"]) >= T_BAR and ev_q["same_sign"] and spread > 0)
            if comp in tested:
                verdict = "SUPPORTED" if passes else "not supported"
                if passes:
                    supported.append(f"{comp}@{h}mo")
            else:
                verdict = f"(control: {'holds' if passes else 'DEGRADED'})"

            results.setdefault(comp, {})[h] = {
                "annual_ic": ev_a["mean_ic"], "quarterly_ic": ev_q["mean_ic"],
                "quarterly_t": ev_q["t"], "ic_h1": ev_q["ic_h1"], "ic_h2": ev_q["ic_h2"],
                "same_sign": ev_q["same_sign"], "oos_quintile_pct": spread,
                "n_snaps": ev_q["n_snaps"], "supported": bool(passes),
            }
            print(f"    {comp:20} {h:>6}mo {ev_a['mean_ic']:+9.4f} {ev_q['mean_ic']:+9.4f} "
                  f"{ev_q['t']:+8.2f} {ev_q['ic_h1']:+9.4f} {ev_q['ic_h2']:+9.4f} "
                  f"{spread:+9.2f}%  {verdict}")

    # ── Kill condition ───────────────────────────────────────────────────────
    print("\n" + "=" * 74)
    payload = {"stitcher_validation": v, "hypotheses": n_hyp, "bar": T_BAR,
               "results": results, "supported": supported}
    os.makedirs(a.out, exist_ok=True)
    Path(a.out, "milestone_b.json").write_text(json.dumps(payload, indent=2, default=str) + "\n")

    if supported:
        print(f"SUPPORTED at quarterly-TTM: {', '.join(supported)}")
        print("These carry into Milestone D's composite alongside Valuation.")
        return 0

    print("KILL CONDITION MET — no growth component earns SUPPORTED at quarterly-TTM.")
    print("Per the brief, rule_of_40 / fcf_margin / earnings_quality are dropped")
    print("permanently from Lane 1 scope. This is a clean negative result: the June")
    print("flatness was NOT a resolution artifact, and the gated follow-up is closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
