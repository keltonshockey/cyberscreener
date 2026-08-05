"""
Panel construction — monthly PIT snapshots x names, with forward returns.

Ported from the June engine's `main()`, split out so the panel can be built once
and reused by Milestones A–D instead of each re-deriving it.

READ-ONLY CONTRACT: this module opens corpus files for reading only. There is no
`open(..., "w")`, no `rm`, no `mv` anywhere under `research/lane1/` that touches
`~/lt-recon-data`. Enforced by `api/tests/test_lane1_pit.py`.
"""

from __future__ import annotations

import datetime as dt
import json
import os

from .pit import (CAPEX, CASH, DEBT_CUR, DEBT_LT, EPS, GROSS, OCF, OPINC, REV,
                  SHARES, annual_facts, as_of_annual, as_of_instant,
                  instant_facts, prior_annual)
from .prices import fwd_return, load_prices, price_row
from .scoring import score_lt
from .stats import MIN_CROSS_SECTION, spearman, tstat

CORPUS_ROOT = os.path.expanduser("~/lt-recon-data")

# The June snapshot grid: first of each month, 2014-12 .. 2025-06 = 127 snapshots.
JUNE_FIRST_SNAPSHOT = (2014, 12)
JUNE_LAST_SNAPSHOT = (2025, 6)

HORIZONS = (6, 12)


def month_starts(first=JUNE_FIRST_SNAPSHOT, last=JUNE_LAST_SNAPSHOT) -> list[dt.date]:
    """Monthly snapshot dates, inclusive of both endpoints."""
    snaps = []
    y, m = first
    while (y, m) <= last:
        snaps.append(dt.date(y, m, 1))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return snaps


