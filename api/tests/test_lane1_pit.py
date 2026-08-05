"""
Tests for research/lane1/ — the PIT reconstruction machinery.

The corpus is 2.2 GB and lives only on mill, so the tests split in two:

  * Logic tests (always run) use hand-built synthetic facts. They pin the parts
    that would silently corrupt every downstream number — above all the
    `filed <= D` discipline, which is the single assumption separating this from
    a hindsight backtest.
  * The reproduction test (skipped without the corpus) is the Milestone A gate.

What is deliberately pinned here, and why each would be invisible otherwise:

  1. LOOKAHEAD — a restatement filed after D must never be visible at D.
  2. AS-FILED — among facts for one period, the FIRST filing wins, not the last.
  3. SPLIT POINTS — both the sign-consistency midpoint and the OOS split are
     defined on the snapshot WINDOW, not on the list of snapshots that produced
     an observation (RESULT_R2_IC_HARNESS correction 4: splitting the
     observation list moved a boundary by a full horizon and flipped a verdict).
  4. READ-ONLY — nothing under research/lane1/ may write to the corpus.
"""

import datetime as dt
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from research.lane1.panel import Panel, fundamentals_as_of, month_starts  # noqa: E402
from research.lane1.pit import (annual_facts, as_of_annual, as_of_instant,  # noqa: E402
                                instant_facts, prior_annual)
from research.lane1.prices import fwd_return, price_row  # noqa: E402
from research.lane1.scoring import W, score_lt  # noqa: E402
from research.lane1.stats import pooled_quintiles, rank, spearman  # noqa: E402

D = dt.date


def _annual(end, filed, val, form="10-K", fp="FY", start=None):
    """One companyfacts annual duration fact."""
    start = start or (D.fromisoformat(end) - dt.timedelta(days=365)).isoformat()
    return {"start": start, "end": end, "filed": filed, "val": val, "form": form, "fp": fp}


def _facts(entries):
    return {"Revenues": {"units": {"USD": entries}}}


# ─────────────────────────────────────────────────────────────────────────────
# 1. The lookahead guard — the whole game
# ─────────────────────────────────────────────────────────────────────────────
def test_fact_filed_after_snapshot_is_invisible():
    """A number not yet filed on D cannot be used at D."""
    facts = annual_facts(_facts([
        _annual("2020-12-31", "2021-02-15", 100.0),
        _annual("2021-12-31", "2022-02-15", 200.0),   # filed AFTER the snapshot
    ]), ["Revenues"])
    got = as_of_annual(facts, D(2021, 6, 1))
    assert got is not None
    assert got[0] == D(2020, 12, 31), "used a period whose filing had not happened yet"
    assert got[1] == 100.0


def test_restatement_does_not_leak_backwards():
    """
    The canonical lookahead bug: FY2020 is restated in 2022. A backtest standing
    at 2021-06-01 must see the ORIGINAL 100.0, never the restated 175.0 —
    otherwise every pre-2022 snapshot is scored on information from the future.
    """
    facts = annual_facts(_facts([
        _annual("2020-12-31", "2021-02-15", 100.0),
        _annual("2020-12-31", "2022-03-01", 175.0),   # restatement, same period
    ]), ["Revenues"])

    at_2021 = as_of_annual(facts, D(2021, 6, 1))
    assert at_2021[1] == 100.0, "restated value leaked into an earlier snapshot"

    # Even once the restatement is filed, as-filed discipline keeps the original.
    at_2023 = as_of_annual(facts, D(2023, 6, 1))
    assert at_2023[1] == 100.0, "as-filed must keep the FIRST filing for a period"


def test_no_facts_before_first_filing():
    facts = annual_facts(_facts([_annual("2020-12-31", "2021-02-15", 100.0)]), ["Revenues"])
    assert as_of_annual(facts, D(2021, 1, 1)) is None


def test_prior_annual_finds_the_year_before():
    facts = annual_facts(_facts([
        _annual("2019-12-31", "2020-02-15", 80.0),
        _annual("2020-12-31", "2021-02-15", 100.0),
    ]), ["Revenues"])
    cur = as_of_annual(facts, D(2021, 6, 1))
    prior = prior_annual(facts, D(2021, 6, 1), cur[0])
    assert prior[1] == 80.0
    # YoY growth from as-filed values only.
    assert (cur[1] / prior[1] - 1) * 100 == pytest.approx(25.0)


def test_prior_annual_respects_filed_cutoff():
    """The prior year must also have been filed by D."""
    facts = annual_facts(_facts([
        _annual("2019-12-31", "2022-01-01", 80.0),    # filed late
        _annual("2020-12-31", "2021-02-15", 100.0),
    ]), ["Revenues"])
    cur = as_of_annual(facts, D(2021, 6, 1))
    assert prior_annual(facts, D(2021, 6, 1), cur[0]) is None


