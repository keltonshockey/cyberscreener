#!/usr/bin/env python3
"""
Standing IC report — the weekly, repeatable version of the 2026-08-04 interim
edge analysis.

Why this exists
---------------
`RESULT_EDGE_INTERIM_2026-08-04.md` found that `opt_asymmetry` had flipped sign
mid-window (H1 +0.100 -> H2 -0.172) and that live `conviction` anti-predicts
forward returns. That was discovered *after* the pre-registered gate had already
failed on real cohort-C plays. The whole point of this module is that the next
such flip shows up in a weekly report instead of at a gate failure.

This is evaluation infrastructure, not a scoring feature: it reads, it never
scores, and it is explicitly permitted under the fail rule.

Method (must stay identical to ANALYSIS_PREREG_2026-08-04.md T1)
---------------------------------------------------------------
1. Panel: the LAST scan per ticker per US weekday, prices taken from the
   `scores` rows themselves (never an outside source).
2. For each series -- the 12 `lt_*` / `opt_*` sub-components, plus `lt_score`,
   `opt_score`, and `conviction` = 0.6*opt + 0.4*lt -- compute the daily
   cross-sectional Spearman IC against forward underlying return at each
   horizon (default 5d and 21d).
3. t-stat on the mean daily IC, se scaled by sqrt(horizon) to account for
   overlapping forward windows (deliberately conservative).
4. Split the window at its midpoint and record the mean IC in each half.
5. Verdict, identical to the prereg bar:
     SUPPORTED    |t_adj| >= 3 AND the mean IC carries the same sign in both halves
     INSUFFICIENT too few usable days (or a degenerate/constant column)
     noise        everything else
   The hypothesis count (series x horizons) is stated in the output, because a
   bar applied 30 times is not the same bar applied once.

Outputs are APPEND-ONLY. A run never overwrites or deletes a previous report;
if a path is already taken it takes the next free `-02`, `-03`, ... suffix. The
weekly job's whole value is the historical series of these files.

Usage
-----
    python -m research.harness.ic_report --db /path/to/cyberscreener.db
    python -m research.harness.ic_report --db ... --window-days 180 --tearsheet
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pandas as pd

# ─────────────────────────────────────────────────────────────────────────────
# The read door. research/README.md rule 1: use api/db/ro.py, never a hand-rolled
# sqlite3.connect. We load THAT EXACT FILE -- but by path, not via `from db.ro
# import connect_ro`, and the distinction is load-bearing:
#
# `api/db/__init__.py` eagerly does `from .models import ...`, and db.models
# imports core -> core.scanner -> yfinance. So the package-path import drags the
# entire application dependency tree in behind a 3-function read helper that
# needs nothing but stdlib. Two concrete consequences:
#
#   1. The mill venv could not stay small. `~/.venvs/icharness` would need
#      yfinance, fastapi, anthropic and the rest just to open a database
#      read-only -- and mill's system python is 3.9, so a fat venv is exactly
#      where this goes wrong.
#   2. It would import `db.models` -- the WRITE-PATH module -- into research
#      code at runtime, which is precisely what research/README.md rule 3
#      exists to prevent. The static check would still pass while the runtime
#      reality violated it.
#
# Loading the file directly keeps one implementation of the read door (R1's,
# unmodified) with none of that. test_ic_harness.py pins both properties:
# the function really is R1's, and db.models is never imported.
# ─────────────────────────────────────────────────────────────────────────────
_API_DIR = Path(__file__).resolve().parents[2] / "api"
RO_PATH = _API_DIR / "db" / "ro.py"

def _load_read_door():
    import importlib.util
    spec = importlib.util.spec_from_file_location("cs_db_ro", RO_PATH)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"cannot load the read door from {RO_PATH}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod

connect_ro = _load_read_door().connect_ro

# ─────────────────────────────────────────────────────────────────────────────
# The series under test. Order is fixed so reports and the golden file are
# stable across runs.
# ─────────────────────────────────────────────────────────────────────────────
LT_COMPONENTS = [
    "lt_rule_of_40",
    "lt_valuation",
    "lt_fcf_margin",
    "lt_trend",
    "lt_earnings_quality",
    "lt_discount_momentum",
]
OPT_COMPONENTS = [
    "opt_earnings_catalyst",
    "opt_iv_context",
    "opt_directional",
    "opt_technical",
    "opt_liquidity",
    "opt_asymmetry",
]
COMPOSITES = ["lt_score", "opt_score", "conviction"]
SERIES = LT_COMPONENTS + OPT_COMPONENTS + COMPOSITES

DEFAULT_HORIZONS = (5, 21)
DEFAULT_DB = "/Users/mill/cs-nightly/cyberscreener.db"
DEFAULT_OUT_DIR = "~/mill-local-edits/ic-reports"

# A cross-section thinner than this is not a cross-section; the day is dropped.
MIN_NAMES_PER_DAY = 10
# Fewer usable IC days than this and the verdict is INSUFFICIENT rather than a
# number that looks like evidence.
MIN_DAYS = 20
# The prereg bar.
T_BAR = 3.0

# Scan timestamps are stored UTC; "US weekday" means the US market day, so the
# panel is bucketed in Eastern time before the weekday filter is applied.
MARKET_TZ = "America/New_York"


@dataclass
class SeriesResult:
    series: str
    horizon: int
    n_days: int
    n_obs: int
    mean_ic: float
    std_ic: float
    t_raw: float
    t_adj: float
    ic_h1: float
    ic_h2: float
    same_sign: bool
    verdict: str
    note: str = ""


# ─────────────────────────────────────────────────────────────────────────────
# Panel construction
# ─────────────────────────────────────────────────────────────────────────────
def load_panel(db_path: str, window_days: int, asof: str | None = None) -> pd.DataFrame:
    """
    Build the analysis panel: one row per ticker per US weekday, carrying every
    scored component and the price recorded on that row.

    Deduplication keeps the LAST scan of each market day, matching the prereg
    (and deliberately unlike `_deduplicate_scores` in the app, which keeps the
    FIRST -- this analysis is independent of it).
    """
    conn = connect_ro(db_path)
    try:
        cols = ", ".join(f"s.{c}" for c in LT_COMPONENTS + OPT_COMPONENTS + ["lt_score", "opt_score"])
        rows = pd.read_sql_query(
            f"SELECT s.ticker, s.price, {cols}, sc.timestamp "
            "FROM scores s JOIN scans sc ON sc.id = s.scan_id "
            "WHERE s.price IS NOT NULL AND s.price > 0",
            conn,
        )
    finally:
        conn.close()

    if rows.empty:
        return rows.assign(date=pd.Series(dtype="object"))

    ts = pd.to_datetime(rows["timestamp"], utc=True, errors="coerce")
    rows = rows.loc[ts.notna()].copy()
    ts = ts.loc[ts.notna()]
    local = ts.dt.tz_convert(MARKET_TZ)
    rows["date"] = local.dt.date
    rows["_ts"] = ts

    # US weekdays only (Mon-Fri). Market holidays simply have no scans worth
    # ranking; they fall out naturally with the cross-section size filter.
    rows = rows.loc[local.dt.dayofweek < 5].copy()

    # Trailing window, measured from the last market day actually present so a
    # stale DB narrows the window instead of silently returning nothing.
    end = pd.Timestamp(asof).date() if asof else rows["date"].max()
    start = end - timedelta(days=window_days)
    rows = rows.loc[(rows["date"] > start) & (rows["date"] <= end)].copy()
    if rows.empty:
        return rows

    # Last scan of the day wins.
    rows = rows.sort_values("_ts").drop_duplicates(subset=["ticker", "date"], keep="last")

    rows["conviction"] = 0.6 * rows["opt_score"] + 0.4 * rows["lt_score"]
    return rows.drop(columns=["timestamp", "_ts"]).reset_index(drop=True)


def forward_returns(panel: pd.DataFrame, horizons) -> dict:
    """
    Forward underlying return at each horizon, in PANEL DAYS.

    Built on a wide date x ticker price matrix and shifted along the date axis,
    so horizon h means the same h market days for every ticker. Doing this
    per-ticker instead would let a ticker with gaps quietly reach further
    forward in calendar time than its peers, which biases the cross-section.
    """
    wide = panel.pivot_table(index="date", columns="ticker", values="price", aggfunc="last")
    wide = wide.sort_index()
    out = {}
    for h in horizons:
        fwd = wide.shift(-h) / wide - 1.0
        out[h] = fwd.stack(future_stack=True).rename(f"fwd_{h}").reset_index()
    return out


# ─────────────────────────────────────────────────────────────────────────────
# IC computation
# ─────────────────────────────────────────────────────────────────────────────
def _spearman(a: pd.Series, b: pd.Series) -> float:
    """
    Spearman rank correlation via ranked Pearson.

    Implemented on pandas/numpy rather than scipy on purpose: nothing else in
    this repo's environment needs scipy, and the mill venv should stay small.
    Returns NaN when either side is constant -- which is exactly what a
    degenerate (constant) component should produce, and what drives the
    INSUFFICIENT verdict rather than a fabricated number.
    """
    ok = a.notna() & b.notna()
    if ok.sum() < MIN_NAMES_PER_DAY:
        return float("nan")
    ra = a[ok].rank()
    rb = b[ok].rank()
    if ra.nunique() < 2 or rb.nunique() < 2:
        return float("nan")
    return float(np.corrcoef(ra.to_numpy(), rb.to_numpy())[0, 1])


def daily_ic(panel: pd.DataFrame, fwd: pd.DataFrame, series: str, horizon: int) -> pd.Series:
    """Daily cross-sectional Spearman IC of `series` vs the forward return."""
    fwd_col = f"fwd_{horizon}"
    merged = panel[["date", "ticker", series]].merge(fwd, on=["date", "ticker"], how="inner")
    merged = merged.loc[merged[fwd_col].notna()]
    if merged.empty:
        return pd.Series(dtype=float)
    ics = merged.groupby("date").apply(
        lambda g: _spearman(g[series], g[fwd_col]), include_groups=False
    )
    return ics.dropna().sort_index()


def window_midpoint(panel: pd.DataFrame):
    """
    The calendar midpoint of the analysis WINDOW.

    The prereg says "window split at its midpoint", and it means the window --
    not the IC series, which is shorter because the last `horizon` days have no
    forward return yet. Splitting the IC list in half instead puts the boundary
    ~2 weeks early and materially changes the half-means: on the 2026-08-04
    interim window it moved lt_valuation's H1 from +0.006 to -0.010, i.e. from
    "positive in both halves" (the interim's one standout finding) to a sign
    disagreement. Verified against the published interim table -- this split
    reproduces it to ~0.003 on every series, the IC-count split does not.
    """
    start, end = panel["date"].min(), panel["date"].max()
    return start + (end - start) / 2


def evaluate(ics: pd.Series, series: str, horizon: int, n_obs: int, mid_date) -> SeriesResult:
    """Mean IC, overlap-corrected t, half-split sign check, prereg verdict."""
    n = int(len(ics))
    if n < MIN_DAYS:
        return SeriesResult(
            series=series, horizon=horizon, n_days=n, n_obs=n_obs,
            mean_ic=float("nan"), std_ic=float("nan"), t_raw=float("nan"),
            t_adj=float("nan"), ic_h1=float("nan"), ic_h2=float("nan"),
            same_sign=False, verdict="INSUFFICIENT",
            note=f"{n} usable IC days < {MIN_DAYS} required",
        )

    mean_ic = float(ics.mean())
    std_ic = float(ics.std(ddof=1))
    if not std_ic > 0:
        return SeriesResult(
            series=series, horizon=horizon, n_days=n, n_obs=n_obs,
            mean_ic=mean_ic, std_ic=std_ic, t_raw=float("nan"), t_adj=float("nan"),
            ic_h1=float("nan"), ic_h2=float("nan"), same_sign=False,
            verdict="INSUFFICIENT", note="zero dispersion in daily IC",
        )

    t_raw = mean_ic / (std_ic / math.sqrt(n))
    # Overlapping forward windows: se scaled by sqrt(h), per the prereg.
    t_adj = t_raw / math.sqrt(horizon)

    first_half = pd.Series(ics.index, index=ics.index).apply(lambda d: d <= mid_date)
    h1_vals, h2_vals = ics[first_half.values], ics[~first_half.values]
    if h1_vals.empty or h2_vals.empty:
        return SeriesResult(
            series=series, horizon=horizon, n_days=n, n_obs=n_obs,
            mean_ic=mean_ic, std_ic=std_ic, t_raw=t_raw, t_adj=t_adj,
            ic_h1=float("nan"), ic_h2=float("nan"), same_sign=False,
            verdict="INSUFFICIENT", note="all IC days fall in one half of the window",
        )
    ic_h1, ic_h2 = float(h1_vals.mean()), float(h2_vals.mean())
    same_sign = bool(np.sign(ic_h1) == np.sign(ic_h2) and ic_h1 != 0 and ic_h2 != 0)

    verdict = "SUPPORTED" if (abs(t_adj) >= T_BAR and same_sign) else "noise"
    return SeriesResult(
        series=series, horizon=horizon, n_days=n, n_obs=n_obs,
        mean_ic=mean_ic, std_ic=std_ic, t_raw=t_raw, t_adj=t_adj,
        ic_h1=ic_h1, ic_h2=ic_h2, same_sign=same_sign, verdict=verdict,
    )


def run_analysis(panel: pd.DataFrame, horizons) -> list[SeriesResult]:
    if panel.empty:
        return []
    fwds = forward_returns(panel, horizons)
    mid_date = window_midpoint(panel)
    results = []
    for h in horizons:
        fwd = fwds[h]
        for s in SERIES:
            if s not in panel.columns:
                results.append(SeriesResult(
                    series=s, horizon=h, n_days=0, n_obs=0, mean_ic=float("nan"),
                    std_ic=float("nan"), t_raw=float("nan"), t_adj=float("nan"),
                    ic_h1=float("nan"), ic_h2=float("nan"), same_sign=False,
                    verdict="INSUFFICIENT", note="column absent from this DB",
                ))
                continue
            ics = daily_ic(panel, fwd, s, h)
            n_obs = int(panel[s].notna().sum())
            results.append(evaluate(ics, s, h, n_obs, mid_date))
    return results


# ─────────────────────────────────────────────────────────────────────────────
# Output — append-only by construction
# ─────────────────────────────────────────────────────────────────────────────
def _free_path(out_dir: Path, stem: str, ext: str) -> Path:
    """
    Return a path that does not yet exist.

    Append-only is the contract: a second run on the same day must not clobber
    the first, because the value of this job is the historical series.
    """
    candidate = out_dir / f"{stem}{ext}"
    if not candidate.exists():
        return candidate
    for i in range(2, 1000):
        candidate = out_dir / f"{stem}-{i:02d}{ext}"
        if not candidate.exists():
            return candidate
    raise RuntimeError(f"cannot find a free filename for {stem}{ext}")


def results_to_frame(results: list[SeriesResult]) -> pd.DataFrame:
    return pd.DataFrame([asdict(r) for r in results])


def previous_csv(out_dir: Path, exclude: Path | None = None) -> Path | None:
    files = sorted(p for p in out_dir.glob("ic-report-*.csv") if p != exclude)
    return files[-1] if files else None


def delta_paragraph(current: pd.DataFrame, prev_path: Path | None) -> str:
    """
    One paragraph naming what CHANGED since the previous run — verdict moves and
    sign flips. This is the part that goes to Pushover; a weekly report nobody
    reads is the failure mode section 9 of the playbook is about.
    """
    if prev_path is None:
        return ("First run in this directory — no previous report to compare against. "
                "Subsequent runs will report verdict changes and IC sign flips here.")
    try:
        prev = pd.read_csv(prev_path)
    except Exception as exc:  # pragma: no cover - defensive
        return f"Could not read previous report {prev_path.name}: {exc}"

    key = ["series", "horizon"]
    merged = current.merge(prev, on=key, how="outer", suffixes=("", "_prev"))

    verdict_moves, sign_flips = [], []
    for _, r in merged.iterrows():
        now_v, was_v = r.get("verdict"), r.get("verdict_prev")
        if pd.notna(was_v) and pd.notna(now_v) and now_v != was_v:
            verdict_moves.append(f"{r['series']}@{int(r['horizon'])}d {was_v}->{now_v}")
        now_ic, was_ic = r.get("mean_ic"), r.get("mean_ic_prev")
        if pd.notna(now_ic) and pd.notna(was_ic) and np.sign(now_ic) != np.sign(was_ic):
            sign_flips.append(
                f"{r['series']}@{int(r['horizon'])}d {was_ic:+.3f}->{now_ic:+.3f}")

    if not verdict_moves and not sign_flips:
        return (f"No verdict changes and no IC sign flips vs {prev_path.name}. "
                f"{len(current)} hypotheses re-tested.")
    parts = [f"Changes vs {prev_path.name}:"]
    if verdict_moves:
        parts.append(" verdict moves — " + "; ".join(verdict_moves) + ".")
    if sign_flips:
        parts.append(" mean-IC sign flips — " + "; ".join(sign_flips) + ".")
    return "".join(parts)


def render_markdown(df: pd.DataFrame, meta: dict, delta: str) -> str:
    lines = [
        f"# IC report — {meta['run_date']}",
        "",
        f"Generated `{meta['generated_utc']}` by `research/harness/ic_report.py`.",
        "",
        "| field | value |",
        "|---|---|",
        f"| database | `{meta['db']}` |",
        f"| window | {meta['window_days']} calendar days, {meta['start']} to {meta['end']} |",
        f"| panel | {meta['n_days']} market days, {meta['n_tickers']} tickers, {meta['n_rows']} ticker-days |",
        f"| horizons | {', '.join(str(h) + 'd' for h in meta['horizons'])} |",
        f"| **hypotheses tested** | **{meta['n_hypotheses']}** ({len(SERIES)} series x {len(meta['horizons'])} horizons) |",
        f"| bar | \\|t_adj\\| >= {T_BAR} AND same-sign mean IC in both halves |",
        "",
        "Method: last scan per ticker per US weekday; prices from the `scores` rows",
        "themselves; daily cross-sectional Spearman IC vs forward underlying return;",
        "t-stat se scaled by sqrt(horizon) for overlapping windows. Identical to",
        "`ANALYSIS_PREREG_2026-08-04.md` T1.",
        "",
        "## Delta vs previous run",
        "",
        delta,
        "",
    ]

    supported = df[df["verdict"] == "SUPPORTED"]
    lines += [
        "## Verdict summary",
        "",
        f"- SUPPORTED: **{len(supported)}** of {len(df)}",
        f"- noise: {(df['verdict'] == 'noise').sum()}",
        f"- INSUFFICIENT: {(df['verdict'] == 'INSUFFICIENT').sum()}",
        "",
    ]
    if len(supported):
        lines.append("Series clearing the bar: " +
                     ", ".join(f"`{r.series}`@{r.horizon}d" for r in supported.itertuples()))
    else:
        lines.append("**Nothing clears the bar in this window.**")
    lines.append("")

    for h in meta["horizons"]:
        sub = df[df["horizon"] == h]
        lines += [
            f"## Horizon {h}d",
            "",
            "| series | mean IC | t_adj | H1 | H2 | same sign | n_days | verdict | note |",
            "|---|---|---|---|---|---|---|---|---|",
        ]
        for r in sub.itertuples():
            def f(v, spec="{:+.4f}"):
                return "—" if pd.isna(v) else spec.format(v)
            lines.append(
                f"| `{r.series}` | {f(r.mean_ic)} | {f(r.t_adj, '{:+.2f}')} | "
                f"{f(r.ic_h1)} | {f(r.ic_h2)} | {'yes' if r.same_sign else 'no'} | "
                f"{r.n_days} | {r.verdict} | {r.note or ''} |"
            )
        lines.append("")

    lines += [
        "## Reading this",
        "",
        f"With {meta['n_hypotheses']} hypotheses tested, a single |t_adj| just over "
        f"{T_BAR} is not evidence on its own — the both-halves sign requirement is what",
        "separates a durable signal from a lucky sub-window. A SUPPORTED verdict here",
        "nominates a component for the pre-registered promotion path; it does not",
        "promote anything. Nothing in this report changes a weight or a score.",
        "",
    ]
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Optional alphalens enrichment (never fatal)
# ─────────────────────────────────────────────────────────────────────────────
def write_tearsheet(panel: pd.DataFrame, out_dir: Path, stem: str, horizons) -> str:
    """
    alphalens-reloaded quantile/turnover analysis, if it imports cleanly.

    Enrichment only: the native path above is the contract, so any failure here
    is logged and skipped rather than failing the run.
    """
    try:
        import alphalens  # noqa: F401
        from alphalens.utils import get_clean_factor_and_forward_returns
        from alphalens.tears import create_full_tear_sheet  # noqa: F401
    except Exception as exc:
        return f"alphalens not available ({type(exc).__name__}: {exc}) — tearsheet skipped."

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt

        prices = panel.pivot_table(index="date", columns="ticker", values="price", aggfunc="last")
        prices.index = pd.to_datetime(prices.index)
        factor = panel.set_index([pd.to_datetime(panel["date"]), "ticker"])["conviction"].dropna()
        factor.index.names = ["date", "asset"]

        data = get_clean_factor_and_forward_returns(
            factor, prices, periods=tuple(horizons), quantiles=5,
        )

        plt.close("all")
        # alphalens renders each section then calls plt.show() and immediately
        # closes the figure (GridFigure.close()). Collecting figures AFTERWARDS
        # therefore always yields nothing -- the first cut of this function did
        # exactly that and wrote a blank 3KB image while reporting success.
        # Instead, intercept show() and keep a REFERENCE to each figure before
        # alphalens closes it; a closed Figure still renders via savefig.
        captured = []

        def _capture(*a, **k):
            for num in plt.get_fignums():
                fig = plt.figure(num)
                if not any(fig is c for c in captured):
                    captured.append(fig)

        _real_show = plt.show
        plt.show = _capture
        try:
            create_full_tear_sheet(data)
        finally:
            plt.show = _real_show

        # alphalens opens a SEPARATE figure per section. A plain savefig() here
        # captures only matplotlib's "current" figure — which is the empty one
        # left behind after the last section, producing a ~3KB blank PNG while
        # cheerfully reporting success. Collect every figure into one PDF, and
        # refuse to claim success if there were none.
        from matplotlib.backends.backend_pdf import PdfPages

        pages = [f for f in captured if f.axes]
        if not pages:
            plt.close("all")
            return "alphalens produced no figures — tearsheet skipped."

        path = _free_path(out_dir, f"{stem}-tearsheet", ".pdf")
        with PdfPages(path) as pdf:
            for fig in pages:
                pdf.savefig(fig, bbox_inches="tight")
        plt.close("all")
        return (f"alphalens tearsheet written to {path.name} "
                f"({len(pages)} pages, factor: conviction).")
    except Exception as exc:
        return f"alphalens present but tearsheet failed ({type(exc).__name__}: {exc}) — skipped."


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def generate(db: str, out_dir: Path, window_days: int, horizons, asof=None,
             tearsheet=False, label=None) -> dict:
    """Run the analysis and write the report pair. Returns a summary dict."""
    out_dir = Path(os.path.expanduser(str(out_dir)))
    out_dir.mkdir(parents=True, exist_ok=True)

    panel = load_panel(db, window_days, asof=asof)
    results = run_analysis(panel, horizons)
    df = results_to_frame(results)

    run_date = (asof or (panel["date"].max().isoformat() if not panel.empty
                         else datetime.now(timezone.utc).date().isoformat()))
    stem = f"ic-report-{run_date}" + (f"-{label}" if label else "")

    csv_path = _free_path(out_dir, stem, ".csv")
    md_path = _free_path(out_dir, stem, ".md")

    prev = previous_csv(out_dir)
    delta = delta_paragraph(df, prev) if not df.empty else "No results — empty panel."

    meta = {
        "run_date": str(run_date),
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%SZ"),
        "db": db,
        "window_days": window_days,
        "horizons": list(horizons),
        "start": str(panel["date"].min()) if not panel.empty else "—",
        "end": str(panel["date"].max()) if not panel.empty else "—",
        "n_days": int(panel["date"].nunique()) if not panel.empty else 0,
        "n_tickers": int(panel["ticker"].nunique()) if not panel.empty else 0,
        "n_rows": int(len(panel)),
        "n_hypotheses": len(df),
    }

    df.to_csv(csv_path, index=False)
    md_path.write_text(render_markdown(df, meta, delta))

    note = ""
    if tearsheet:
        note = write_tearsheet(panel, out_dir, stem, horizons)

    return {"csv": csv_path, "md": md_path, "meta": meta, "delta": delta,
            "results": df, "prev": prev, "tearsheet_note": note}


def send_pushover(message: str) -> bool:
    """
    Send the delta paragraph. Keys come from the environment (vault-backed via
    mill-secrets.env), never inline. No keys = skip, reported as such.

    The RETURN VALUE MATTERS: OPERATIONS_PLAYBOOK 9b caught three sibling
    scripts piping Pushover's reply to /dev/null, every one of which would log
    "alert sent" for an alert that went nowhere. The caller logs accepted /
    NOT ACCEPTED from this.
    """
    import urllib.parse
    import urllib.request

    token, user = os.environ.get("PUSHOVER_TOKEN"), os.environ.get("PUSHOVER_USER")
    if not token or not user:
        print("pushover: PUSHOVER_TOKEN/PUSHOVER_USER not set — skipped", file=sys.stderr)
        return False
    # Pushover truncates around 1024 chars; keep the head, which is where the
    # verdict moves and sign flips are.
    body = message[:900]
    data = urllib.parse.urlencode({"token": token, "user": user, "message": body}).encode()
    req = urllib.request.Request("https://api.pushover.net/1/messages.json", data=data)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status == 200
    except Exception as exc:
        print(f"pushover: send failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return False


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=DEFAULT_DB, help=f"cyberscreener.db (default: {DEFAULT_DB})")
    p.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help=f"default: {DEFAULT_OUT_DIR}")
    p.add_argument("--window-days", type=int, default=180, help="trailing calendar days (default 180)")
    p.add_argument("--horizons", default="5,21", help="forward horizons in market days (default 5,21)")
    p.add_argument("--asof", default=None, help="treat this date as the window end (YYYY-MM-DD)")
    p.add_argument("--tearsheet", action="store_true", help="also try the alphalens tearsheet")
    p.add_argument("--label", default=None, help="suffix for the output filenames")
    p.add_argument("--pushover", action="store_true", help="send the delta paragraph via Pushover")
    p.add_argument("--quiet", action="store_true")
    a = p.parse_args(argv)

    horizons = tuple(int(h) for h in a.horizons.split(",") if h.strip())

    out = generate(a.db, Path(a.out_dir), a.window_days, horizons,
                   asof=a.asof, tearsheet=a.tearsheet, label=a.label)

    if not a.quiet:
        m = out["meta"]
        print(f"panel: {m['n_days']} market days, {m['n_tickers']} tickers, "
              f"{m['n_rows']} ticker-days ({m['start']} to {m['end']})")
        print(f"hypotheses tested: {m['n_hypotheses']}")
        df = out["results"]
        if not df.empty:
            print(f"SUPPORTED: {(df['verdict'] == 'SUPPORTED').sum()} | "
                  f"noise: {(df['verdict'] == 'noise').sum()} | "
                  f"INSUFFICIENT: {(df['verdict'] == 'INSUFFICIENT').sum()}")
        print(f"wrote: {out['md']}")
        print(f"wrote: {out['csv']}")
        if out["tearsheet_note"]:
            print(out["tearsheet_note"])
        print()
        print("DELTA: " + out["delta"])

    if a.pushover:
        m = out["meta"]
        sup = int((out["results"]["verdict"] == "SUPPORTED").sum()) if not out["results"].empty else 0
        headline = f"IC {m['run_date']}: {sup} SUPPORTED of {m['n_hypotheses']}"
        ok = send_pushover(f"{headline}. {out['delta']}")
        print(f"pushover: {'accepted' if ok else 'NOT ACCEPTED'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
