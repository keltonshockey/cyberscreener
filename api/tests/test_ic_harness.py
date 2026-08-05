"""
Tests for research/harness/ic_report.py — the standing IC report.

Four things are pinned here, and each maps to a way this harness could quietly
become worthless:

1. GOLDEN OUTPUT — a deterministic synthetic DB with a known planted signal
   produces byte-stable IC numbers. Catches silent methodology drift, which is
   the failure that would make a *weekly* report actively misleading rather than
   merely wrong once.
2. READ-ONLY — the harness's own connection cannot write. REBUILD_PLAN section 0.
3. APPEND-ONLY — a second run never touches the first run's files. The value of
   this job is the historical series; an overwriting job destroys exactly the
   record it exists to build.
4. DEGENERATE INPUT — a constant column reports INSUFFICIENT rather than
   crashing or inventing a correlation.

To regenerate the golden after an INTENTIONAL methodology change:
    UPDATE_IC_GOLDEN=1 python -m pytest tests/test_ic_harness.py
then review the diff like any code change.
"""
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from research.harness.ic_report import (  # noqa: E402
    SERIES, evaluate, generate, load_panel, run_analysis, results_to_frame,
    window_midpoint, daily_ic, forward_returns,
)

GOLDEN = Path(__file__).parent / "fixtures" / "ic_golden.json"

# Enough names to clear MIN_NAMES_PER_DAY, enough days to clear MIN_DAYS with a
# 5d forward window to spare.
N_TICKERS = 14
N_DAYS = 60


