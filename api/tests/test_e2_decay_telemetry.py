"""
Tests for the E2 additions to research/harness/ic_report.py - decay slopes,
regime-tagged IC, and the accruing sign-persistence section
(PREREG_E2_DECAY_TELEMETRY.md items 1-3, live-panel side).

What is pinned, and the failure each pin prevents:

  1. DECAY SLOPE recovers a planted trend and refuses to invent one on flat or
     too-short series; slope + CI land in the weekly csv AND md.
  2. REGIME TAGGING is INSUFFICIENT on a young panel - the ~6-month live panel
     must NOT get fabricated 252-day-median states - and, on a panel that IS
     old enough, tags exactly per the registered definition (21d vol vs its
     trailing 252d median, min 126 days of vol history).
  3. The ACCRUING sign-persistence section self-labels INSUFFICIENT on a
     6-month fixture - the prereg says the live secondary CANNOT clear any bar
     today, so a verdict other than INSUFFICIENT there is a bug.
  4. Old report CSVs (pre-E2 columns) stay parseable by the delta logic, and
     the append-only contract holds with the new sections present.
"""

import csv as csvmod
import datetime as dt
import sys
from pathlib import Path

import pandas as pd
import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

import test_ic_harness as t1  # noqa: E402  (reuses the R2 fixture builder)
from research.harness.ic_report import (  # noqa: E402
    REGIME_BASE_MIN_DAYS, REGIME_BASE_WINDOW, REGIME_VOL_WINDOW, SERIES,
    decay_slope_ci, generate, load_panel, monthly_ic_series, regime_states,
    regime_table, render_markdown, run_analysis)


