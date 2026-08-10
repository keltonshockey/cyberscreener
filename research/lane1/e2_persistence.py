#!/usr/bin/env python3
"""
E2 sign-persistence conditioner - the PIT-PRIMARY run (the registered decider).

Registered in PREREG_E2_DECAY_TELEMETRY.md (commit a5b2c8d, before any code).
H1 per component: the sign of the trailing 12-month mean IC predicts the sign
of next-month IC. H0: no predictive sign-persistence.

THE KILL CONDITION IS DECIDED ONLY BY THIS PIT RUN. The accruing live-panel
section in the weekly harness is secondary, underpowered, and cannot clear or
resurrect the conditioner this cycle (prereg: Falsifier / kill condition). If
no component clears the bar here, the conditioner is DEAD: decay telemetry
ships as monitoring only and E3's design must exclude sign-persistence gating.

Statistic (shared implementation with the weekly harness -
research/harness/persistence.py): monthly IC series per component from the
lane1 engine's per-snapshot monthly ICs; for each month m with >= 12 trailing
months, s_m = sign(trailing 12mo mean IC), outcome IC_m; OLS of IC_m on s_m
with Newey-West lag 3. Bar for SUPPORTED: |t| >= 3 AND same effect sign in
both sample halves AND significance survives Bonferroni across ALL components
tested (N printed; expected 6). < 24 monthly ICs -> INSUFFICIENT. A
significant NEGATIVE effect is FAILED_H1, never a discovery.

Horizon note: the prereg fixes the hypothesis count at 6 (one per LT
component), so the primary run reads ONE forward-return horizon. That horizon
is 12 months - the horizon Lane 1 exists to serve, fixed by Milestone D's
falsifier ("specified at 12mo, NOT at any horizon"). --horizon 6 is accepted
for exploration but is labeled NON-PRIMARY and cannot decide the kill
condition.

Discipline: read-only against the corpus (build_panel opens files for reading
only; enforced by test_lane1_never_opens_the_corpus_for_write). Output is
append-only dated files in a directory OUTSIDE the corpus.

Usage:
    python -m research.lane1.e2_persistence [--corpus PATH] [--out DIR] [--horizon 12]
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.lane1.panel import CORPUS_ROOT, build_panel  # noqa: E402
from research.lane1.scoring import COMPONENTS  # noqa: E402
from research.harness.persistence import (  # noqa: E402
    ALPHA, MIN_MONTHS, NW_LAG, T_BAR, TRAILING_MONTHS, free_path,
    persistence_test)

PRIMARY_HORIZON = 12
DEFAULT_OUT = "~/mill-local-edits/e2-persistence"

BAR_TEXT = (f"|t| >= {T_BAR:g} (Newey-West lag {NW_LAG}) AND same effect sign in "
            f"both sample halves AND Bonferroni across all components tested "
            f"(alpha = two-sided p at |t|={T_BAR:g}, i.e. {ALPHA:.5f})")

CSV_FIELDS = ["component", "horizon_months", "n_months", "n_pairs", "beta",
              "se_nw", "t_nw", "p_two", "p_bonf", "effect_h1", "effect_h2",
              "same_sign", "bonferroni_n", "verdict", "note"]


def ic_series_by_component(panel, horizon: int) -> dict:
    """
    {component: (months, ics)} from the lane1 engine's monthly IC machinery -
    the per-snapshot cross-sectional Spearman ICs, exactly what Milestones A-D
    evaluate on. Months without a usable cross-section are absent by
    construction (Panel.ic_series applies MIN_CROSS_SECTION).
    """
    out = {}
    for comp in COMPONENTS:
        ser = [(s, ic) for (s, ic, _n) in panel.ic_series(comp, horizon)
               if ic is not None]
        out[comp] = ([s for s, _ in ser], [ic for _, ic in ser])
    return out


def analyse(series_by_component: dict) -> list:
    """Run the registered family test. Bonferroni N = full family size."""
    n = len(series_by_component)
    return [persistence_test(months, ics, component=comp, bonferroni_n=n)
            for comp, (months, ics) in series_by_component.items()]


def kill_condition_met(results) -> bool:
    return not any(r.verdict == "SUPPORTED" for r in results)


def render_md(results, meta: dict) -> str:
    """Dated report. The header states the decider role - required by the prereg."""
    n_hyp = meta["n_hypotheses"]
    primary = meta["horizon"] == PRIMARY_HORIZON
    lines = [
        f"# E2 sign-persistence - PIT primary - {meta['run_date']}",
        "",
        "**THE KILL CONDITION IS DECIDED ONLY BY THIS PIT RUN** per",
        "PREREG_E2_DECAY_TELEMETRY.md (commit a5b2c8d). The accruing live-panel",
        "section of the weekly IC report is secondary and cannot clear or",
        "resurrect the conditioner this cycle.",
        "",
    ]
    if not primary:
        lines += [
            f"**NON-PRIMARY RUN (horizon {meta['horizon']}mo, exploratory).**",
            "The registered primary reads the 12mo horizon; this run cannot",
            "decide the kill condition.",
            "",
        ]
    lines += [
        "| field | value |",
        "|---|---|",
        f"| generated | {meta['generated']} |",
        f"| corpus | `{meta['corpus']}` |",
        f"| panel | {meta['n_names']} names, {meta['n_snaps']} monthly snapshots |",
        f"| horizon | {meta['horizon']}mo forward return |",
        f"| **hypotheses tested** | **{n_hyp}** (one per LT component) |",
        f"| bar | {meta['bar']} |",
        f"| trailing window | {TRAILING_MONTHS} monthly ICs; < {MIN_MONTHS} monthly ICs -> INSUFFICIENT |",
        "",
        "Direction is fixed by the prereg: the claim is POSITIVE persistence.",
        "A significant negative effect is reported FAILED_H1, never relabeled.",
        "",
        "## Results",
        "",
        "| component | n_months | n_pairs | beta | t_nw | p_bonf | H1 effect | H2 effect | same sign | verdict | note |",
        "|---|---|---|---|---|---|---|---|---|---|---|",
    ]

    def f(v, spec="{:+.4f}"):
        return "-" if v != v else spec.format(v)

    for r in results:
        lines.append(
            f"| `{r.component}` | {r.n_months} | {r.n_pairs} | {f(r.beta)} | "
            f"{f(r.t_nw, '{:+.2f}')} | {f(r.p_bonf, '{:.5f}')} | "
            f"{f(r.effect_h1)} | {f(r.effect_h2)} | "
            f"{'yes' if r.same_sign else 'no'} | {r.verdict} | {r.note or ''} |")

    supported = [r.component for r in results if r.verdict == "SUPPORTED"]
    failed = [r.component for r in results if r.verdict == "FAILED_H1"]
    lines += ["", "## Verdict", ""]
    if supported:
        lines.append("SUPPORTED: " + ", ".join(f"`{c}`" for c in supported))
    if failed:
        lines.append("FAILED_H1 (significant CONTRARIAN effect - reported as a "
                     "failed H1, not a discovery): " + ", ".join(f"`{c}`" for c in failed))
    if not primary:
        lines.append("Exploratory run - no kill-condition reading.")
    elif kill_condition_met(results):
        lines += [
            "**KILL CONDITION MET - no component clears the bar on the PIT",
            "primary. The E2 conditioner is DEAD: decay telemetry ships as",
            "monitoring only, no conditioning logic may be built on it, and",
            "E3's design must exclude sign-persistence gating.**",
        ]
    else:
        lines.append("Kill condition NOT met - see SUPPORTED components above. "
                     "This nominates; it does not promote or condition anything.")
    lines.append("")
    return "\n".join(lines)


def render_csv(results, meta: dict) -> str:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=CSV_FIELDS)
    w.writeheader()
    for r in results:
        w.writerow({
            "component": r.component, "horizon_months": meta["horizon"],
            "n_months": r.n_months, "n_pairs": r.n_pairs, "beta": r.beta,
            "se_nw": r.se_nw, "t_nw": r.t_nw, "p_two": r.p_two,
            "p_bonf": r.p_bonf, "effect_h1": r.effect_h1,
            "effect_h2": r.effect_h2, "same_sign": r.same_sign,
            "bonferroni_n": r.bonferroni_n, "verdict": r.verdict,
            "note": r.note,
        })
    return buf.getvalue()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--corpus", default=CORPUS_ROOT)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--horizon", type=int, default=PRIMARY_HORIZON, choices=(6, 12),
                    help="forward-return horizon in months; 12 is the registered "
                         "primary, 6 is exploratory/NON-PRIMARY")
    a = ap.parse_args(argv)

    print("=" * 74)
    print("E2 SIGN-PERSISTENCE - PIT PRIMARY")
    print("THE KILL CONDITION IS DECIDED ONLY BY THIS RUN")
    print("(PREREG_E2_DECAY_TELEMETRY.md, commit a5b2c8d - bar frozen before code)")
    print("=" * 74)
    if a.horizon != PRIMARY_HORIZON:
        print(f"NON-PRIMARY RUN: horizon {a.horizon}mo is exploratory and cannot")
        print("decide the kill condition (registered primary: 12mo).")

    print(f"\ncorpus: {a.corpus}")
    print("building PIT panel (as-filed, filed<=D, annual resolution) ...", flush=True)
    panel = build_panel(a.corpus)
    print(f"panel: {panel.n_names} names, {len(panel.snaps)} snapshots "
          f"{panel.snaps[0]}..{panel.snaps[-1]}")

    series = ic_series_by_component(panel, a.horizon)
    results = analyse(series)

    n_hyp = len(series)
    print(f"\nhypotheses tested: {n_hyp} (one per LT component; expected 6)")
    print(f"bar: {BAR_TEXT}")
    print()
    for r in results:
        t_txt = "     -" if r.t_nw != r.t_nw else f"{r.t_nw:+6.2f}"
        print(f"  {r.component:20} n_months={r.n_months:3d} pairs={r.n_pairs:3d} "
              f"t_nw={t_txt}  {r.verdict:12} {r.note}")

    meta = {
        "run_date": dt.date.today().isoformat(),
        "generated": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "corpus": a.corpus, "horizon": a.horizon,
        "n_names": panel.n_names, "n_snaps": len(panel.snaps),
        "n_hypotheses": n_hyp, "bar": BAR_TEXT,
    }

    out_dir = Path(a.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"e2-persistence-{meta['run_date']}"
    if a.horizon != PRIMARY_HORIZON:
        stem += f"-h{a.horizon}"
    md_path = free_path(out_dir, stem, ".md")
    csv_path = free_path(out_dir, stem, ".csv")
    md_path.write_text(render_md(results, meta))
    csv_path.write_text(render_csv(results, meta))

    print(f"\nwrote: {md_path}")
    print(f"wrote: {csv_path}")
    if a.horizon == PRIMARY_HORIZON:
        if kill_condition_met(results):
            print("\nKILL CONDITION MET - conditioner is DEAD; telemetry ships as "
                  "monitoring only (see report).")
        else:
            print("\nKill condition NOT met - SUPPORTED components listed in the report.")
    print("\nRead the ARTIFACT for the verdicts; the exit code only signals that "
          "the run completed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