def _build_fixture_db(path: Path, constant_component: str | None = None) -> None:
    """
    Deterministic synthetic DB — no RNG, no clock, no network.

    `lt_valuation` is constructed to genuinely predict the 5d forward return
    (the planted signal, so a real IC is measurable), while `opt_liquidity` is
    pure sawtooth noise uncorrelated with returns. Everything is generated from
    integer arithmetic so the golden file is stable across platforms.
    """
    conn = sqlite3.connect(path)
    conn.executescript(
        """
        CREATE TABLE scans (
            id INTEGER PRIMARY KEY, timestamp TEXT, tickers_scanned INTEGER,
            duration_seconds REAL, config_json TEXT, intel_layers TEXT
        );
        CREATE TABLE scores (
            id INTEGER PRIMARY KEY, scan_id INTEGER, ticker TEXT, price REAL,
            lt_score REAL, opt_score REAL,
            lt_rule_of_40 REAL, lt_valuation REAL, lt_fcf_margin REAL,
            lt_trend REAL, lt_earnings_quality REAL, lt_discount_momentum REAL,
            opt_earnings_catalyst REAL, opt_iv_context REAL, opt_directional REAL,
            opt_technical REAL, opt_liquidity REAL, opt_asymmetry REAL
        );
        """
    )

    tickers = [f"T{i:02d}" for i in range(N_TICKERS)]
    # 2026-03-02 is a Monday; step weekdays only so every row is a US weekday.
    from datetime import date, timedelta
    d = date(2026, 3, 2)
    days = []
    while len(days) < N_DAYS:
        if d.weekday() < 5:
            days.append(d)
        d += timedelta(days=1)

    # Deterministic price paths: signal term (ordered by ti) + integer-derived
    # shock of similar magnitude, so the planted IC is strong but < 1 and varies
    # day to day. No RNG — the formula is reproducible on any platform.
    # The shock's period (29) must not divide or equal a horizon. At period 21
    # the shocks over any 21-day window sum to the same constant for every
    # ticker, the noise cancels exactly, and the 21d IC comes out at precisely
    # 1.000 with zero dispersion — a resonance artifact that silently turns the
    # fixture degenerate at exactly the horizon we care most about.
    prices = [[100.0 + ti * 2.0] for ti in range(N_TICKERS)]
    for ti in range(N_TICKERS):
        for di in range(1, N_DAYS + 30):
            signal = (ti - (N_TICKERS - 1) / 2) * 0.0012
            shock = (((ti * 37 + di * 53) % 29) - 14) * 0.012
            prices[ti].append(prices[ti][-1] * (1.0 + signal + shock))

    scan_id = 0
    row_id = 0
    for di, day in enumerate(days):
        scan_id += 1
        # Two scans per day; the LATER one carries the real values, so the
        # "last scan of the day" dedup is actually exercised rather than assumed.
        conn.execute(
            "INSERT INTO scans (id,timestamp,tickers_scanned) VALUES (?,?,?)",
            (scan_id, f"{day.isoformat()} 14:00:00", N_TICKERS),
        )
        early_scan = scan_id
        scan_id += 1
        conn.execute(
            "INSERT INTO scans (id,timestamp,tickers_scanned) VALUES (?,?,?)",
            (scan_id, f"{day.isoformat()} 21:30:00", N_TICKERS),
        )
        late_scan = scan_id

        for ti, tk in enumerate(tickers):
            # Price path: a drift set by the ticker's index PLUS a deterministic
            # per-day shock of comparable size. The shock matters — without it
            # the planted relationship is perfectly monotone, every daily IC is
            # exactly 1.0, the IC series has zero variance and the t-stat is
            # undefined. Real cross-sections are never that clean, and a fixture
            # that clean cannot exercise the SUPPORTED path at all.
            price = prices[ti][di]

            # Planted signal: ranks with the drift rate, hence with fwd return.
            valuation = float(ti * 5)
            # Sawtooth noise: cycles independently of ti's ordering.
            liquidity = float((ti * 7 + di * 3) % 41)
            constant = 50.0

            vals = {
                "lt_rule_of_40": float((ti * 3 + di) % 29),
                "lt_valuation": valuation,
                "lt_fcf_margin": float((ti * 11 + di * 5) % 37),
                "lt_trend": float((ti + di * 2) % 23),
                "lt_earnings_quality": float((ti * 13) % 31),
                "lt_discount_momentum": float((ti * 17 + di) % 19),
                "opt_earnings_catalyst": float((ti * 2 + di * 7) % 43),
                "opt_iv_context": float((ti * 19 + di) % 27),
                "opt_directional": float((ti * 23 + di * 11) % 33),
                "opt_technical": float((ti * 29 + di * 13) % 47),
                "opt_liquidity": liquidity,
                "opt_asymmetry": float((ti * 31 + di * 17) % 53),
            }
            if constant_component:
                vals[constant_component] = constant

            lt = sum(vals[c] for c in vals if c.startswith("lt_")) / 6.0
            opt = sum(vals[c] for c in vals if c.startswith("opt_")) / 6.0

            for sid, factor in ((early_scan, 0.5), (late_scan, 1.0)):
                row_id += 1
                cols = ["id", "scan_id", "ticker", "price", "lt_score", "opt_score"] + list(vals)
                # The early scan carries deliberately wrong values; if dedup ever
                # picks it, the golden numbers move and this test fails.
                payload = [row_id, sid, tk, price * factor, lt * factor, opt * factor] + [
                    v * factor for v in vals.values()
                ]
                conn.execute(
                    f"INSERT INTO scores ({','.join(cols)}) "
                    f"VALUES ({','.join('?' * len(cols))})",
                    payload,
                )
    conn.commit()
    conn.close()


@pytest.fixture
def fixture_db(tmp_path):
    p = tmp_path / "fixture.db"
    _build_fixture_db(p)
    return p


# ─────────────────────────────────────────────────────────────────────────────
# 1. Golden output
# ─────────────────────────────────────────────────────────────────────────────
def _round(v):
    return None if v != v else round(float(v), 9)  # NaN -> None


def _compute_golden(db: Path):
    panel = load_panel(str(db), window_days=365, asof=None)
    results = run_analysis(panel, (5, 21))
    return {
        "panel": {
            "n_rows": int(len(panel)),
            "n_days": int(panel["date"].nunique()),
            "n_tickers": int(panel["ticker"].nunique()),
        },
        "results": {
            f"{r.series}@{r.horizon}": {
                "n_days": r.n_days, "mean_ic": _round(r.mean_ic),
                "t_adj": _round(r.t_adj), "ic_h1": _round(r.ic_h1),
                "ic_h2": _round(r.ic_h2), "same_sign": r.same_sign,
                "verdict": r.verdict,
            }
            for r in results
        },
    }


