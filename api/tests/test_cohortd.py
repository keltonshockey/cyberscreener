"""
Tests for research/cohortd/ — the cohort D paper logger.

The brief names five things to pin, and each maps to a way this lane could log
years of data that turn out to mean nothing:

  1. ENTRY-RULE BOUNDARY — 1.9 vol points must NOT enter, 2.0 must. The threshold
     is registered and the code may not soften it.
  2. CONDOR SETTLEMENT SIGN SWEEP — inside the shorts, beyond each wing, and
     between short and wing on both sides. Settlement math that is wrong in one
     region produces a plausible-looking record that is silently false.
  3. DEDUP ON RE-RUN — a daily job that double-logs a cycle corrupts n, and n is
     what every verdict in the prereg is gated on.
  4. APPEND-ONLY — a re-run must never modify a recorded value.
  5. HAR-RV REGRESSION — fixed series, fixed numbers, so a silent change to the
     forecast (which gates every entry) fails loudly.

Plus the isolation contract, which is the one that cannot be checked by reading:
this lane must import NOTHING from `api/` and must never name `cyberscreener.db`.
"""

import ast
import datetime as dt
import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))

from research.cohortd import condor as cd  # noqa: E402
from research.cohortd import harrv, logger, metrics, store  # noqa: E402

COHORTD = REPO_ROOT / "research" / "cohortd"


# ─────────────────────────────────────────────────────────────────────────────
# Deterministic fixtures — no RNG, no clock, no network
# ─────────────────────────────────────────────────────────────────────────────
def synthetic_closes(n=400, start=100.0, amp=0.008):
    """
    Deterministic price path with a stable, non-degenerate volatility.

    Integer-derived so the HAR regression values are reproducible on any
    platform; the alternating component keeps realized variance positive
    (a constant series would make RV zero and the forecast meaningless).
    """
    closes, px = [], start
    for i in range(n):
        step = amp * (1 if i % 2 == 0 else -1) * (1.0 + (i % 7) / 10.0)
        px *= (1.0 + step)
        closes.append(px)
    return closes


def condor_fixture(credit=2.0):
    """A symmetric 10-wide condor: 380/390 puts, 420/430 calls."""
    return cd.Condor(expiry="2026-09-18", dte=37, short_put=390.0, long_put=380.0,
                     short_call=420.0, long_call=430.0, credit=credit,
                     put_width=10.0, call_width=10.0)


def chain_fixture(spot=405.0):
    """Chain rows spanning both wings with plausible deltas and two-sided quotes."""
    puts, calls = [], []
    for k in range(370, 411, 5):
        moneyness = (spot - k) / spot
        delta = -max(0.01, 0.5 - moneyness * 6)
        # Put premium RISES with strike: a lower strike is further OTM and
        # cheaper. Pricing it the other way round makes the short leg cheaper
        # than the long wing, the net credit negative, and `build_condor`
        # correctly refuses to build — which is how the first cut of this
        # fixture failed.
        puts.append({"strike": float(k), "bid": 1.0 + (k - 365) * 0.05,
                     "ask": 1.2 + (k - 365) * 0.05, "impliedVolatility": 0.18,
                     "delta": delta})
    for k in range(400, 441, 5):
        moneyness = (k - spot) / spot
        delta = max(0.01, 0.5 - moneyness * 6)
        calls.append({"strike": float(k), "bid": 1.0 + (440 - k) * 0.05,
                      "ask": 1.2 + (440 - k) * 0.05, "impliedVolatility": 0.18,
                      "delta": delta})
    return puts, calls


# ─────────────────────────────────────────────────────────────────────────────
# 1. Entry-rule boundary — the registered threshold
# ─────────────────────────────────────────────────────────────────────────────
def test_entry_threshold_is_the_registered_two_points():
    assert logger.ENTRY_THRESHOLD_VOL_POINTS == 2.0


@pytest.mark.parametrize("spread,expected", [
    (1.9, "SKIP"),      # the brief's explicit boundary cases
    (2.0, "ENTER"),
    (1.99, "SKIP"),
    (2.01, "ENTER"),
    (5.0, "ENTER"),
    (-3.0, "SKIP"),
])
def test_entry_rule_boundary(monkeypatch, spread, expected):
    """1.9 does not enter, 2.0 does. The rule is `>=`, fixed at registration."""
    monkeypatch.setattr(harrv, "forecast_har",
                        lambda closes: {"ok": True, "forecast_vol_points": 15.0,
                                        "rv_d": 1, "rv_w": 1, "rv_m": 1, "clamped": False})
    monkeypatch.setattr(harrv, "forecast_garch", lambda closes: {"ok": False, "reason": "x"})
    out = logger.evaluate_entry([1.0], 15.0 + spread)
    assert out["decision"] == expected
    assert out["spread"] == pytest.approx(spread)


