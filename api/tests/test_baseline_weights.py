"""
SESSION-BASELINE-WEIGHTS — baseline vs layers scoring regime.

Locks in:
  1. Baseline MEMBERSHIP is exactly the pre-registered, evidence-backed set
     (LT = Valuation, Opt = Asymmetry) — any change must be a deliberate edit
     of weights_baseline.json AND this test, per PROMOTION_CRITERIA.md.
  2. Baseline math: score = component raw x weight, NO earnings multiplier,
     no threat mutation.
  3. The legacy composite stays computable behind CYBERSCREENER_LEGACY_SCORES.
  4. set_weights (calibration) cannot steer live scoring in baseline mode.
  5. The forward-test journal stamps the score_version cohort at log time.
  6. run_scan end-to-end (offline): live scores are baseline, the legacy
     composite is preserved in breakdown _meta, and per-component point
     columns keep their reference-weight values (forward history intact).
"""
import importlib
import json
import sys
from pathlib import Path

import pytest

import core.baseline as baseline
import core.scanner as sc

FIXTURES = json.loads(
    (Path(__file__).parent / "fixtures" / "scoring_fixtures.json").read_text())
FIXTURES.pop("_doc", None)


# ── 1. membership lock ─────────────────────────────────────────────────────────

def test_baseline_membership_is_pre_registered():
    cfg = baseline.load_config()
    assert cfg["baseline"] == {"lt": {"valuation": 100}, "opt": {"asymmetry": 100}}, (
        "Baseline membership changed. This is allowed ONLY via "
        "PROMOTION_CRITERIA.md - update the criteria evidence, the config, "
        "and this test in the same reviewed PR."
    )
    assert cfg["score_version"] == "v2-baseline"


def test_every_layer_has_caption_and_evidence():
    cfg = baseline.load_config()
    for name, layer in cfg["layers"].items():
        assert layer.get("caption"), f"layer {name} missing honesty caption"
        assert layer.get("evidence"), f"layer {name} missing evidence pointer"
        assert layer.get("status"), f"layer {name} missing status"
        assert layer.get("stack") in ("lt", "opt")


def test_ref_weights_match_legacy_defaults():
    """ref_weights keep persisted component history comparable — they must
    equal the legacy default weights exactly."""
    cfg = baseline.load_config()
    assert cfg["ref_weights"]["lt"] == sc.DEFAULT_LT_WEIGHTS
    assert cfg["ref_weights"]["opt"] == sc.DEFAULT_OPT_WEIGHTS


# ── 2. baseline math ───────────────────────────────────────────────────────────

def test_baseline_lt_is_valuation_raw_times_100():
    for name, row in FIXTURES.items():
        _, _, bd = sc.score_long_term(row, weights=sc.DEFAULT_LT_WEIGHTS)
        expected = round(bd["valuation"]["raw"] * 100, 1)
        assert baseline.compute_baseline_lt(bd) == expected, name


def test_baseline_opt_is_asymmetry_raw_times_100_no_multiplier():
    """premium_seller_high_ivr has earnings in 5 days (x1.3 in the legacy
    composite) — the baseline must NOT inherit the multiplier."""
    row = FIXTURES["premium_seller_high_ivr"]
    legacy, _, bd = sc.score_options(row, weights=sc.DEFAULT_OPT_WEIGHTS)
    b = baseline.compute_baseline_opt(bd)
    assert b == round(bd["asymmetry"]["raw"] * 100, 1)
    assert bd["earnings_catalyst"]["multiplier"] == 1.3   # legacy got the boost
    assert b != legacy


def test_missing_component_reads_zero_not_high():
    """A data hole must never add baseline score."""
    assert baseline.compute_baseline_lt({}) == 0.0
    assert baseline.compute_baseline_opt({"asymmetry": {"raw": None, "max": 0}}) == 0.0


# ── 3 + 4. legacy flag and the calibration freeze ──────────────────────────────

def test_legacy_flag_flips_mode(monkeypatch):
    assert baseline.baseline_active() is True
    assert baseline.score_version() == "v2-baseline"
    monkeypatch.setenv("CYBERSCREENER_LEGACY_SCORES", "1")
    assert baseline.baseline_active() is False
    assert baseline.score_version() == "v1-legacy"


def test_set_weights_frozen_in_baseline_mode():
    before = sc.get_weights()
    sc.set_weights(lt_weights={"valuation": 1}, opt_weights={"technical": 99})
    assert sc.get_weights() == before, (
        "set_weights must be inert in baseline mode - calibration output "
        "may not steer live scoring (PROMOTION_CRITERIA.md)")