def test_ic_golden_matches(fixture_db):
    computed = _compute_golden(fixture_db)
    if os.environ.get("UPDATE_IC_GOLDEN"):
        GOLDEN.write_text(json.dumps(computed, indent=2, sort_keys=True) + "\n")
        pytest.skip("IC golden regenerated — review and commit the diff")
    assert GOLDEN.exists(), "fixtures/ic_golden.json missing — UPDATE_IC_GOLDEN=1"
    golden = json.loads(GOLDEN.read_text())
    assert computed == golden, (
        "IC harness output drifted from the golden file. If the methodology "
        "change was INTENTIONAL, regenerate with UPDATE_IC_GOLDEN=1 and commit "
        "the reviewed diff. If not, you just caught silent drift in a report "
        "that is supposed to be comparable week over week."
    )


def test_ic_is_deterministic(fixture_db):
    """Same DB, same numbers — twice, no hidden state, no clock dependence."""
    assert _compute_golden(fixture_db) == _compute_golden(fixture_db)


def test_planted_signal_is_detected(fixture_db):
    """
    The fixture plants a real relationship in lt_valuation and pure noise in
    opt_liquidity. If the harness cannot tell them apart, the golden file is
    just pinning a bug.
    """
    panel = load_panel(str(fixture_db), window_days=365)
    fwd = forward_returns(panel, (5,))[5]
    planted = daily_ic(panel, fwd, "lt_valuation", 5)
    noise = daily_ic(panel, fwd, "opt_liquidity", 5)
    assert planted.mean() > 0.08, f"planted signal not recovered: {planted.mean()}"
    assert planted.std() > 0, "planted IC has no dispersion — fixture is degenerate"
    assert abs(noise.mean()) < planted.mean(), "noise column outranked the planted signal"


def test_supported_verdict_can_actually_fire(fixture_db):
    """
    The SUPPORTED label must be reachable. A verdict that never fires in any
    test is decoration (OPERATIONS_PLAYBOOK 9b) — and SUPPORTED is the one label
    that would nominate a component for promotion, so it is the one that most
    needs to be exercised rather than assumed.
    """
    panel = load_panel(str(fixture_db), window_days=365)
    results = {f"{r.series}@{r.horizon}": r for r in run_analysis(panel, (5, 21))}
    r = results["lt_valuation@21"]
    assert r.verdict == "SUPPORTED", (
        f"planted signal did not clear the bar: t_adj={r.t_adj}, "
        f"H1={r.ic_h1}, H2={r.ic_h2}")
    assert r.same_sign and abs(r.t_adj) >= 3.0
    # Same planted series at 5d does NOT clear the bar — the drift needs the
    # longer horizon to outgrow the shock. Both labels exercised on one column.
    assert results["lt_valuation@5"].verdict == "noise"


def test_hypothesis_count_is_thirty(fixture_db):
    """15 series x 2 horizons — the count the interim analysis reported."""
    panel = load_panel(str(fixture_db), window_days=365)
    assert len(SERIES) == 15
    assert len(run_analysis(panel, (5, 21))) == 30


def test_last_scan_of_day_wins(fixture_db):
    """
    Dedup must keep the LAST scan of each market day (prereg), not the first.
    The fixture's early scan carries half-values, so picking it would halve the
    panel's prices.
    """
    panel = load_panel(str(fixture_db), window_days=365)
    assert len(panel) == N_TICKERS * N_DAYS
    row = panel[(panel["ticker"] == "T05")].sort_values("date").iloc[0]
    assert row["lt_valuation"] == pytest.approx(25.0), "took the early (half-value) scan"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Read-only proof
# ─────────────────────────────────────────────────────────────────────────────
def test_harness_connection_cannot_write(fixture_db):
    """The harness reads through connect_ro; writes must fail at the sqlite layer."""
    from db.ro import connect_ro
    conn = connect_ro(str(fixture_db))
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only|query_only"):
            conn.execute("INSERT INTO scores (ticker, price) VALUES ('EVIL', 1.0)")
            conn.commit()
    finally:
        conn.close()


