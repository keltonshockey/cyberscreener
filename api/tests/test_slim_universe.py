"""
SESSION-SLIM-SCOPE — slim universe loader + journal-continuity union.

Locks in: the committed config's invariants (size ~100, cap floor, sector
mix), the env revert flag, the dynamic open-play union (a dropped ticker
keeps scanning until its journal plays close), and the fail-safe fallbacks.
"""
import importlib
import json
from pathlib import Path

import pytest

import core.slim_universe as su

CONFIG = json.loads((Path(__file__).parent.parent / "core" / "universe_slim.json").read_text())
FULL = [f"FULL{i}" for i in range(480)]


@pytest.fixture(autouse=True)
def fresh_cache():
    """Loader cache reset around every test."""
    su._config_cache = None
    su._config_loaded = False
    yield
    su._config_cache = None
    su._config_loaded = False


# ── committed-config invariants ────────────────────────────────────────────────

def test_config_size_is_about_100():
    n = len(CONFIG["tickers"])
    assert 90 <= n <= 110, f"slim universe is {n} names — re-justify if this moves"


def test_config_respects_cap_floor():
    floor = CONFIG["criteria"]["market_cap_floor_b"]
    for t, meta in CONFIG["tickers"].items():
        assert meta["market_cap_b"] >= floor, f"{t} below the ${floor}B floor"


def test_config_preserves_sector_mix():
    counts = CONFIG["sector_counts"]
    assert counts["cyber"] >= 25                      # thesis sector kept whole
    assert counts["defense"] >= 5 and counts["energy"] >= 8
    for sub in ("Technology", "Health Care", "Financials", "Industrials"):
        assert counts[f"broad/{sub}"] >= 4, f"deep-review sector {sub} underrepresented"


def test_config_documents_every_exclusion_category():
    for cat, n in CONFIG["excluded_counts"].items():
        assert cat in CONFIG["exclusion_reasons"], f"undocumented exclusion category {cat}"
        assert len(CONFIG["excluded"][cat]) == n


def test_config_is_enabled_and_provenanced():
    assert CONFIG["enabled"] is True
    assert CONFIG["built_from_scan"]            # reproducibility anchor
    assert CONFIG["criteria"]["options_liquidity"]


# ── loader behavior ────────────────────────────────────────────────────────────

def test_active_tickers_uses_slim_list(monkeypatch):
    monkeypatch.setattr(su, "open_play_tickers", lambda: set())
    active = su.get_active_tickers(FULL)
    # slim list plus any manually pinned thesis names (always_include, e.g. RPD)
    assert set(active) == set(CONFIG["tickers"].keys()) | set(CONFIG.get("always_include", []))
    assert len(active) < len(FULL) / 3


def test_full_universe_env_flag_reverts(monkeypatch):
    monkeypatch.setenv("CYBERSCREENER_FULL_UNIVERSE", "1")
    assert su.get_active_tickers(FULL) == FULL


def test_missing_config_falls_back_to_full(monkeypatch, tmp_path):
    monkeypatch.setattr(su, "CONFIG_PATH", tmp_path / "absent.json")
    assert su.get_active_tickers(FULL) == FULL


def test_disabled_config_falls_back_to_full(monkeypatch, tmp_path):
    p = tmp_path / "disabled.json"
    p.write_text(json.dumps({"enabled": False, "tickers": {"X": {}}}))
    monkeypatch.setattr(su, "CONFIG_PATH", p)
    assert su.get_active_tickers(FULL) == FULL


def test_corrupt_config_falls_back_to_full(monkeypatch, tmp_path):
    p = tmp_path / "corrupt.json"
    p.write_text("{not json")
    monkeypatch.setattr(su, "CONFIG_PATH", p)
    assert su.get_active_tickers(FULL) == FULL


# ── journal continuity ─────────────────────────────────────────────────────────

def test_open_play_tickers_unioned_until_closed(monkeypatch):
    """A ticker dropped from the slim list but holding an OPEN journal play
    keeps scanning; once closed it drops out (the core continuity guarantee)."""
    # RBBN is genuinely excluded (sub-$1B on the selection scan) and NOT pinned
    # (RPD was pinned via always_include 2026-06-12, so it can no longer stand in
    # for a dropped name here).
    dropped = "RBBN"
    assert dropped not in CONFIG["tickers"]
    assert dropped not in CONFIG.get("always_include", [])

    monkeypatch.setattr(su, "open_play_tickers", lambda: {dropped})
    assert dropped in su.get_active_tickers(FULL)

    monkeypatch.setattr(su, "open_play_tickers", lambda: set())
    assert dropped not in su.get_active_tickers(FULL)


def test_always_include_pins(monkeypatch, tmp_path):
    p = tmp_path / "pin.json"
    p.write_text(json.dumps({
        "enabled": True, "tickers": {"AAA": {}}, "always_include": ["PINNED"]}))
    monkeypatch.setattr(su, "CONFIG_PATH", p)
    monkeypatch.setattr(su, "open_play_tickers", lambda: set())
    assert set(su.get_active_tickers(FULL)) == {"AAA", "PINNED"}


def test_open_play_lookup_reads_journal(tmp_path, monkeypatch):
    """open_play_tickers() reads status='open' rows from the real journal
    table; closed rows do not count."""
    monkeypatch.setenv("CYBERSCREENER_DB", str(tmp_path / "j.db"))
    import db.models as m
    importlib.reload(m)
    m.init_db()
    m.log_play(ticker="OPN", horizon="swing", strategy="Long Call", strike=100.0,
               expiry="2026-07-17", dte=30, entry_price=4.0, entry_iv_rank=50.0,
               lt_score=60.0, opt_score=70.0, rc_score=55)
    pid = m.log_play(ticker="CLSD", horizon="swing", strategy="Long Put", strike=90.0,
                     expiry="2026-07-17", dte=30, entry_price=3.0, entry_iv_rank=50.0,
                     lt_score=60.0, opt_score=70.0, rc_score=55)
    m.close_play(pid, outcome_price=80.0, pnl_pct=50.0)

    assert su.open_play_tickers() == {"OPN"}
