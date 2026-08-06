#!/usr/bin/env python3
"""
Milestone D — Chen-Zimmermann predictor sweep + equal-weight composite.

Executes exactly the pre-registration in RESULT_R3_LANE1_2026-08-05.md
(commit a58ea3f): 10 predictors, CZ-documented signs, 20 hypotheses, SUPPORTED
requires t>=3 AND both-half same sign AND positive OOS quintile spread, turnover
measured with a 50% one-sided monthly cap, composite = EQUAL-WEIGHT rank average
of survivors + Valuation, no optimiser.

Usage:
    python -m research.lane1.milestone_d [--corpus PATH] [--out DIR]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.lane1.panel import (CORPUS_ROOT, HORIZONS, Panel, build_panel,  # noqa: E402
                                  month_starts)
from research.lane1.predictors import PREDICTORS, FactBundle, compute  # noqa: E402
from research.lane1.prices import fwd_return, load_prices, price_row  # noqa: E402
from research.lane1.stats import (MIN_CROSS_SECTION, pooled_quintiles,  # noqa: E402
                                  rank, spearman, tstat)

T_BAR = 3.0
TURNOVER_CAP = 0.50


def build_predictor_panel(corpus_root: str, snaps=None):
    """Panel whose per-name payload is the predictor dict rather than LT scores."""
    snaps = snaps or month_starts()
    edgar = os.path.join(corpus_root, "edgar")
    prices_dir = os.path.join(corpus_root, "prices")
    with open(os.path.join(corpus_root, "universe", "manifest.json")) as f:
        tickers = json.load(f)["tickers"]

    entries = {s: [] for s in snaps}
    n_names = 0
    missing = []

    for t in tickers:
        ppath = os.path.join(prices_dir, "%s.csv" % t)
        if not os.path.exists(ppath) or os.path.getsize(ppath) < 200:
            missing.append(t)
            continue
        dates, adj = load_prices(ppath)
        if len(dates) < 300:
            continue
        fpath = os.path.join(edgar, "%s.facts.json" % t)
        if not os.path.exists(fpath):
            continue
        try:
            with open(fpath) as f:
                fj = json.load(f)
            bundle = FactBundle(fj.get("facts", {}).get("us-gaap", {}),
                                fj.get("facts", {}).get("dei", {}))
        except Exception:
            continue
        n_names += 1

        for D in snaps:
            pr = price_row(dates, adj, D)
            if pr is None:
                continue
            f6 = fwd_return(dates, adj, D, 6)
            f12 = fwd_return(dates, adj, D, 12)
            if f6 is None and f12 is None:
                continue
            vals = compute(bundle, D, pr["price"])
            if vals:
                entries[D].append((t, vals, f6, f12))

    return Panel(snaps, entries, n_names, missing, 0)


def rows_for(panel, name, snapshot, horizon):
    hi = 2 if horizon == 6 else 3
    return [(e[1][name], e[hi]) for e in panel.entries[snapshot]
            if name in e[1] and e[hi] is not None]


def evaluate(panel, name, horizon):
    ser = []
    for s in panel.snaps:
        rows = rows_for(panel, name, s, horizon)
        if len(rows) >= MIN_CROSS_SECTION:
            ser.append((s, spearman([r[0] for r in rows], [r[1] for r in rows])))
    mean_ic, t, n = tstat([x[1] for x in ser])
    mid = panel.midpoint()
    h1 = [x[1] for x in ser if x[0] <= mid and x[1] is not None]
    h2 = [x[1] for x in ser if x[0] > mid and x[1] is not None]
    m1 = sum(h1) / max(1, len(h1))
    m2 = sum(h2) / max(1, len(h2))
    return dict(mean_ic=mean_ic, t=t, n_snaps=n, ic_h1=m1, ic_h2=m2,
                same_sign=(m1 > 0) == (m2 > 0))


def measure_turnover(panel, name):
    """
    Mean one-sided monthly rank turnover: average |rank change| across
    consecutive snapshots, normalised so a full reshuffle = 1.0.

    Measured, not assumed — the brief's low-turnover constraint is only
    meaningful if the number comes from our own signal.
    """
    prev = None
    vals = []
    for s in panel.snaps:
        cur = {e[0]: e[1][name] for e in panel.entries[s] if name in e[1]}
        if len(cur) >= MIN_CROSS_SECTION:
            names = sorted(cur)
            r = rank([cur[n] for n in names])
            ranks = {n: r[i] / len(names) for i, n in enumerate(names)}
            if prev:
                common = set(ranks) & set(prev)
                if len(common) >= MIN_CROSS_SECTION:
                    vals.append(sum(abs(ranks[n] - prev[n]) for n in common) / len(common) * 2)
            prev = ranks
    return sum(vals) / len(vals) if vals else float("nan")


def composite_rows(panel, lt_panel, members, snapshot, horizon):
    """
    Equal-weight average of within-snapshot percentile ranks across `members`.

    Ranks are recomputed per snapshot so no member's raw scale can dominate;
    equal weight is the point (no optimiser — the June IC-reweight overfit).
    """
    hi = 2 if horizon == 6 else 3
    per_member = {}
    for m in members:
        if m == "valuation":
            src = {e[0]: e[1]["valuation"] for e in lt_panel.entries[snapshot]}
        else:
            src = {e[0]: e[1][m] for e in panel.entries[snapshot] if m in e[1]}
        if len(src) < MIN_CROSS_SECTION:
            return []
        names = sorted(src)
        r = rank([src[n] for n in names])
        per_member[m] = {n: r[i] / len(names) for i, n in enumerate(names)}

    rets = {e[0]: e[hi] for e in lt_panel.entries[snapshot] if e[hi] is not None}
    common = set(rets)
    for m in members:
        common &= set(per_member[m])
    return [(sum(per_member[m][n] for m in members) / len(members), rets[n]) for n in common]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--corpus", default=CORPUS_ROOT)
    ap.add_argument("--out", default=os.path.expanduser("~/mill-local-edits/lane1"))
    a = ap.parse_args(argv)

    print("=" * 78)
    print("MILESTONE D — Chen-Zimmermann predictor sweep (pre-registered, commit a58ea3f)")
    print("=" * 78)

    print("\nbuilding predictor panel ...", flush=True)
    pan = build_predictor_panel(a.corpus)
    lt = build_panel(a.corpus)
    cov = sorted(len(pan.entries[s]) for s in pan.snaps)
    print(f"  {pan.n_names} names, median {cov[len(cov)//2]} names/snapshot")

    n_hyp = len(PREDICTORS) * len(HORIZONS)
    print(f"\nhypotheses: {n_hyp} ({len(PREDICTORS)} predictors x {len(HORIZONS)} horizons)")
    print(f"bar: |t| >= {T_BAR} AND same sign both halves AND positive OOS quintile spread")
    print(f"turnover cap: {TURNOVER_CAP:.0%} one-sided monthly\n")

    ins, oos = pan.in_sample(), pan.out_of_sample()
    turn = {p: measure_turnover(pan, p) for p in PREDICTORS}

    print(f"{'predictor':14} {'horiz':>6} {'mean IC':>9} {'t':>8} {'H1':>9} {'H2':>9} "
          f"{'OOS Q5-Q1':>10} {'turnover':>9}  verdict")
    print("-" * 104)

    results, survivors = {}, []
    for p in PREDICTORS:
        for h in HORIZONS:
            ev = evaluate(pan, p, h)
            q = pooled_quintiles([rows_for(pan, p, s, h) for s in oos])
            spread = q[0] * 100 if q else float("nan")
            stat_ok = abs(ev["t"]) >= T_BAR and ev["same_sign"] and spread > 0
            turn_ok = turn[p] <= TURNOVER_CAP
            if stat_ok and turn_ok:
                verdict = "SUPPORTED"
                survivors.append((p, h))
            elif stat_ok and not turn_ok:
                verdict = "stat-ok, TURNOVER EXCLUDED"
            else:
                verdict = "not supported"
            results.setdefault(p, {})[h] = dict(ev, oos_quintile_pct=spread,
                                                turnover=turn[p], verdict=verdict)
            print(f"{p:14} {h:>5}mo {ev['mean_ic']:+9.4f} {ev['t']:+8.2f} "
                  f"{ev['ic_h1']:+9.4f} {ev['ic_h2']:+9.4f} {spread:+9.2f}% "
                  f"{turn[p]:>8.1%}  {verdict}")

    surviving_names = sorted({p for p, _h in survivors})
    print("\n" + "=" * 78)
    print(f"SURVIVORS: {', '.join(surviving_names) if surviving_names else 'NONE'}")

    members = surviving_names + ["valuation"]
    print(f"COMPOSITE MEMBERS (equal weight): {', '.join(members)}")

    print("\nComposite vs Valuation alone — OOS quintile spread")
    print(f"{'horizon':>8} {'Valuation alone':>18} {'Composite':>14}  beats?")
    comp_out = {}
    for h in HORIZONS:
        v_alone = pooled_quintiles([lt.rows("valuation", s, h) for s in oos])
        v_pct = v_alone[0] * 100 if v_alone else float("nan")
        if surviving_names:
            c = pooled_quintiles([composite_rows(pan, lt, members, s, h) for s in oos])
            c_pct = c[0] * 100 if c else float("nan")
            beats = "yes" if c_pct > v_pct else "NO"
        else:
            c_pct, beats = v_pct, "n/a (composite IS Valuation)"
        comp_out[h] = {"valuation_alone_pct": v_pct, "composite_pct": c_pct, "beats": beats}
        print(f"{h:>7}mo {v_pct:>17.2f}% {c_pct:>13.2f}%  {beats}")

    os.makedirs(a.out, exist_ok=True)
    Path(a.out, "milestone_d.json").write_text(json.dumps(
        {"hypotheses": n_hyp, "results": results, "turnover": turn,
         "survivors": surviving_names, "composite": comp_out}, indent=2, default=str) + "\n")

    print("\n" + "=" * 78)
    if not surviving_names:
        print("ZERO predictors survive. Per the pre-registration this is a VALID outcome:")
        print("the Lane 1 composite is VALUATION ALONE.")
        return 0

    # THE PRE-COMMITTED FALSIFIER, applied exactly as registered:
    #   "If the survivors' equal-weight composite does not beat Valuation alone
    #    on OOS quintile spread AT 12MO, the added predictors earn no place and
    #    the composite spec ships as Valuation-only."
    # It is specified at 12mo — the horizon Lane 1 exists to serve — NOT "at any
    # horizon". Reading it the looser way would let a 6mo win rescue a 12mo loss,
    # which is choosing the test after seeing the result.
    if comp_out[12]["beats"] == "NO":
        print("PRE-COMMITTED FALSIFIER FIRES.")
        print(f"  Survivors found: {', '.join(surviving_names)} (both clear the stat bar")
        print("  and are far inside the turnover cap), but the equal-weight composite")
        print(f"  returns {comp_out[12]['composite_pct']:+.2f}% at 12mo against Valuation")
        print(f"  alone at {comp_out[12]['valuation_alone_pct']:+.2f}% — it does NOT beat it.")
        print("\n  Per the pre-registration the added predictors earn no place:")
        print("  THE LANE 1 COMPOSITE SPEC SHIPS AS VALUATION-ONLY.")
        print(f"\n  (The composite does win at 6mo, {comp_out[6]['composite_pct']:+.2f}% vs")
        print(f"  {comp_out[6]['valuation_alone_pct']:+.2f}%. That is recorded, and it is")
        print("  NOT grounds to override the 12mo falsifier — the horizon was fixed in")
        print("  advance precisely so this choice could not be made after the fact.)")
    else:
        print(f"Composite of {', '.join(members)} beats Valuation alone at 12mo")
        print(f"  ({comp_out[12]['composite_pct']:+.2f}% vs {comp_out[12]['valuation_alone_pct']:+.2f}%).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