def test_harness_run_does_not_mutate_the_db(fixture_db, tmp_path):
    """Belt and braces: the input file is byte-identical after a full run."""
    import hashlib
    before = hashlib.sha256(fixture_db.read_bytes()).hexdigest()
    generate(str(fixture_db), tmp_path / "out", 365, (5, 21))
    after = hashlib.sha256(fixture_db.read_bytes()).hexdigest()
    assert before == after, "the harness modified its input database"


def test_read_door_is_r1s_actual_function_not_a_copy():
    """
    The harness must use api/db/ro.py itself. Loading it by path is only
    acceptable because it is literally the same file — a reimplementation would
    be two read doors, and one of them would eventually stop being read-only.
    """
    import inspect
    import research.harness.ic_report as ic
    assert Path(inspect.getsourcefile(ic.connect_ro)).resolve() == \
        (REPO_ROOT / "api" / "db" / "ro.py").resolve()
    assert ic.RO_PATH.exists()


def test_harness_does_not_import_the_write_path_module_at_runtime():
    """
    research/README.md rule 3, enforced at RUNTIME rather than by grepping source.

    `from db.ro import connect_ro` would execute api/db/__init__.py, which
    imports db.models — the module holding save_scan/log_play/close_play. A
    static text check cannot see that; this can.
    """
    import subprocess
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(REPO_ROOT)!r});"
        "import research.harness.ic_report;"
        "bad=[m for m in sys.modules if m=='db.models' or m.endswith('.db.models')];"
        "print('LEAKED:'+','.join(bad) if bad else 'CLEAN')"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "CLEAN" in out.stdout, out.stdout


def test_ic_report_does_not_import_write_paths():
    """research/ rule 3 — no write path one typo away from the collected data."""
    import ast
    path = REPO_ROOT / "research" / "harness" / "ic_report.py"
    src = path.read_text()

    # Parse rather than grep: the module's comments legitimately DISCUSS
    # db.models and sqlite3.connect (explaining why it avoids both), and a text
    # match cannot tell prose from code. The AST can.
    imported = set()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            imported.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
            imported.update(f"{node.module}.{a.name}" for a in node.names)
    assert not any(m == "db.models" or m.startswith("db.models.") or
                   m.endswith(".db.models") for m in imported), imported

    # A hand-rolled door would be a CALL to sqlite3.connect.
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
             and n.func.attr == "connect"
             and isinstance(n.func.value, ast.Name) and n.func.value.id == "sqlite3"]
    assert not calls, "research/ must use connect_ro, not its own sqlite3.connect"
    assert "connect_ro" in src


# ─────────────────────────────────────────────────────────────────────────────
# 3. Append-only proof
# ─────────────────────────────────────────────────────────────────────────────
def test_second_run_does_not_touch_the_first(fixture_db, tmp_path):
    """
    Two runs, two file pairs, first pair byte-identical afterwards.

    This is the property the weekly job depends on: the report series IS the
    deliverable, so a run that overwrites its predecessor silently destroys the
    decay history the harness exists to expose.
    """
    out = tmp_path / "reports"
    first = generate(str(fixture_db), out, 365, (5, 21))
    md1, csv1 = Path(first["md"]), Path(first["csv"])
    md1_bytes, csv1_bytes = md1.read_bytes(), csv1.read_bytes()

    second = generate(str(fixture_db), out, 365, (5, 21))
    md2, csv2 = Path(second["md"]), Path(second["csv"])

    assert md2 != md1 and csv2 != csv1, "second run reused the first run's paths"
    assert md1.exists() and csv1.exists(), "second run deleted the first run's files"
    assert md1.read_bytes() == md1_bytes, "second run modified the first markdown"
    assert csv1.read_bytes() == csv1_bytes, "second run modified the first CSV"
    assert len(list(out.glob("ic-report-*.csv"))) == 2


def test_third_run_keeps_incrementing(fixture_db, tmp_path):
    out = tmp_path / "reports"
    for _ in range(3):
        generate(str(fixture_db), out, 365, (5, 21))
    assert len(list(out.glob("ic-report-*.csv"))) == 3
    assert len(list(out.glob("ic-report-*.md"))) == 3