def test_only_annual_10k_facts_count():
    """Quarterly and non-10-K facts must not enter the annual series."""
    entries = [
        _annual("2020-12-31", "2021-02-15", 100.0),
        {"start": "2020-10-01", "end": "2020-12-31", "filed": "2021-02-15",
         "val": 30.0, "form": "10-Q", "fp": "Q4"},                       # quarterly
        _annual("2020-12-31", "2021-02-15", 999.0, form="8-K"),          # wrong form
        _annual("2020-12-31", "2021-02-15", 888.0, fp="Q4"),             # wrong fp
    ]
    facts = annual_facts(_facts(entries), ["Revenues"])
    assert len(facts) == 1 and facts[0][2] == 100.0


def test_instant_facts_exclude_durations():
    node = {"CashAndCashEquivalentsAtCarryingValue": {"units": {"USD": [
        {"end": "2020-12-31", "filed": "2021-02-15", "val": 50.0},                    # instant
        {"start": "2020-01-01", "end": "2020-12-31", "filed": "2021-02-15", "val": 9},  # duration
    ]}}}
    facts = instant_facts(node, ["CashAndCashEquivalentsAtCarryingValue"])
    assert len(facts) == 1
    assert as_of_instant(facts, D(2021, 6, 1)) == 50.0


def test_concept_fallback_order_is_honoured():
    """First concept WITH DATA wins; an empty preferred tag falls through."""
    node = {"Revenues": {"units": {}},
            "SalesRevenueNet": {"units": {"USD": [_annual("2020-12-31", "2021-02-15", 42.0)]}}}
    facts = annual_facts(node, ["Revenues", "SalesRevenueNet"])
    assert facts and facts[0][2] == 42.0


def test_fundamentals_as_of_never_uses_future_filings():
    """End-to-end on the row builder: every field must be knowable at D."""
    rev = annual_facts(_facts([
        _annual("2019-12-31", "2020-02-15", 80.0),
        _annual("2020-12-31", "2021-02-15", 100.0),
        _annual("2021-12-31", "2022-02-15", 500.0),   # future
    ]), ["Revenues"])
    out = fundamentals_as_of(D(2021, 6, 1), rev, [], [], [], [], [], [], [], [], [], 10.0)
    assert out["revenue_growth_pct"] == pytest.approx(25.0)
    assert "500" not in repr(out)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Price inputs
# ─────────────────────────────────────────────────────────────────────────────
def _series(n=400, start=D(2019, 1, 1), step=1.0):
    dates = [start + dt.timedelta(days=i) for i in range(n)]
    adj = [100.0 + i * step for i in range(n)]
    return dates, adj


def test_price_row_uses_no_bar_after_D():
    dates, adj = _series()
    D0 = dates[300]
    row = price_row(dates, adj, D0)
    assert row["price"] == adj[300], "price came from a bar after the snapshot"


def test_price_row_requires_a_year_of_history():
    dates, adj = _series(n=400)
    assert price_row(dates, adj, dates[100]) is None
    assert price_row(dates, adj, dates[300]) is not None


def test_fwd_return_is_none_past_the_end_of_the_series():
    """Truncating instead of returning None would invent survivor-flattered returns."""
    dates, adj = _series(n=400)
    assert fwd_return(dates, adj, dates[399], 12) is None
    assert fwd_return(dates, adj, dates[300], 1) is not None


# ─────────────────────────────────────────────────────────────────────────────
# 3. Scoring port fidelity
# ─────────────────────────────────────────────────────────────────────────────
def test_weights_are_the_june_defaults():
    assert W == {"rule_of_40": 25, "valuation": 20, "fcf_margin": 15,
                 "trend": 15, "earnings_quality": 10, "discount_momentum": 15}
    assert sum(W.values()) == 100


def test_score_lt_components_are_bounded_by_their_weights():
    for row in ({}, {"ev_revenue": 0.1, "revenue_growth_pct": 50},
                {"ev_revenue": 900, "revenue_growth_pct": -90, "fcf_margin_pct": -50}):
        bd = score_lt(row)
        for comp, w in W.items():
            assert 0 <= bd[comp] <= w, f"{comp} outside [0,{w}] for {row}"
        assert bd["lt_score"] == pytest.approx(sum(bd[c] for c in W), abs=0.05)


def test_valuation_prefers_cheap_over_expensive():
    """Direction sanity: the component that survived June must rank cheap above dear."""
    cheap = score_lt({"ev_revenue": 2.0, "revenue_growth_pct": 20})["valuation"]
    dear = score_lt({"ev_revenue": 60.0, "revenue_growth_pct": 20})["valuation"]
    assert cheap > dear