def test_skipped_cycles_still_record_their_values():
    """A rejection with no recorded inputs cannot be audited later (PREREG §5)."""
    closes = synthetic_closes()
    out = logger.evaluate_entry(closes, 5.0)      # far below any plausible forecast
    assert out["decision"] == "SKIP"
    assert out["iv30"] == 5.0
    assert out["har_forecast"] is not None
    assert out["spread"] is not None
    assert "reason" in out


def test_har_failure_forces_skip_not_entry():
    """No forecast means no entry — never a default-open."""
    out = logger.evaluate_entry([100.0, 101.0], 99.0)
    assert out["decision"] == "SKIP"
    assert out["har_ok"] is False


# ─────────────────────────────────────────────────────────────────────────────
# 2. Condor settlement sign sweep
# ─────────────────────────────────────────────────────────────────────────────
def test_settle_inside_shorts_is_max_win():
    c = condor_fixture()
    for S in (400.0, 391.0, 419.0, 405.0):
        s = cd.settle(c, S)
        assert s["pnl"] == pytest.approx(c.credit)
        assert s["win"] is True
        assert s["r_multiple"] == pytest.approx(c.credit / c.defined_risk)


def test_settle_beyond_put_wing_is_capped_max_loss():
    c = condor_fixture()
    for S in (380.0, 350.0, 0.01):
        s = cd.settle(c, S)
        assert s["pnl"] == pytest.approx(c.credit - c.put_width)
        assert s["win"] is False
        assert s["pnl"] == pytest.approx(-c.defined_risk)


def test_settle_beyond_call_wing_is_capped_max_loss():
    c = condor_fixture()
    for S in (430.0, 500.0, 10_000.0):
        s = cd.settle(c, S)
        assert s["pnl"] == pytest.approx(c.credit - c.call_width)
        assert s["pnl"] == pytest.approx(-c.defined_risk)


def test_settle_between_short_and_wing_is_partial_loss():
    c = condor_fixture()
    put_side = cd.settle(c, 385.0)          # 5 into a 10-wide put spread
    assert put_side["put_side_loss"] == pytest.approx(5.0)
    assert put_side["pnl"] == pytest.approx(c.credit - 5.0)
    assert -c.defined_risk < put_side["pnl"] < c.credit

    call_side = cd.settle(c, 425.0)
    assert call_side["call_side_loss"] == pytest.approx(5.0)
    assert call_side["pnl"] == pytest.approx(c.credit - 5.0)


def test_settle_is_monotone_and_never_exceeds_defined_risk():
    """Sweep the whole line: loss is bounded, and only one side can be in play."""
    c = condor_fixture()
    for S in [x / 2 for x in range(700, 900)]:
        s = cd.settle(c, S)
        assert s["pnl"] <= c.credit + 1e-9
        assert s["pnl"] >= -c.defined_risk - 1e-9
        assert not (s["put_side_loss"] > 0 and s["call_side_loss"] > 0)


def test_win_flag_matches_sign_of_pnl():
    """`win` is strictly `pnl > 0`, so breakeven is NOT a win."""
    c = condor_fixture(credit=2.0)
    assert cd.settle(c, 405.0)["win"] is True           # max win
    assert cd.settle(c, 389.0)["win"] is True           # 1 loss vs 2 credit -> +1
    assert cd.settle(c, 388.0)["pnl"] == pytest.approx(0.0)
    assert cd.settle(c, 388.0)["win"] is False          # exact breakeven is not a win
    assert cd.settle(c, 387.0)["win"] is False


def test_defined_risk_is_width_minus_credit():
    c = condor_fixture(credit=2.5)
    assert c.defined_risk == pytest.approx(10.0 - 2.5)


