"""
Tests for research/harness/persistence.py and research/lane1/e2_persistence.py
- the E2 sign-persistence conditioner (PREREG_E2_DECAY_TELEMETRY.md).

Section 9b discipline: every verdict branch must be shown able to fire AND able
to fail. What is pinned here, and why:

  1. NEWEY-WEST - the lag-3 HAC t is implemented by hand (mill has no
     statsmodels), so it is pinned against HAND-COMPUTED values on a small
     fixed series. If the estimator drifts, every verdict downstream is wrong.
  2. ALL THREE VERDICTS on one deterministic fixture set: a planted persistent
     component clears the registered bar (SUPPORTED fires), a planted noise
     component reads NOISE, a short series reads INSUFFICIENT.
  3. BOTH-HALVES clause actually rejects: an effect that flips sign between
     sample halves with a large |t| must NOT be SUPPORTED.
  4. BONFERRONI actually binds: a raw pass (|t| >= 3, same-sign halves) that
     fails the family-adjusted level must be NOISE - and the SAME series with
     family size 1 is SUPPORTED, isolating the clause.
  5. DIRECTION is fixed: a significant negative effect is FAILED_H1, never
     SUPPORTED.
  6. The registered constants are frozen (this is the test the induced-failure
     drill flips first).

All fixtures are deterministic: integer LCG noise, no clock, no network.
"""

import csv
import datetime as dt
import io
import math
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from research.harness.persistence import (  # noqa: E402
    ALPHA, MIN_MONTHS, NW_LAG, T_BAR, TRAILING_MONTHS,
    build_pairs, free_path, newey_west_slope, persistence_test, run_family)
import research.lane1.e2_persistence as e2p  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic fixture machinery — integer LCG, stable on every platform.
# ─────────────────────────────────────────────────────────────────────────────
def _months(n, start=dt.date(2010, 1, 1)):
    out, y, m = [], start.year, start.month
    for _ in range(n):
        out.append(dt.date(y, m, 1))
        m += 1
        if m > 12:
            m, y = 1, y + 1
    return out


def _lcg(n, amp, seed):
    out, s = [], seed
    for _ in range(n):
        s = (1103515245 * s + 12345) % (2 ** 31)
        out.append(amp * (2.0 * s / (2 ** 31) - 1.0))
    return out