def test_delta_paragraph_reports_no_change_on_identical_rerun(fixture_db, tmp_path):
    out = tmp_path / "reports"
    generate(str(fixture_db), out, 365, (5, 21))
    second = generate(str(fixture_db), out, 365, (5, 21))
    assert "No verdict changes and no IC sign flips" in second["delta"]


def test_delta_paragraph_names_a_verdict_change(fixture_db, tmp_path):
    """A changed verdict must actually surface in the Pushover paragraph."""
    import pandas as pd
    out = tmp_path / "reports"
    first = generate(str(fixture_db), out, 365, (5, 21))
    df = first["results"].copy()
    # Rewrite the previous CSV so the next run sees a genuine verdict move.
    df.loc[df["series"] == "lt_valuation", "verdict"] = "SUPPORTED"
    df.loc[df["series"] == "lt_valuation", "mean_ic"] = -0.5
    pd.DataFrame(df).to_csv(first["csv"], index=False)
    second = generate(str(fixture_db), out, 365, (5, 21))
    assert "lt_valuation" in second["delta"]
    assert "SUPPORTED->" in second["delta"] or "sign flips" in second["delta"]


# ─────────────────────────────────────────────────────────────────────────────
# 4. Degenerate input
# ─────────────────────────────────────────────────────────────────────────────
def test_constant_component_reports_insufficient(tmp_path):
    """
    A constant column has no ranks, so it has no IC. The harness must say
    INSUFFICIENT — not crash, and above all not fabricate a correlation.
    """
    db = tmp_path / "constant.db"
    _build_fixture_db(db, constant_component="opt_asymmetry")
    panel = load_panel(str(db), window_days=365)
    results = {f"{r.series}@{r.horizon}": r for r in run_analysis(panel, (5, 21))}

    for h in (5, 21):
        r = results[f"opt_asymmetry@{h}"]
        assert r.verdict == "INSUFFICIENT", f"constant column got verdict {r.verdict}"
        assert r.mean_ic != r.mean_ic or r.n_days == 0, "fabricated an IC for a constant column"

    # The rest of the report must still be produced — one dead column does not
    # take the run down.
    assert results["lt_valuation@21"].verdict in {"SUPPORTED", "noise"}


def test_empty_panel_does_not_crash(tmp_path):
    """A window with no data yields no results rather than an exception."""
    db = tmp_path / "empty.db"
    _build_fixture_db(db)
    panel = load_panel(str(db), window_days=365, asof="2020-01-01")
    assert panel.empty
    assert run_analysis(panel, (5, 21)) == []


def test_missing_column_reports_insufficient(tmp_path):
    """An older DB missing a component must not take the whole report down."""
    db = tmp_path / "nocol.db"
    _build_fixture_db(db)
    panel = load_panel(str(db), window_days=365).drop(columns=["opt_iv_context"])
    results = {f"{r.series}@{r.horizon}": r for r in run_analysis(panel, (5, 21))}
    assert results["opt_iv_context@5"].verdict == "INSUFFICIENT"
    assert "column absent" in results["opt_iv_context@5"].note


def test_short_window_reports_insufficient(fixture_db):
    """Too few usable IC days must read INSUFFICIENT, not a confident number."""
    panel = load_panel(str(fixture_db), window_days=20)
    for r in run_analysis(panel, (21,)):
        assert r.verdict == "INSUFFICIENT"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Notification + staged scheduling
# ─────────────────────────────────────────────────────────────────────────────
def test_pushover_reports_not_accepted_without_keys(monkeypatch, capsys):
    """No keys must read as NOT ACCEPTED, never as a silent success."""
    import research.harness.ic_report as ic
    monkeypatch.delenv("PUSHOVER_TOKEN", raising=False)
    monkeypatch.delenv("PUSHOVER_USER", raising=False)
    assert ic.send_pushover("hello") is False