# ─────────────────────────────────────────────────────────────────────────────
# 2b. Structure selection
# ─────────────────────────────────────────────────────────────────────────────
def test_expiry_choice_prefers_37_dte_within_30_45():
    assert cd.choose_expiry({"a": 20, "b": 31, "c": 37, "d": 44, "e": 60}) == "c"
    assert cd.choose_expiry({"a": 31, "b": 44}) == "a"          # 31 is nearer 37
    assert cd.choose_expiry({"a": 20, "b": 60}) is None         # nothing in window


def test_condor_legs_are_ordered_and_priced():
    puts, calls = chain_fixture()
    c = cd.build_condor(405.0, "2026-09-18", 37, puts, calls)
    assert c is not None
    assert c.long_put < c.short_put < c.short_call < c.long_call
    assert c.credit > 0 and c.defined_risk > 0


def test_condor_rejects_one_sided_quotes():
    """A leg without a two-sided market is unusable; no partial condor is logged."""
    puts, calls = chain_fixture()
    for r in puts:
        r["bid"] = 0
    assert cd.build_condor(405.0, "2026-09-18", 37, puts, calls) is None


def test_bs_delta_fallback_when_chain_has_none():
    puts, calls = chain_fixture()
    for r in puts + calls:
        r.pop("delta", None)
    c = cd.build_condor(405.0, "2026-09-18", 37, puts, calls)
    assert c is not None, "should fall back to Black-Scholes delta"


# ─────────────────────────────────────────────────────────────────────────────
# 3 & 4. Dedup and append-only
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def db(tmp_path):
    return store.connect(str(tmp_path / "cohortD.db"))


def _row(date="2026-09-01", decision="ENTER"):
    c = condor_fixture()
    r = {"cycle_date": date, "decision": decision, "spot": 405.0, "iv30": 18.0,
         "har_forecast": 15.0, "spread": 3.0, "threshold": 2.0,
         "entered_at": "2026-09-01T13:00:00Z", "notes": "test"}
    r.update(c.as_dict())
    return r


def test_dedup_on_rerun(db):
    assert store.record_cycle(db, _row()) is True
    assert store.record_cycle(db, _row()) is False      # same date -> ignored
    assert db.execute("SELECT COUNT(*) FROM cycles").fetchone()[0] == 1


def test_rerun_cannot_modify_an_existing_row(db, tmp_path):
    store.record_cycle(db, _row())
    before = db.execute("SELECT * FROM cycles WHERE cycle_date='2026-09-01'").fetchone()
    tampered = _row()
    tampered.update(credit=99.0, spot=1.0, notes="TAMPERED")
    store.record_cycle(db, tampered)
    after = db.execute("SELECT * FROM cycles WHERE cycle_date='2026-09-01'").fetchone()
    assert dict(after) == dict(before), "a re-run modified a recorded row"


def test_settlement_fills_only_once(db):
    store.record_cycle(db, _row())
    s1 = cd.settle(condor_fixture(), 405.0)
    assert store.settle_cycle(db, "2026-09-01", s1, "2026-10-18T20:00:00Z") is True
    s2 = cd.settle(condor_fixture(), 300.0)             # would be a max loss
    assert store.settle_cycle(db, "2026-09-01", s2, "2026-10-19T20:00:00Z") is False
    row = db.execute("SELECT * FROM cycles").fetchone()
    assert row["pnl"] == pytest.approx(s1["pnl"]), "settlement was overwritten"


def test_database_bytes_unchanged_by_a_full_rerun(db, tmp_path):
    """Append-only, proven on the file itself rather than asserted."""
    path = tmp_path / "cohortD.db"
    store.record_cycle(db, _row())
    store.settle_cycle(db, "2026-09-01", cd.settle(condor_fixture(), 405.0), "2026-10-18Z")
    db.commit()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()

    for _ in range(3):                                   # simulate repeated daily runs
        store.record_cycle(db, _row())
        store.settle_cycle(db, "2026-09-01", cd.settle(condor_fixture(), 300.0), "2026-10-20Z")
    db.commit()
    assert hashlib.sha256(path.read_bytes()).hexdigest() == digest


def test_skips_are_recorded_and_counted(db):
    store.record_cycle(db, _row("2026-09-01", "SKIP"))
    store.record_cycle(db, _row("2026-10-01", "ENTER"))
    c = store.counts(db)
    assert c["cycles"] == 2 and c["skipped"] == 1 and c["entered"] == 1


def test_open_positions_only_returns_expired_unsettled(db):
    store.record_cycle(db, _row("2026-09-01"))           # expiry 2026-09-18
    assert store.open_positions(db, "2026-09-17") == []
    assert len(store.open_positions(db, "2026-09-18")) == 1