class Panel:
    """
    entries[snapshot] = list of (ticker, breakdown, fwd6, fwd12)

    `snaps` is the FULL snapshot grid, retained even where a snapshot has too
    thin a cross-section to score. That matters: the half-split and the OOS
    split are both defined on the full grid (see `midpoint` / `oos_split`), not
    on the list of snapshots that happened to produce an IC.
    """

    def __init__(self, snaps, entries, n_names, delisted_no_price, no_price):
        self.snaps = snaps
        self.entries = entries
        self.n_names = n_names
        self.delisted_no_price = delisted_no_price
        self.no_price = no_price

    # ── the two split points, both on the WINDOW ─────────────────────────────
    def midpoint(self) -> dt.date:
        """
        Sub-period boundary for the sign-consistency test.

        Defined on the full snapshot GRID, matching June (`snaps[len(snaps)//2]`)
        — and matching the lesson from RESULT_R2_IC_HARNESS correction 4, where
        splitting the observation list instead of the window moved the boundary
        by a full horizon and flipped a component's verdict.
        """
        return self.snaps[len(self.snaps) // 2]

    def oos_split(self) -> dt.date:
        """Walk-forward boundary: first 60% of the grid is in-sample (June: 2021-04-01)."""
        return self.snaps[int(len(self.snaps) * 0.6)]

    def in_sample(self) -> list[dt.date]:
        s = self.oos_split()
        return [d for d in self.snaps if d <= s]

    def out_of_sample(self) -> list[dt.date]:
        s = self.oos_split()
        return [d for d in self.snaps if d > s]

    # ── reads ────────────────────────────────────────────────────────────────
    def _hi(self, horizon: int) -> int:
        return 2 if horizon == 6 else 3

    def rows(self, component: str, snapshot: dt.date, horizon: int):
        """(score, forward_return) pairs for one snapshot, dropping unresolved returns."""
        hi = self._hi(horizon)
        return [(e[1][component], e[hi]) for e in self.entries[snapshot] if e[hi] is not None]

    def ic_series(self, component: str, horizon: int):
        """[(snapshot, IC, n_names)] over snapshots with a usable cross-section."""
        out = []
        for s in self.snaps:
            rows = self.rows(component, s, horizon)
            if len(rows) >= MIN_CROSS_SECTION:
                out.append((s, spearman([r[0] for r in rows], [r[1] for r in rows]), len(rows)))
        return out

    def evaluate(self, component: str, horizon: int) -> dict:
        """Mean IC, t, both-half means and the sign-consistency verdict."""
        ser = self.ic_series(component, horizon)
        ics = [x[1] for x in ser]
        mean_ic, t, n = tstat(ics)
        mid = self.midpoint()
        h1 = [x[1] for x in ser if x[0] <= mid and x[1] is not None]
        h2 = [x[1] for x in ser if x[0] > mid and x[1] is not None]
        m1 = sum(h1) / max(1, len(h1))
        m2 = sum(h2) / max(1, len(h2))
        same_sign = (m1 > 0) == (m2 > 0)
        if same_sign and abs(t) >= 3:
            verdict = "yes"
        elif abs(t) >= 2:
            verdict = "borderline"
        else:
            verdict = "no"
        return dict(component=component, horizon=horizon, mean_ic=mean_ic, t=t, n_snaps=n,
                    ic_h1=m1, ic_h2=m2, same_sign=same_sign, sign_consistent=verdict)


def build_panel(corpus_root: str = CORPUS_ROOT, snaps=None, verbose: bool = False) -> Panel:
    """
    Build the PIT panel from the corpus. Read-only throughout.

    Names without a usable price series are collected into `delisted_no_price`
    rather than silently skipped — that list IS the survivorship gap Milestone C
    has to bound.
    """
    snaps = snaps or month_starts()
    edgar = os.path.join(corpus_root, "edgar")
    prices_dir = os.path.join(corpus_root, "prices")

    with open(os.path.join(corpus_root, "universe", "manifest.json")) as f:
        tickers = json.load(f)["tickers"]

    entries = {s: [] for s in snaps}
    n_names = no_price = 0
    delisted_no_price = []

    for t in tickers:
        ppath = os.path.join(prices_dir, "%s.csv" % t)
        if not os.path.exists(ppath) or os.path.getsize(ppath) < 200:
            delisted_no_price.append(t)
            continue
        dates, adj = load_prices(ppath)
        if len(dates) < 300:
            no_price += 1
            continue

        g, gdei = {}, {}
        fpath = os.path.join(edgar, "%s.facts.json" % t)
        if os.path.exists(fpath):
            try:
                with open(fpath) as f:
                    fj = json.load(f)
                g = fj.get("facts", {}).get("us-gaap", {})
                gdei = fj.get("facts", {}).get("dei", {})
            except Exception:
                g, gdei = {}, {}

        rev_a = annual_facts(g, REV)
        op_a = annual_facts(g, OPINC)
        gp_a = annual_facts(g, GROSS)
        ocf_a = annual_facts(g, OCF)
        cap_a = annual_facts(g, CAPEX)
        eps_a = annual_facts(g, EPS)
        sh_i = instant_facts(gdei, SHARES)
        dltf = instant_facts(g, DEBT_LT)
        dcurf = instant_facts(g, DEBT_CUR)
        cashf = instant_facts(g, CASH)
        n_names += 1

        for D in snaps:
            pr = price_row(dates, adj, D)
            if pr is None:
                continue
            f6 = fwd_return(dates, adj, D, 6)
            f12 = fwd_return(dates, adj, D, 12)
            if f6 is None and f12 is None:
                continue
            row = dict(pr)
            row.update(fundamentals_as_of(D, rev_a, op_a, gp_a, ocf_a, cap_a, eps_a,
                                          sh_i, dltf, dcurf, cashf, row["price"]))
            entries[D].append((t, score_lt(row), f6, f12))

        if verbose:
            print(f"  {t}: {sum(1 for D in snaps if entries[D] and entries[D][-1][0] == t)} snaps")

    return Panel(snaps, entries, n_names, delisted_no_price, no_price)


def fundamentals_as_of(D, rev_a, op_a, gp_a, ocf_a, cap_a, eps_a,
                       sh_i, dltf, dcurf, cashf, price) -> dict:
    """
    As-filed fundamental inputs knowable on D.

    Everything routes through `as_of_annual` / `as_of_instant`, so `filed <= D`
    holds for every number here by construction. Fields stay absent when the
    underlying facts are missing, which sends `score_lt` down the same penalised
    default path production used.
    """
    out: dict = {}
    rev = as_of_annual(rev_a, D)
    if not rev:
        return out
    rev_end, rev_val = rev

    prior = prior_annual(rev_a, D, rev_end)
    if prior and prior[1] and rev_val:
        out["revenue_growth_pct"] = (rev_val / prior[1] - 1) * 100

    op = as_of_annual(op_a, D)
    if op and rev_val:
        out["operating_margin_pct"] = op[1] / rev_val * 100

    gp = as_of_annual(gp_a, D)
    if gp and rev_val:
        out["gross_margin_pct"] = gp[1] / rev_val * 100

    ocf = as_of_annual(ocf_a, D)
    cap = as_of_annual(cap_a, D)
    if ocf and rev_val:
        out["fcf_margin_pct"] = (ocf[1] - (cap[1] if cap else 0)) / rev_val * 100

    shares = as_of_instant(sh_i, D)
    if shares and shares > 0 and rev_val:
        debt = (as_of_instant(dltf, D) or 0) + (as_of_instant(dcurf, D) or 0)
        cash = as_of_instant(cashf, D) or 0
        out["ev_revenue"] = (price * shares + debt - cash) / rev_val

    eps = as_of_annual(eps_a, D)
    if eps:
        out["eps"] = eps[1]
        if eps[1] and eps[1] > 0:
            out["pe_ratio"] = price / eps[1]
    return out