def test_pushover_reports_not_accepted_on_transport_failure(monkeypatch):
    """
    A dead network must return False, not raise and not report success.
    OPERATIONS_PLAYBOOK 9b: the alert whose response is discarded.
    """
    import research.harness.ic_report as ic
    monkeypatch.setenv("PUSHOVER_TOKEN", "t")
    monkeypatch.setenv("PUSHOVER_USER", "u")

    def boom(*a, **k):
        raise OSError("network unreachable")

    monkeypatch.setattr("urllib.request.urlopen", boom)
    assert ic.send_pushover("hello") is False


def test_pushover_accepted_on_200(monkeypatch):
    import research.harness.ic_report as ic
    monkeypatch.setenv("PUSHOVER_TOKEN", "t")
    monkeypatch.setenv("PUSHOVER_USER", "u")

    class Resp:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *a): return False

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: Resp())
    assert ic.send_pushover("hello") is True


def test_tearsheet_absent_alphalens_skips_without_failing(fixture_db, tmp_path, monkeypatch):
    """
    alphalens is enrichment; the native report is the contract. A missing
    library must log why and leave the real outputs intact — never fail the run.
    """
    import builtins
    import research.harness.ic_report as ic

    real_import = builtins.__import__

    def no_alphalens(name, *a, **k):
        if name.startswith("alphalens"):
            raise ModuleNotFoundError("No module named 'alphalens'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", no_alphalens)
    note = ic.write_tearsheet(load_panel(str(fixture_db), 365), tmp_path, "stem", (5, 21))
    assert "not available" in note and "skipped" in note

    # And the full run still produces its md+csv with --tearsheet requested.
    out = ic.generate(str(fixture_db), tmp_path / "r", 365, (5, 21), tearsheet=True)
    assert Path(out["md"]).exists() and Path(out["csv"]).exists()


def test_staged_plist_is_not_loaded_and_is_well_formed():
    """
    The plist must exist in the repo, name the 18:30 Sunday slot, and — the part
    that matters — never be installed by a code session. Loading launchd jobs is
    a supervised human step.
    """
    import plistlib
    p = REPO_ROOT / "scripts" / "mill" / "com.mill.cs-ic-report.plist"
    assert p.exists(), "staged plist missing"
    d = plistlib.loads(p.read_bytes())
    assert d["Label"] == "com.mill.cs-ic-report"
    cal = d["StartCalendarInterval"]
    assert (cal["Weekday"], cal["Hour"], cal["Minute"]) == (0, 18, 30), (
        "must run Sundays 18:30, after the 18:00 gate read")
    assert not (Path.home() / "Library" / "LaunchAgents" /
                "com.mill.cs-ic-report.plist").exists(), (
        "the plist was INSTALLED — staging means staged")


def test_mill_wrapper_is_executable_and_read_only_by_construction():
    sh = REPO_ROOT / "scripts" / "mill" / "ic_report_weekly.sh"
    assert sh.exists() and os.access(sh, os.X_OK), "wrapper missing or not executable"
    src = sh.read_text()
    assert "research.harness.ic_report" in src
    assert "--pushover" in src
    # No droplet, no service management, anywhere in the weekly job.
    for forbidden in ("ssh ", "scp ", "systemctl", "rsync", "deploy.sh"):
        assert forbidden not in src, f"weekly job must not run {forbidden!r}"


def test_window_midpoint_splits_the_window_not_the_ic_series(fixture_db):
    """
    Regression guard on the split definition.

    The prereg says "window split at its midpoint". Splitting the IC series
    instead moves the boundary ~`horizon` days early and changes the half-means
    — on the real 2026-08-04 window it flipped lt_valuation's H1 sign and
    therefore its both-halves verdict. Verified against the published interim
    table before pinning.
    """
    panel = load_panel(str(fixture_db), window_days=365)
    mid = window_midpoint(panel)
    assert mid == panel["date"].min() + (panel["date"].max() - panel["date"].min()) / 2

    fwd = forward_returns(panel, (21,))[21]
    ics = daily_ic(panel, fwd, "lt_valuation", 21)
    # The IC series stops `horizon` days short of the window end, so the window
    # midpoint must sit strictly later than the IC series' own midpoint.
    assert ics.index.max() < panel["date"].max()
    assert mid > ics.index[len(ics) // 2]