# ─────────────────────────────────────────────────────────────────────────────
# 5. HAR-RV regression values on a fixed series
# ─────────────────────────────────────────────────────────────────────────────
def test_harrv_regression_on_fixed_series():
    """
    Pinned numbers on a deterministic series. The forecast gates every entry, so
    a silent change to it must fail loudly rather than quietly re-tune the lane.
    """
    out = harrv.forecast_har(synthetic_closes())
    assert out["ok"] is True
    assert out["forecast_vol_points"] == pytest.approx(16.7030, abs=1e-3)
    assert out["rv_d"] == pytest.approx(12.7507, abs=1e-3)
    assert out["rv_w"] == pytest.approx(17.4674, abs=1e-3)
    assert out["rv_m"] == pytest.approx(16.5407, abs=1e-3)
    assert out["clamped"] is False


def test_harrv_is_deterministic():
    a = harrv.forecast_har(synthetic_closes())
    b = harrv.forecast_har(synthetic_closes())
    assert a["forecast_vol_points"] == b["forecast_vol_points"]


def test_harrv_refuses_short_history():
    assert harrv.forecast_har([100.0, 101.0, 102.0])["ok"] is False


def test_harrv_never_forecasts_below_the_variance_floor():
    """
    A clamped-to-zero forecast would inflate IV-minus-forecast and manufacture an
    entry — the failure direction that costs money.
    """
    out = harrv.forecast_har(synthetic_closes())
    assert out["forecast_vol_points"] > 0


def test_annualization_is_252_day():
    assert harrv.annualize_variance(0.0) == 0.0
    daily_var = (0.01) ** 2
    assert harrv.annualize_variance(daily_var) == pytest.approx(15.8745, abs=1e-3)


# ─────────────────────────────────────────────────────────────────────────────
# Metrics — the registered statistics and verdict caps
# ─────────────────────────────────────────────────────────────────────────────
def test_wilson_interval_brackets_the_point_estimate():
    lo, hi = metrics.wilson_interval(13, 15)
    assert lo < 13 / 15 < hi
    assert 0 <= lo and hi <= 1
    # The interval must be wide at n=15 — this is the 14/16 lesson in numbers.
    assert hi - lo > 0.3


def test_verdict_is_capped_below_100_cycles():
    rows = [{"r_multiple": 0.5} for _ in range(99)]
    m = metrics.summarize(rows)
    assert m["verdict"].startswith("DIRECTIONAL")
    assert "no verdict permitted" in m["verdict"]


def test_fail_stop_triggers_only_at_n30_with_ci_below_zero():
    losing = [{"r_multiple": -0.9} for _ in range(35)]
    m = metrics.summarize(losing)
    assert m["fail_stop_armed"] is True
    assert m["fail_stop_triggered"] is True
    assert m["verdict"].startswith("FAIL-STOP")

    few = [{"r_multiple": -0.9} for _ in range(29)]
    assert metrics.summarize(few)["fail_stop_triggered"] is False


def test_high_win_rate_alone_is_not_a_pass():
    """
    PREREG §9: the exact error our own 14/16 made. 90% wins with a fat tail and
    no alpha regression must NOT read as a pass.
    """
    rows = [{"r_multiple": 0.3} for _ in range(108)] + [{"r_multiple": -4.0} for _ in range(12)]
    m = metrics.summarize(rows)
    assert m["win_rate"] == pytest.approx(0.9)
    assert "PASS" not in m["verdict"]
    assert m["verdict"].startswith("H0 NOT REJECTED")


def test_alpha_regression_recovers_a_planted_relationship():
    spy = [(i % 21 - 10) / 100.0 for i in range(120)]
    y = [0.02 + 1.5 * s for s in spy]                 # alpha 0.02, beta 1.5, no noise
    fit = metrics.ols_alpha_beta(y, spy)
    assert fit["alpha"] == pytest.approx(0.02, abs=1e-9)
    assert fit["beta"] == pytest.approx(1.5, abs=1e-9)


def test_max_drawdown_and_profit_factor():
    assert metrics.max_drawdown([1.0, -0.5, -0.5, 1.0]) == pytest.approx(-1.0)
    assert metrics.profit_factor([2.0, -1.0]) == pytest.approx(2.0)