def _weekdays(n, start=dt.date(2025, 1, 6)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += dt.timedelta(days=1)
    return out


def _lcg(n, amp, seed):
    out, s = [], seed
    for _ in range(n):
        s = (1103515245 * s + 12345) % (2 ** 31)
        out.append(amp * (2.0 * s / (2 ** 31) - 1.0))
    return out


@pytest.fixture
def six_month_db(tmp_path, monkeypatch):
    """The R2 fixture DB extended to ~6 months of weekdays (126) - the shape of
    the real live panel today. Reuses the exact planted-signal builder."""
    monkeypatch.setattr(t1, "N_DAYS", 126)
    p = tmp_path / "six_month.db"
    t1._build_fixture_db(p)
    return p


def _regime_panel(n_days=320, n_tickers=12):
    """Panel old enough for the 252d median baseline: decaying low-vol phase
    (days 0-249), then a 20x vol jump. Deterministic, no RNG."""
    days = _weekdays(n_days)
    rows, prices = [], [100.0 + 2 * ti for ti in range(n_tickers)]
    for di, d in enumerate(days):
        mag = 0.001 * (0.997 ** di) if di < 250 else 0.02
        base = mag if di % 2 == 0 else -mag
        for ti in range(n_tickers):
            r = base * (1 + (ti - (n_tickers - 1) / 2) / 200.0)
            if di > 0:
                prices[ti] *= (1 + r)
            rows.append({"date": d, "ticker": f"T{ti:02d}", "price": prices[ti],
                         "lt_valuation": float((ti * 5 + di) % 23)})
    return pd.DataFrame(rows), days


# ─────────────────────────────────────────────────────────────────────────────
# 1. Decay slopes (telemetry)
# ─────────────────────────────────────────────────────────────────────────────
def test_decay_slope_recovers_a_planted_trend():
    days = _weekdays(120)
    nz = _lcg(120, 0.002, seed=8)
    ics = pd.Series([0.0005 * (d - days[0]).days + nz[i]
                     for i, d in enumerate(days)], index=days)
    slope, lo, hi = decay_slope_ci(ics)
    assert slope == pytest.approx(0.0005, rel=0.05)
    assert lo > 0, "CI must exclude zero for a real trend"
    assert lo < slope < hi


def test_decay_slope_flat_series_reports_zero_not_a_trend():
    days = _weekdays(60)
    slope, lo, hi = decay_slope_ci(pd.Series([0.03] * 60, index=days))
    assert slope == 0.0
    assert lo <= 0.0 <= hi


def test_decay_slope_too_short_is_nan_not_a_number():
    days = _weekdays(2)
    slope, lo, hi = decay_slope_ci(pd.Series([0.1, 0.2], index=days))
    assert slope != slope and lo != lo and hi != hi
    empty = pd.Series(dtype=float)
    assert decay_slope_ci(empty)[0] != decay_slope_ci(empty)[0]


def test_decay_columns_and_section_land_in_the_weekly_outputs(six_month_db, tmp_path):
    out = generate(str(six_month_db), tmp_path / "r", 365, (5, 21))
    df = out["results"]
    for col in ("decay_slope", "decay_ci_lo", "decay_ci_hi"):
        assert col in df.columns
    ok = df[df["verdict"] != "INSUFFICIENT"]
    assert (ok["decay_slope"].notna()).all(), "computable rows must carry a slope"
    # csv on disk carries the columns too
    with open(out["csv"]) as f:
        header = f.readline()
    assert "decay_slope" in header and "pers_verdict" in header
    md = Path(out["md"]).read_text()
    assert "## Decay slopes (telemetry)" in md
    assert "no verdict semantics change" in md


def test_decay_is_telemetry_only_verdicts_unchanged(six_month_db):
    """Adding E2 fields must not move any existing verdict field - the golden
    test pins the 60-day fixture; this pins the 126-day one structurally."""
    panel = load_panel(str(six_month_db), window_days=365)
    for r in run_analysis(panel, (5, 21)):
        assert r.verdict in {"SUPPORTED", "noise", "INSUFFICIENT"}
        # decay fields exist alongside, never in place of, the old ones
        assert hasattr(r, "t_adj") and hasattr(r, "decay_slope")


# ─────────────────────────────────────────────────────────────────────────────
# 2. Regime tagging - INSUFFICIENT branch first (the honest branch)
# ─────────────────────────────────────────────────────────────────────────────
def test_regime_is_insufficient_on_a_six_month_panel(six_month_db):
    panel = load_panel(str(six_month_db), window_days=365)
    states, reason = regime_states(panel)
    assert states is None
    assert "126" in reason and "252" in reason
    rt = regime_table(panel, (5, 21))
    assert rt["status"] == "INSUFFICIENT"
    assert "rows" not in rt, "INSUFFICIENT must report NOTHING, not partial states"


def test_regime_insufficient_is_said_in_the_report(six_month_db, tmp_path):
    out = generate(str(six_month_db), tmp_path / "r", 365, (5, 21))
    md = Path(out["md"]).read_text()
    assert "interim proxy pending E1 regime states" in md
    assert "Regime tagging INSUFFICIENT" in md
    assert "mean IC (HIGH)" not in md, "no state table may appear when INSUFFICIENT"
    assert out["regime"]["status"] == "INSUFFICIENT"


def test_regime_tags_exactly_per_the_registered_definition():
    panel, days = _regime_panel()
    states, reason = regime_states(panel)
    assert reason == ""

    # Warm-up honesty: nothing tagged before 21d vol + 126 vol observations.
    first_possible = days[REGIME_VOL_WINDOW + REGIME_BASE_MIN_DAYS - 2]
    assert states.index.min() > first_possible - dt.timedelta(days=1)
    assert states.index.min() == days[146]

    # Registered semantics on the two engineered phases.
    low_phase = states[[d < days[250] for d in states.index]]
    high_phase = states[[d >= days[275] for d in states.index]]
    assert set(low_phase) == {"LOW"}, "decaying-vol phase must read LOW"
    assert set(high_phase) == {"HIGH"}, "post-jump phase must read HIGH"

    # And the definition is literally 21d vol vs its trailing 252d median.
    from research.harness.ic_report import universe_median_return
    med = universe_median_return(panel)
    vol = med.rolling(REGIME_VOL_WINDOW, min_periods=REGIME_VOL_WINDOW).std(ddof=1)
    base = vol.rolling(REGIME_BASE_WINDOW, min_periods=REGIME_BASE_MIN_DAYS).median()
    for d in list(states.index)[:5] + list(states.index)[-5:]:
        assert states[d] == ("HIGH" if vol[d] > base[d] else "LOW")


def test_regime_table_reports_mean_ic_and_ndays_per_state():
    panel, _days = _regime_panel()
    rt = regime_table(panel, (5, 21))
    assert rt["status"] == "ok"
    assert rt["n_high"] > 0 and rt["n_low"] > 0
    assert rt["n_high"] + rt["n_low"] + rt["n_untagged"] == panel["date"].nunique()
    assert len(rt["rows"]) == 2  # lt_valuation at both horizons
    for row in rt["rows"]:
        assert row["n_high"] + row["n_low"] > 0
        assert row["series"] == "lt_valuation"


def test_regime_ok_branch_renders_a_state_table():
    from research.harness.ic_report import SeriesResult, results_to_frame
    df = results_to_frame([SeriesResult(
        series="lt_valuation", horizon=5, n_days=0, n_obs=0,
        mean_ic=float("nan"), std_ic=float("nan"), t_raw=float("nan"),
        t_adj=float("nan"), ic_h1=float("nan"), ic_h2=float("nan"),
        same_sign=False, verdict="INSUFFICIENT")])
    meta = {"run_date": "x", "generated_utc": "x", "db": "x", "window_days": 1,
            "horizons": [5], "start": "-", "end": "-", "n_days": 0,
            "n_tickers": 0, "n_rows": 0, "n_hypotheses": 1}
    regime = {"status": "ok", "n_high": 3, "n_low": 4, "n_untagged": 5,
              "rows": [{"series": "lt_valuation", "horizon": 5,
                        "ic_high": 0.1, "n_high": 3, "ic_low": -0.2, "n_low": 4}]}
    md = render_markdown(df, meta, "d", regime=regime)
    assert "mean IC (HIGH)" in md
    assert "3 HIGH days, 4 LOW days, 5 untagged" in md
    assert "NO hypothesis is tested on this split" in md


# ─────────────────────────────────────────────────────────────────────────────
# 3. Accruing sign-persistence: MUST self-label INSUFFICIENT today
# ─────────────────────────────────────────────────────────────────────────────
def test_accruing_persistence_is_insufficient_on_six_months(six_month_db, tmp_path):
    """The prereg's own words: 'At ~6 monthly observations this CANNOT clear
    any bar now ... Any number it produces this cycle is labeled INSUFFICIENT.'
    This is the test that it actually happens."""
    out = generate(str(six_month_db), tmp_path / "r", 365, (5, 21))
    df = out["results"]
    assert (df["pers_verdict"] == "INSUFFICIENT").all(), (
        df[df["pers_verdict"] != "INSUFFICIENT"][["series", "horizon", "pers_verdict"]])
    assert (df["pers_n_months"] <= 6).all()
    assert (df["pers_t"].isna()).all(), "no fabricated t on an INSUFFICIENT series"

    md = Path(out["md"]).read_text()
    assert "## Sign-persistence conditioner (accruing secondary)" in md
    assert "decided ONLY by the PIT-primary run on mill" in md
    assert "Hypothesis count on this panel: 30" in md


def test_monthly_aggregation_drops_thin_months():
    days = _weekdays(70)  # ~3.2 months
    ics = pd.Series([0.01 * ((i * 3) % 7 - 3) for i in range(70)], index=days)
    months, vals = monthly_ic_series(ics)
    assert len(months) >= 3
    assert all(m.day == 1 for m in months)
    # A month with fewer than 5 IC days must vanish, not average 2 points.
    sparse = ics[[d.month != 2 or d.day < 5 for d in ics.index]]
    m2, _ = monthly_ic_series(sparse)
    assert dt.date(2025, 2, 1) not in m2


# ─────────────────────────────────────────────────────────────────────────────
# 4. Compatibility + append-only with the new sections
# ─────────────────────────────────────────────────────────────────────────────
def test_previous_pre_e2_csv_is_still_parseable_by_the_delta(six_month_db, tmp_path):
    """A report written BEFORE E2 (no decay/pers columns) must still feed the
    week-over-week delta - the historical series is the deliverable."""
    out_dir = tmp_path / "r"
    first = generate(str(six_month_db), out_dir, 365, (5, 21))
    # Strip the E2 columns to simulate a pre-E2 report file.
    old_cols = ["series", "horizon", "n_days", "n_obs", "mean_ic", "std_ic",
                "t_raw", "t_adj", "ic_h1", "ic_h2", "same_sign", "verdict", "note"]
    pd.read_csv(first["csv"])[old_cols].to_csv(first["csv"], index=False)
    second = generate(str(six_month_db), out_dir, 365, (5, 21))
    assert "No verdict changes" in second["delta"]


def test_append_only_still_holds_with_e2_sections(six_month_db, tmp_path):
    out_dir = tmp_path / "r"
    first = generate(str(six_month_db), out_dir, 365, (5, 21))
    md1 = Path(first["md"]).read_bytes()
    second = generate(str(six_month_db), out_dir, 365, (5, 21))
    assert Path(second["md"]) != Path(first["md"])
    assert Path(first["md"]).read_bytes() == md1
    assert len(list(out_dir.glob("ic-report-*.csv"))) == 2


def test_run_with_e2_sections_does_not_mutate_the_db(six_month_db, tmp_path):
    import hashlib
    before = hashlib.sha256(six_month_db.read_bytes()).hexdigest()
    generate(str(six_month_db), tmp_path / "r", 365, (5, 21))
    assert hashlib.sha256(six_month_db.read_bytes()).hexdigest() == before


def test_hypothesis_count_still_thirty(six_month_db):
    panel = load_panel(str(six_month_db), window_days=365)
    assert len(SERIES) == 15
    assert len(run_analysis(panel, (5, 21))) == 30
