"""
Module test for routers/plays.py (SESSION-ROUTER-SPLIT).

Proves the /plays/* + /ai/status cluster is still registered on main.app at the
same paths/methods and that the offline-reachable handlers return the same
response schema after extraction. Endpoints that would hit the network for live
options/ticker data (play generation against a real universe ticker) are only
exercised on their no-network branches (unknown ticker → 404, empty DB → "No
scans found.").
"""
import importlib

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    """TestClient over main.app with DB access rebound to a fresh temp DB,
    mirroring tests/test_api_smoke.py so the play caches start empty."""
    monkeypatch.setenv("CYBERSCREENER_DB", str(tmp_path / "plays.db"))
    import db.models as m
    importlib.reload(m)
    m.init_db()

    import routers.plays as rp
    importlib.reload(rp)

    import main
    return TestClient(main.app)


EXPECTED_ROUTES = {
    ("/plays/top/recommendations", "GET"),
    ("/plays/{ticker}/generate", "POST"),
    ("/plays/{ticker}/status", "GET"),
    ("/plays/{ticker}", "GET"),
    ("/plays/history/all", "GET"),
    ("/plays/history/{ticker}", "GET"),
    ("/plays/{ticker}/analyze", "POST"),
    ("/ai/status", "GET"),
    ("/plays/open/tracked", "GET"),
}


def test_routes_registered_once_at_same_paths(client):
    import main
    seen = []
    for r in main.app.routes:
        p = getattr(r, "path", None)
        for method in (getattr(r, "methods", set()) or set()):
            if (p, method) in EXPECTED_ROUTES:
                seen.append((p, method))
    assert sorted(seen) == sorted(EXPECTED_ROUTES)
    assert len(seen) == len(set(seen)), "a plays route is registered more than once"


def test_ai_status_schema(client):
    resp = client.get("/ai/status")
    assert resp.status_code == 200
    assert set(resp.json()) == {"available"}
    assert isinstance(resp.json()["available"], bool)


def test_plays_history_all_schema(client):
    resp = client.get("/plays/history/all")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data) == {"plays", "stats"}
    assert isinstance(data["plays"], list)


def test_plays_open_tracked_schema(client):
    resp = client.get("/plays/open/tracked")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data) == {"plays"}
    assert isinstance(data["plays"], list)


def test_plays_status_not_started(client):
    resp = client.get("/plays/ZZZZ/status")
    assert resp.status_code == 200
    assert resp.json() == {"status": "not_started"}


def test_generate_and_get_unknown_ticker_404(client):
    # Not in the universe → handlers 404 before any network call.
    assert client.post("/plays/NOTATICKER/generate").status_code == 404
    assert client.get("/plays/NOTATICKER").status_code == 404


def test_top_recommendations_empty_db(client):
    # No scans yet → early return, no options-chain fetch.
    resp = client.get("/plays/top/recommendations")
    assert resp.status_code == 200
    assert resp.json() == {"plays": [], "message": "No scans found."}