# ─────────────────────────────────────────────────────────────────────────────
# Isolation — the contract that cannot be verified by reading
# ─────────────────────────────────────────────────────────────────────────────
def test_cohortd_imports_nothing_from_api():
    """
    PREREG §11 / brief: this lane imports NOTHING from `api/`.

    AST-parsed rather than grepped: the modules legitimately DISCUSS api/ and
    db.models in comments explaining why they avoid them, and a text match
    cannot tell prose from an import.
    """
    offenders = {}
    for path in sorted(COHORTD.glob("*.py")):
        names = set()
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.Import):
                names.update(a.name for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module)
        bad = [n for n in names
               if n == "api" or n.startswith("api.")
               or n in {"db", "core", "jobs"} or n.startswith(("db.", "core.", "jobs."))]
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"research/cohortd/ imported application modules: {offenders}"


def test_cohortd_never_names_the_application_database():
    """
    Full isolation: not even read-only.

    Checked against string literals in CODE, not raw text. These modules
    legitimately explain in comments and docstrings that they never open
    `cyberscreener.db`, and a plain text match cannot tell an explanation from a
    path — the same prose-versus-code trap R2 and R3 both hit.
    """
    offenders = {}
    for path in sorted(COHORTD.glob("*.py")):
        tree = ast.parse(path.read_text())
        docstrings = set()
        for node in ast.walk(tree):
            if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                ds = ast.get_docstring(node, clean=False)
                if ds:
                    docstrings.add(ds)
        bad = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Constant) and isinstance(n.value, str)
               and "cyberscreener.db" in n.value and n.value not in docstrings]
        if bad:
            offenders[path.name] = bad
    assert not offenders, f"cyberscreener.db appears in CODE: {offenders}"


def test_cohortd_is_importable_without_the_api_package(tmp_path):
    """
    Import the module set in a subprocess and assert no `api` module was loaded.

    A static check cannot see a transitive import; this can.
    """
    import subprocess
    code = (
        "import sys;"
        f"sys.path.insert(0, {str(REPO_ROOT)!r});"
        "import research.cohortd.logger;"
        "bad=[m for m in sys.modules if m=='api' or m.startswith('api.') "
        "or m in ('db','core') or m.startswith(('db.','core.'))];"
        "print('LEAKED:'+','.join(bad) if bad else 'CLEAN')"
    )
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert "CLEAN" in out.stdout, out.stdout


def test_storage_path_is_the_new_research_db():
    assert store.DEFAULT_DB == "~/cs-research/cohortD.db"
    assert "cs-research" in store.db_path()


# ─────────────────────────────────────────────────────────────────────────────
# Calendar behaviour + staged plist
# ─────────────────────────────────────────────────────────────────────────────
def test_first_trading_day_skips_weekends():
    assert logger.is_first_trading_day(dt.date(2026, 6, 1)) is True    # Monday
    assert logger.is_first_trading_day(dt.date(2026, 6, 2)) is False
    # 2026-08-01 is a Saturday; the first trading day is Monday the 3rd.
    assert logger.is_first_trading_day(dt.date(2026, 8, 1)) is False
    assert logger.is_first_trading_day(dt.date(2026, 8, 3)) is True


def test_staged_plist_is_well_formed_and_not_installed():
    import plistlib
    p = REPO_ROOT / "scripts" / "mill" / "com.mill.cs-cohortd.plist"
    assert p.exists(), "staged plist missing"
    d = plistlib.loads(p.read_bytes())
    assert d["Label"] == "com.mill.cs-cohortd"
    assert not (Path.home() / "Library" / "LaunchAgents"
                / "com.mill.cs-cohortd.plist").exists(), "the plist was INSTALLED"


def test_mill_wrapper_touches_no_service_and_no_droplet():
    sh = REPO_ROOT / "scripts" / "mill" / "cohortd_daily.sh"
    assert sh.exists()
    # Comment lines are stripped: the header legitimately DESCRIBES the isolation
    # ("never opens cyberscreener.db"), and forbidding the word outright would
    # fail the file for documenting the very property under test.
    code = "\n".join(ln for ln in sh.read_text().splitlines()
                     if not ln.lstrip().startswith("#"))
    for forbidden in ("systemctl", "deploy.sh", "cyberscreener.db",
                      "launchctl load", "ssh ", "scp "):
        assert forbidden not in code, f"wrapper must not run {forbidden!r}"
