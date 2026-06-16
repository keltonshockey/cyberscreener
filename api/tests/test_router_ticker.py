"""
Module test for routers/ticker.py (SESSION-ROUTER-SPLIT).

Proves the read-only ticker/universe endpoints are still registered on main.app
at the same paths and return the same response schema after extraction. Fully
offline — these endpoints read the static universe, not the DB.
"""
from fastapi.testclient import TestClient

import main

client = TestClient(main.app)


def test_routes_registered_once_at_same_paths():
    by_path = {}
    for r in main.app.routes:
        p = getattr(r, "path", None)
        if p in ("/tickers", "/universe", "/tickers/{sector}"):
            by_path.setdefault(p, set()).update(getattr(r, "methods", set()) or set())
    assert by_path.get("/tickers") == {"GET"}
    assert by_path.get("/universe") == {"GET"}
    assert by_path.get("/tickers/{sector}") == {"GET"}


def test_tickers_schema():
    resp = client.get("/tickers")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data) == {"universe", "all_tickers", "total"}
    assert isinstance(data["all_tickers"], list)
    assert data["total"] == len(data["all_tickers"])
    assert data["total"] > 0


def test_universe_schema():
    resp = client.get("/universe")
    assert resp.status_code == 200
    data = resp.json()
    assert set(data) == {"sectors", "summary", "tickers"}
    assert set(data["tickers"]) == {"cyber", "energy", "defense", "all"}
    # /tickers and /universe must agree on the deduplicated full universe.
    assert data["tickers"]["all"] == client.get("/tickers").json()["all_tickers"]


def test_tickers_by_sector_valid_and_invalid():
    resp = client.get("/tickers/cyber")
    assert resp.status_code == 200
    data = resp.json()
    assert data["sector"] == "cyber"
    assert data["total"] == len(data["tickers"])

    bad = client.get("/tickers/notasector")
    assert bad.status_code == 400
    assert "Sector must be one of" in bad.json()["detail"]