def test_missing_fundamentals_take_the_penalised_path_not_a_crash():
    bd = score_lt({"price": 10.0})
    assert bd["fcf_margin"] == 0
    assert bd["valuation"] == score_lt({"ev_revenue": 999})["valuation"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. Statistics
# ─────────────────────────────────────────────────────────────────────────────
def test_rank_averages_ties():
    """Component scores round to 0.1, so ties are common and must share a rank."""
    assert rank([10.0, 10.0, 20.0]) == [1.5, 1.5, 3.0]


def test_spearman_is_monotone_invariant():
    a = [1, 2, 3, 4, 5]
    assert spearman(a, [10, 20, 30, 40, 50]) == pytest.approx(1.0)
    assert spearman(a, [1, 4, 9, 16, 25]) == pytest.approx(1.0)   # monotone, non-linear
    assert spearman(a, [5, 4, 3, 2, 1]) == pytest.approx(-1.0)


def test_quintiles_are_cut_within_snapshot_then_pooled():
    """
    Cutting on the pooled distribution would rank a 2014 name against a 2024 one
    and convert market-wide drift into fake cross-sectional edge.
    """
    hi = [(float(i), 0.10) for i in range(50, 100)]
    lo = [(float(i), -0.10) for i in range(0, 50)]
    snap_a = lo[:25] + hi[:25]
    snap_b = lo[25:] + hi[25:]
    spread, q1, q5 = pooled_quintiles([snap_a, snap_b])
    assert q5 > q1 and spread == pytest.approx(0.20, abs=1e-9)


def test_thin_cross_sections_are_dropped():
    assert pooled_quintiles([[(1.0, 0.5)] * 10]) is None


# ─────────────────────────────────────────────────────────────────────────────
# 5. Split points live on the WINDOW (R2 correction 4)
# ─────────────────────────────────────────────────────────────────────────────
def _panel_with_sparse_tail():
    """
    127 snapshots, but only the first 40 carry entries — the shape that breaks a
    split defined on observations instead of the window.
    """
    snaps = month_starts()
    entries = {s: [] for s in snaps}
    for s in snaps[:40]:
        entries[s] = [(f"T{i}", {"valuation": float(i), "lt_score": float(i)}, 0.01, 0.02)
                      for i in range(40)]
    return Panel(snaps, entries, n_names=40, delisted_no_price=[], no_price=0)


def test_midpoint_is_the_window_midpoint_not_the_observed_one():
    p = _panel_with_sparse_tail()
    assert p.midpoint() == p.snaps[len(p.snaps) // 2]
    observed = [s for s in p.snaps if p.entries[s]]
    assert p.midpoint() > observed[len(observed) // 2], (
        "midpoint tracked the observation list — the R2 correction-4 bug")


def test_oos_split_is_the_window_60pct_and_matches_june():
    p = _panel_with_sparse_tail()
    assert p.oos_split() == p.snaps[int(len(p.snaps) * 0.6)]
    assert p.oos_split() == D(2021, 4, 1), "June's documented OOS boundary moved"
    assert len(p.in_sample()) == 77 and len(p.out_of_sample()) == 50


def test_june_snapshot_grid_is_127_months():
    snaps = month_starts()
    assert len(snaps) == 127
    assert snaps[0] == D(2014, 12, 1) and snaps[-1] == D(2025, 6, 1)


# ─────────────────────────────────────────────────────────────────────────────
# 6. Read-only contract against the corpus
# ─────────────────────────────────────────────────────────────────────────────
def test_lane1_never_opens_the_corpus_for_write():
    """
    The corpus is the single copy of a 2.2 GB irreplaceable dataset (REBUILD_PLAN
    §0). Nothing in research/lane1/ may write, move, or delete inside it.
    """
    import ast
    lane1 = REPO_ROOT / "research" / "lane1"
    offenders = {}
    for path in sorted(lane1.glob("*.py")):
        tree = ast.parse(path.read_text())
        bad = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                fn = node.func
                name = getattr(fn, "id", None) or getattr(fn, "attr", None)
                if name == "open":
                    # Any explicit mode argument other than a read mode is a fail.
                    for arg in list(node.args[1:2]) + [k.value for k in node.keywords
                                                       if k.arg == "mode"]:
                        if isinstance(arg, ast.Constant) and "r" not in str(arg.value):
                            bad.append(f"line {node.lineno}: open(mode={arg.value!r})")
                if name in {"remove", "unlink", "rmtree", "rename", "replace", "rmdir"}:
                    bad.append(f"line {node.lineno}: {name}()")
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"write/delete calls in research/lane1/: {offenders}"


def test_corpus_root_is_only_ever_read():
    """The corpus path must not be joined into any output destination."""
    src = (REPO_ROOT / "research" / "lane1" / "panel.py").read_text()
    assert 'CORPUS_ROOT = os.path.expanduser("~/lt-recon-data")' in src
    assert "lt-recon-data-derived" not in src, (
        "panel.py should not know about the output dir; keep read and write separate")


# ─────────────────────────────────────────────────────────────────────────────
# 7. Milestone A gate (needs the corpus — skipped elsewhere)
# ─────────────────────────────────────────────────────────────────────────────
CORPUS = Path.home() / "lt-recon-data"
needs_corpus = pytest.mark.skipif(
    not (CORPUS / "universe" / "manifest.json").exists(),
    reason="decade PIT corpus not present (lives on mill)")


@needs_corpus
def test_june_reproduction_gate():
    """Milestone A: the port must reproduce June, or nothing downstream is trustworthy."""
    from research.lane1.reproduce_june import main
    assert main(["--corpus", str(CORPUS)]) == 0