def _blocks(n, block, level, noise_amp, seed):
    """Regime-block IC series: level alternates sign every `block` months, so
    the trailing-12mo sign genuinely predicts the next month inside blocks."""
    nz = _lcg(n, noise_amp, seed)
    return [(level if (i // block) % 2 == 0 else -level) + nz[i] for i in range(n)]


def _planted_persistent(n=120):
    # block 30 >> trailing window 12: the trailing sign is right for ~23 of
    # every 30 months. t_nw ~ +5.1 - clears even the Bonferroni-adjusted bar.
    return _blocks(n, 30, 0.08, 0.01, seed=5)


def _planted_noise(n=120):
    return _lcg(n, 0.05, seed=42)  # t_nw ~ +1.3


def _anti_persistent(n=120):
    """Self-referentially contrarian: each month does the OPPOSITE of the
    trailing sign. A significant NEGATIVE effect - the FAILED_H1 branch."""
    nz = _lcg(n, 0.01, seed=17)
    ics = []
    for i in range(n):
        if i < TRAILING_MONTHS:
            ics.append(0.05 if i % 2 == 0 else -0.05)
        else:
            tr = sum(ics[i - TRAILING_MONTHS:i]) / TRAILING_MONTHS
            ics.append(-0.08 * (1 if tr > 0 else -1) + nz[i])
    return ics


def _halves_flip(n=240):
    """Strongly persistent first half, mildly contrarian second half. Overall
    t_nw ~ +4.0 (clears the raw t bar) but the effect flips sign at the sample
    midpoint - the both-halves clause is the ONLY thing rejecting it."""
    nzA = _lcg(n, 0.005, seed=11)
    nzB = _lcg(n, 0.01, seed=13)
    half = int(n * 0.53)
    ics = []
    for i in range(n):
        if i < half:
            ics.append((0.1 if (i // 50) % 2 == 0 else -0.1) + nzA[i])
        else:
            tr = sum(ics[i - TRAILING_MONTHS:i]) / TRAILING_MONTHS
            ics.append(-0.015 * (1 if tr > 0 else -1) + nzB[i])
    return ics


def _bonferroni_border(n=120):
    """t_nw ~ +3.40 with same-sign halves: passes |t| >= 3 raw, fails the
    family-of-6 Bonferroni level (needs ~3.51)."""
    return _blocks(n, 24, 0.08, 0.01, seed=5)


# ─────────────────────────────────────────────────────────────────────────────
# 1. Newey-West pinned against hand-computed values
# ─────────────────────────────────────────────────────────────────────────────
def test_newey_west_matches_hand_computed():
    """
    n=8, x alternating +/-1 so X'X = diag(8, 8) and everything is hand-tractable.

        y = [1.0, -0.9, 1.2, -1.1, 0.8, -1.0, 1.1, -0.7]

    beta0 = mean(y) = 0.4/8 = 0.05
    beta1 = sum(x*y)/8 = 7.8/8 = 0.975
    residuals e = y - 0.05 - 0.975x
      = [-0.025, 0.025, 0.175, -0.175, -0.225, -0.075, 0.075, 0.225]
    u_t = x_t e_t = [-0.025, -0.025, 0.175, 0.175, -0.225, 0.075, 0.075, -0.225]
    S11 = sum u^2 + 2*(w1*sum_l1 + w2*sum_l2 + w3*sum_l3),  w = (0.75, 0.5, 0.25)
      sum u^2 = 0.175
      lag1 sum = -0.040625,  lag2 sum = -0.068750,  lag3 sum = +0.078125
      S11 = 0.175 + 2*(0.75*-0.040625 + 0.5*-0.068750 + 0.25*0.078125)
          = 0.175 - 0.090625 = 0.084375
    Var(b1) = S11 / 8^2 = 0.001318359375   (X'X diagonal, so no cross terms)
    se = sqrt(0.001318359375) = 0.0363092188706945...
    t  = 0.975 / se = 26.8526845337047...
    """
    y = [1.0, -0.9, 1.2, -1.1, 0.8, -1.0, 1.1, -0.7]
    x = [1, -1, 1, -1, 1, -1, 1, -1]
    beta, se, t = newey_west_slope(y, x, lag=3)
    assert beta == pytest.approx(0.975, abs=1e-12)
    assert se == pytest.approx(math.sqrt(0.084375 / 64), abs=1e-12)
    assert t == pytest.approx(26.852684533704757, abs=1e-9)


def test_newey_west_degenerate_inputs():
    assert newey_west_slope([1.0, 2.0], [1.0, 2.0])[0] != newey_west_slope([1.0, 2.0], [1.0, 2.0])[0]  # n<3 -> nan
    b, se, t = newey_west_slope([1.0, 2.0, 3.0, 4.0], [2.0, 2.0, 2.0, 2.0])
    assert b != b and t != t  # constant regressor -> nan


# ─────────────────────────────────────────────────────────────────────────────
# 2. All three verdict branches on ONE fixture set
# ─────────────────────────────────────────────────────────────────────────────
def test_all_three_verdicts_on_one_fixture_set():
    family = {
        "planted": (_months(120), _planted_persistent()),
        "noisy": (_months(120), _planted_noise()),
        "short": (_months(20), _lcg(20, 0.05, seed=9)),
    }
    by_name = {r.component: r for r in run_family(family)}

    r = by_name["planted"]
    assert r.verdict == "SUPPORTED", (r.verdict, r.t_nw, r.note)
    assert r.beta > 0 and abs(r.t_nw) >= T_BAR and r.same_sign
    assert r.p_bonf <= ALPHA
    assert r.bonferroni_n == 3  # full family size, printed downstream

    assert by_name["noisy"].verdict == "NOISE"
    assert abs(by_name["noisy"].t_nw) < T_BAR

    r = by_name["short"]
    assert r.verdict == "INSUFFICIENT"
    assert "20 monthly ICs < 24" in r.note
    assert r.t_nw != r.t_nw, "INSUFFICIENT must not carry a fabricated t"


def test_pair_construction_is_the_registered_one():
    months = _months(30)
    ics = [float(i) for i in range(30)]
    pairs = build_pairs(months, ics)
    assert len(pairs) == 30 - TRAILING_MONTHS
    d, s, o = pairs[0]
    assert d == months[12]           # first month with 12 trailing months
    assert o == 12.0                 # outcome is IC_m itself
    assert s == 1.0                  # sign(mean of months 0..11)


def test_insufficient_boundary_is_exactly_24():
    ics24 = _blocks(24, 8, 0.05, 0.005, seed=3)
    assert persistence_test(_months(23), ics24[:23], "c", 1).verdict == "INSUFFICIENT"
    assert persistence_test(_months(24), ics24, "c", 1).verdict != "INSUFFICIENT"


def test_constant_trailing_sign_is_insufficient_not_fabricated():
    ics = [0.05 + v for v in _lcg(60, 0.01, seed=4)]  # always positive
    r = persistence_test(_months(60), ics, "c", 1)
    assert r.verdict == "INSUFFICIENT"
    assert "trailing sign constant" in r.note
    assert r.t_nw != r.t_nw


# ─────────────────────────────────────────────────────────────────────────────
# 3. Both-halves clause actually rejects
# ─────────────────────────────────────────────────────────────────────────────
def test_effect_flipping_halves_is_not_supported_despite_large_t():
    r = persistence_test(_months(240), _halves_flip(), "flip", bonferroni_n=1)
    assert abs(r.t_nw) >= T_BAR, f"fixture lost its power: t={r.t_nw}"
    assert r.p_bonf <= ALPHA, "fixture must pass the significance clauses"
    assert r.effect_h1 > 0 > r.effect_h2, "fixture must actually flip halves"
    assert not r.same_sign
    assert r.verdict == "NOISE", "half-flip must reject SUPPORTED"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Bonferroni actually binds
# ─────────────────────────────────────────────────────────────────────────────
def test_bonferroni_actually_binds():
    months, ics = _months(120), _bonferroni_border()
    r6 = persistence_test(months, ics, "border", bonferroni_n=6)
    # The fixture must sit in the band where ONLY Bonferroni decides.
    assert T_BAR <= abs(r6.t_nw) < 3.6, f"fixture drifted out of band: {r6.t_nw}"
    assert r6.same_sign
    assert r6.p_two <= ALPHA, "raw significance must pass"
    assert r6.p_bonf > ALPHA, "family-adjusted significance must fail"
    assert r6.verdict == "NOISE"
    assert "Bonferroni" in r6.note

    r1 = persistence_test(months, ics, "border", bonferroni_n=1)
    assert r1.verdict == "SUPPORTED", "same series alone must pass - the ONLY difference is N"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Direction fixed: significant negative = FAILED_H1
# ─────────────────────────────────────────────────────────────────────────────
def test_significant_contrarian_effect_is_failed_h1_never_supported():
    r = persistence_test(_months(120), _anti_persistent(), "anti", bonferroni_n=1)
    assert r.t_nw <= -T_BAR, f"fixture must be significantly negative: {r.t_nw}"
    assert r.verdict == "FAILED_H1"
    assert r.verdict != "SUPPORTED"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Registered constants frozen (induced-failure drill flips these first)
# ─────────────────────────────────────────────────────────────────────────────
def test_registered_bar_is_frozen():
    """PREREG_E2_DECAY_TELEMETRY.md 'Statistic and bar (fixed now)'. If this
    fails, someone weakened the registration in code."""
    assert T_BAR == 3.0
    assert NW_LAG == 3
    assert TRAILING_MONTHS == 12
    assert MIN_MONTHS == 24
    assert ALPHA == math.erfc(3.0 / math.sqrt(2.0))


# ─────────────────────────────────────────────────────────────────────────────
# 7. PIT-primary tool (synthetic everywhere; corpus-gated at the end)
# ─────────────────────────────────────────────────────────────────────────────
def _synthetic_six_family(supported=False):
    fam = {}
    comps = ["rule_of_40", "valuation", "fcf_margin", "trend",
             "earnings_quality", "discount_momentum"]
    for i, c in enumerate(comps):
        fam[c] = (_months(120), _lcg(120, 0.05, seed=20 + i))
    if supported:
        # Strong plant so it clears even the N=6 Bonferroni level.
        fam["valuation"] = (_months(120), _blocks(120, 30, 0.15, 0.01, seed=5))
    return fam


def test_pit_tool_hypothesis_count_is_six_and_header_states_decider():
    results = e2p.analyse(_synthetic_six_family())
    assert len(results) == 6
    assert all(r.bonferroni_n == 6 for r in results)
    meta = {"run_date": "2026-08-10", "generated": "x", "corpus": "/c",
            "horizon": 12, "n_names": 1, "n_snaps": 1, "n_hypotheses": 6,
            "bar": e2p.BAR_TEXT}
    md = e2p.render_md(results, meta)
    assert "THE KILL CONDITION IS DECIDED ONLY BY THIS PIT RUN" in md
    assert "**6** (one per LT component)" in md


def test_pit_tool_kill_condition_reads_from_verdicts():
    meta = {"run_date": "2026-08-10", "generated": "x", "corpus": "/c",
            "horizon": 12, "n_names": 1, "n_snaps": 1, "n_hypotheses": 6,
            "bar": e2p.BAR_TEXT}
    dead = e2p.analyse(_synthetic_six_family(supported=False))
    assert e2p.kill_condition_met(dead)
    assert "KILL CONDITION MET" in e2p.render_md(dead, meta)

    alive = e2p.analyse(_synthetic_six_family(supported=True))
    assert not e2p.kill_condition_met(alive)
    md = e2p.render_md(alive, meta)
    assert "Kill condition NOT met" in md
    assert "does not promote or condition anything" in md


def test_pit_tool_nonprimary_horizon_cannot_decide_the_kill():
    results = e2p.analyse(_synthetic_six_family(supported=False))
    meta = {"run_date": "2026-08-10", "generated": "x", "corpus": "/c",
            "horizon": 6, "n_names": 1, "n_snaps": 1, "n_hypotheses": 6,
            "bar": e2p.BAR_TEXT}
    md = e2p.render_md(results, meta)
    assert "NON-PRIMARY RUN" in md
    assert "KILL CONDITION MET" not in md
    assert e2p.PRIMARY_HORIZON == 12


def test_pit_tool_csv_roundtrips():
    results = e2p.analyse(_synthetic_six_family())
    meta = {"horizon": 12}
    rows = list(csv.DictReader(io.StringIO(e2p.render_csv(results, meta))))
    assert len(rows) == 6
    assert set(e2p.CSV_FIELDS) <= set(rows[0])
    assert all(r["bonferroni_n"] == "6" for r in rows)
    assert {r["verdict"] for r in rows} <= {"SUPPORTED", "NOISE", "INSUFFICIENT", "FAILED_H1"}


def test_free_path_is_append_only(tmp_path):
    p1 = free_path(tmp_path, "e2-persistence-2026-08-10", ".md")
    p1.write_text("first")
    p2 = free_path(tmp_path, "e2-persistence-2026-08-10", ".md")
    assert p2 != p1
    p2.write_text("second")
    assert p1.read_text() == "first"


def test_e2_persistence_is_covered_by_the_lane1_write_guard():
    """The corpus write-guard test globs research/lane1/*.py; make sure the new
    tool is actually inside its perimeter."""
    assert (REPO_ROOT / "research" / "lane1" / "e2_persistence.py").exists()
    src = (REPO_ROOT / "research" / "lane1" / "e2_persistence.py").read_text()
    assert "lt-recon-data" not in src.split('"""')[2], (
        "output paths must not point into the corpus")


# ─────────────────────────────────────────────────────────────────────────────
# 8. Corpus-gated: the real PIT-primary run (mill only)
# ─────────────────────────────────────────────────────────────────────────────
CORPUS = Path.home() / "lt-recon-data"
needs_corpus = pytest.mark.skipif(
    not (CORPUS / "universe" / "manifest.json").exists(),
    reason="decade PIT corpus not present (lives on mill)")


@needs_corpus
def test_pit_primary_runs_and_writes_dated_artifacts(tmp_path):
    """The supervised mill step, in test form: run against the corpus, read the
    ARTIFACT (not the exit code) for the verdicts."""
    assert e2p.main(["--corpus", str(CORPUS), "--out", str(tmp_path)]) == 0
    mds = list(tmp_path.glob("e2-persistence-*.md"))
    csvs = list(tmp_path.glob("e2-persistence-*.csv"))
    assert len(mds) == 1 and len(csvs) == 1
    md = mds[0].read_text()
    assert "THE KILL CONDITION IS DECIDED ONLY BY THIS PIT RUN" in md
    assert "**6** (one per LT component)" in md
    rows = list(csv.DictReader(csvs[0].open()))
    assert len(rows) == 6
    # ~114 usable pairs per component expected by the prereg; assert powered.
    assert all(int(r["n_pairs"]) >= 90 for r in rows)
    assert all(r["verdict"] != "INSUFFICIENT" for r in rows)
