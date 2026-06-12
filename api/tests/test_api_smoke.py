"""
API smoke tests — the read endpoints the UI and the forward-test journal live
on must return 200 + schema-valid JSON against a fixture DB, fully offline.

Covered: /health, /scores/latest, /killer-plays.
Note: there is no backend /conviction route — the Conviction (Forum) page is a
frontend route fed by /scores/latest and /killer-plays, so those two ARE the
conviction smoke surface.

Seeding goes through models.save_scan() (not raw INSERTs) so the smoke test
exercises the same persist path production uses.
"""
import importlib

import pytest
from fastapi.testclient import TestClient


def _row(ticker, *, price, sma20, sma50, rsi, perf_3m, lt, opt, rc=60, mcap=80.0):
    """A scored result row decisive enough to survive every /killer-plays
    filter (post-PR#6 the direction must clear MIN_DIR_MARGIN to not be
    dropped as neutral)."""
    return dict(
        ticker=ticker, price=price, market_cap_b=mcap,
        lt_score=lt, opt_score=opt, rc_score=rc,
        rsi=rsi, sma_20=sma20, sma_50=sma50, perf_3m=perf_3m,
        iv_30d=45.0, iv_rank=50.0,
        sector="cyber", subsector="saas", scoring_profile="saas",
        threat_score=100, outage_status="none",
        lt_breakdown={}, opt_breakdown={},
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient over main.app with all DB access rebound to a seeded temp DB.

    Reloading db.models re-executes it in the SAME module object, so the
    get_db already captured by router functions reads the new DB_PATH from its
    (shared) globals. Reloading the router modules resets their module-level
    response caches.
    """
    monkeypatch.setenv("CYBERSCREENER_DB", str(tmp_path / "smoke.db"))
    import db.models as m
    importlib.reload(m)
    m.init_db()

    # BEARX: rsi 80 (+3 bear) + below both SMAs (+2) + perf -15 (+1) = bearish 6
    # BULLX: rsi 22 (+3 bull) + above both SMAs (+2) + perf +15 (+1) = bullish 6
    # MIDX: low scores, neutral — must NOT appear in killer-plays
    m.save_scan([
        _row("BEARX", price=100, sma20=110, sma50=120, rsi=80, perf_3m=-15,
             lt=80.0, opt=80.0),
        _row("BULLX", price=100, sma20=90, sma50=85, rsi=22, perf_3m=15,
             lt=80.0, opt=80.0),
        _row("MIDX", price=50, sma20=50, sma50=50, rsi=50, perf_3m=0,
             lt=40.0, opt=40.0),
    ], intel_layers=["base"], duration_seconds=1.0)

    import routers.scores as rs
    importlib.reload(rs)
    import routers.market as mk
    importlib.reload(mk)

    import main
    return TestClient(main.app)


def test_health_smoke(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("status", "scans", "scan_age_seconds", "db_size_mb", "version"):
        assert key in data, f"/health missing {key}"
    assert data["scans"] == 1


def test_scores_latest_smoke(client):
    resp = client.get("/scores/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["scan_id"] == 1
    assert data["scan_timestamp"]
    assert len(data["results"]) == 3

    required = {"ticker", "price", "lt_score", "opt_score", "rc_score",
                "rsi", "sector", "iv_30d", "market_cap_b", "scan_id"}
    for row in data["results"]:
        missing = required - set(row)
        assert not missing, f"/scores/latest row missing {missing}"

    # ordered by lt_score desc; the seeded values must round-trip
    lts = [r["lt_score"] for r in data["results"]]
    assert lts == sorted(lts, reverse=True)
    by_ticker = {r["ticker"]: r for r in data["results"]}
    assert by_ticker["BEARX"]["opt_score"] == 80.0
    assert by_ticker["MIDX"]["lt_score"] == 40.0


def test_killer_plays_smoke(client):
    resp = client.get("/killer-plays")
    assert resp.status_code == 200
    data = resp.json()
    assert "plays" in data and isinstance(data["plays"], list)
    tickers = {p["ticker"] for p in data["plays"]}
    assert "BEARX" in tickers and "BULLX" in tickers
    assert "MIDX" not in tickers   # low-conviction neutral must not surface

    required = {"ticker", "price", "opt_score", "lt_score", "rc_score",
                "direction", "direction_label", "combined_score",
                "conviction", "catalyst"}
    for play in data["plays"]:
        missing = required - set(play)
        assert not missing, f"/killer-plays play missing {missing}"
        assert play["direction"] in ("bullish", "bearish")
        assert play["direction_label"] in ("Bullish", "Bearish")
        assert play["conviction"] in ("HIGH", "SOLID", "WATCH")

    by_ticker = {p["ticker"]: p for p in data["plays"]}
    assert by_ticker["BEARX"]["direction"] == "bearish"
    assert by_ticker["BULLX"]["direction"] == "bullish"
    assert by_ticker["BEARX"]["combined_score"] == 80.0


def test_layers_smoke(client):
    """/layers feeds the UI Layers panel: membership, captions, ref weights."""
    resp = client.get("/layers")
    assert resp.status_code == 200
    data = resp.json()
    assert data["score_version"] == "v2-baseline"
    assert data["baseline"] == {"lt": {"valuation": 100}, "opt": {"asymmetry": 100}}
    assert data["ref_weights"]["lt"]["valuation"] == 20
    assert data["layers"], "layers list must not be empty"
    for name, layer in data["layers"].items():
        assert layer["caption"], f"{name} missing caption"
        assert layer["status"], f"{name} missing status"
    assert "view_semantics" in data


def test_scores_latest_carries_score_version(client):
    data = client.get("/scores/latest").json()
    assert data["score_version"] == "v2-baseline"


def test_scores_latest_empty_db(tmp_path, monkeypatch):
    """An empty DB must yield a graceful 200 + message, not a 500."""
    monkeypatch.setenv("CYBERSCREENER_DB", str(tmp_path / "empty.db"))
    import db.models as m
    importlib.reload(m)
    m.init_db()
    import routers.scores as rs
    importlib.reload(rs)

    import main
    resp = TestClient(main.app).get("/scores/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["results"] == []
    assert "message" in data