def test_set_weights_applies_in_legacy_mode(monkeypatch):
    monkeypatch.setenv("CYBERSCREENER_LEGACY_SCORES", "1")
    try:
        sc.set_weights(opt_weights={"iv_context": 29, "directional": 28,
                                    "technical": 23, "liquidity": 10,
                                    "asymmetry": 10})
        assert sum(sc.get_weights()["opt"].values()) == pytest.approx(100)
    finally:
        sc._active_lt_weights = dict(sc.DEFAULT_LT_WEIGHTS)
        sc._active_opt_weights = dict(sc.DEFAULT_OPT_WEIGHTS)


# ── 5. journal cohort stamp ────────────────────────────────────────────────────

@pytest.fixture
def models(tmp_path, monkeypatch):
    monkeypatch.setenv("CYBERSCREENER_DB", str(tmp_path / "cohort.db"))
    import db.models as m
    importlib.reload(m)
    m.init_db()
    return m


def test_log_play_stamps_score_version(models):
    pid = models.log_play(
        ticker="COH", horizon="swing", strategy="Long Put", strike=100.0,
        expiry="2026-07-17", dte=30, entry_price=4.0, entry_iv_rank=50.0,
        lt_score=60.0, opt_score=70.0, rc_score=55, direction="bearish")
    conn = models.get_db()
    row = conn.execute(
        "SELECT score_version FROM options_plays WHERE id=?", (pid,)).fetchone()
    conn.close()
    assert row["score_version"] == "v2-baseline"


def test_log_play_stamps_legacy_version_in_legacy_mode(models, monkeypatch):
    monkeypatch.setenv("CYBERSCREENER_LEGACY_SCORES", "1")
    pid = models.log_play(
        ticker="LEG", horizon="swing", strategy="Long Call", strike=100.0,
        expiry="2026-07-17", dte=30, entry_price=4.0, entry_iv_rank=50.0,
        lt_score=60.0, opt_score=70.0, rc_score=55)
    conn = models.get_db()
    row = conn.execute(
        "SELECT score_version FROM options_plays WHERE id=?", (pid,)).fetchone()
    conn.close()
    assert row["score_version"] == "v1-legacy"


# ── 6. run_scan integration (offline) ──────────────────────────────────────────

ELITE = FIXTURES["elite_saas"]


@pytest.fixture
def offline_scan(monkeypatch):
    """run_scan with the network surgically removed: fetch_ticker_data returns
    a fixture row, intel modules are unavailable, sleeps are no-ops."""
    monkeypatch.setattr(sc, "fetch_ticker_data", lambda t: dict(ELITE, ticker=t))
    monkeypatch.setattr(sc.time, "sleep", lambda s: None)
    # Force the threat-intel import inside run_scan to fail fast (offline).
    monkeypatch.setitem(sys.modules, "intel.news_intel", None)
    return lambda: sc.run_scan(tickers=["ELTE"], enable_sec=False,
                               enable_sentiment=False)


def test_run_scan_emits_baseline_scores_with_legacy_in_meta(offline_scan):
    results = offline_scan()
    assert len(results) == 1
    r = results[0]

    _, _, lt_bd = sc.score_long_term(ELITE, weights=sc.DEFAULT_LT_WEIGHTS)
    _, _, opt_bd = sc.score_options(ELITE, weights=sc.DEFAULT_OPT_WEIGHTS)

    # Live scores are the baseline (elite_saas: valuation raw 1.0 -> 100.0)
    assert r["lt_score"] == baseline.compute_baseline_lt(lt_bd) == 100.0
    assert r["opt_score"] == baseline.compute_baseline_opt(opt_bd)

    # The legacy composite is preserved for comparison, with the cohort tag
    meta = r["lt_breakdown"]["_meta"]
    assert meta["score_version"] == "v2-baseline"
    assert meta["legacy_lt_score"] == 99.0      # hand-anchored in golden tests
    assert r["opt_breakdown"]["_meta"]["legacy_opt_score"] == 55.7

    # Component point columns keep REFERENCE-weight values (forward history)
    assert r["lt_valuation"] == lt_bd["valuation"]["points"] == 20.0
    assert r["lt_rule_of_40"] == lt_bd["rule_of_40"]["points"] == 25.0
    assert r["opt_asymmetry"] == opt_bd["asymmetry"]["points"]
    # ...and no junk column from the _meta entry
    assert "lt__meta" not in r


def test_run_scan_legacy_mode_unchanged(offline_scan, monkeypatch):
    monkeypatch.setenv("CYBERSCREENER_LEGACY_SCORES", "1")
    results = offline_scan()
    r = results[0]
    assert r["lt_score"] == 99.0     # the legacy composite, live again
    assert r["opt_score"] == 55.7
    assert "_meta" not in r["lt_breakdown"]
