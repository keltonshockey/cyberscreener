"""
Valuation Watchlist router -- snapshot rule, determinism, read-only proof,
and the registered caveat text.

The fixture DB is built through the real schema door (db.models.init_db after
an env rebind + reload, the test_api_smoke pattern -- main.py runs init_db at
import, so a hand-rolled minimal schema would collide with it), then seeded
with raw scans/scores rows across two months so the snapshot rule is
exercised rather than assumed:

  scan 1  2026-06-30 21:30  (last June scan)
  scan 2  2026-07-15 14:00  (mid-July)
  scan 3  2026-07-31 21:30  (last July scan -- the August snapshot)
  scan 4  2026-08-05 14:00  (current-month scan -- must be invisible in August)
  scan 5  2026-07-31 23:59  (later timestamp but EMPTY -- no scores rows, so
                             it is not "completed" and must never be chosen)

The router reads the DB path from CYBERSCREENER_DB at request time, so each
test monkeypatches the env and hits the real app -- no module reloads needed.
"""

import importlib
import sqlite3

import pytest
from fastapi.testclient import TestClient

# (scan_id, timestamp) -- see module docstring.
SCANS = [
    (1, "2026-06-30 21:30:00"),
    (2, "2026-07-15 14:00:00"),
    (3, "2026-07-31 21:30:00"),
    (4, "2026-08-05 14:00:00"),
    (5, "2026-07-31 23:59:00"),  # empty: no scores rows
]

# Per-scan scores. Scan 3 (the August snapshot) carries a NULL-valuation row
# (NOSCORE) that must be excluded, and a tie (TIEA/TIEB at 40.0) that must
# break by ticker.
SCORES = {
    1: [("JUN1", 100.0, 90.0, "cyber")],
    2: [("MIDJ", 100.0, 55.0, "energy")],
    3: [
        ("ALPH", 120.0, 88.0, "cyber"),
        ("BETA", 80.0, 61.5, "energy"),
        ("TIEA", 50.0, 40.0, "defense"),
        ("TIEB", 55.0, 40.0, "cyber"),
        ("NOSCORE", 10.0, None, "cyber"),
    ],
    4: [("AUGX", 200.0, 99.0, "cyber")],
    5: [],
}


@pytest.fixture
def fixture_db(tmp_path, monkeypatch):
    db = tmp_path / "watchlist-fixture.db"
    monkeypatch.setenv("CYBERSCREENER_DB", str(db))
    import db.models as m
    importlib.reload(m)
    m.init_db()  # full production schema (incl. sector via ensure-columns)

    conn = sqlite3.connect(db)
    for scan_id, ts in SCANS:
        conn.execute(
            "INSERT INTO scans (id, timestamp, tickers_scanned) VALUES (?, ?, ?)",
            (scan_id, ts, len(SCORES[scan_id])),
        )
        for tk, price, val, sector in SCORES[scan_id]:
            conn.execute(
                "INSERT INTO scores (scan_id, ticker, price, lt_valuation, sector)"
                " VALUES (?, ?, ?, ?, ?)",
                (scan_id, tk, price, val, sector),
            )
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def client(fixture_db):
    # The watchlist router reads CYBERSCREENER_DB per request, so the env
    # rebind in fixture_db is all the redirection it needs.
    import main
    return TestClient(main.app)


# -- snapshot rule ------------------------------------------------------------

def test_snapshot_picks_last_completed_scan_of_previous_month(client):
    resp = client.get("/watchlist/valuation?asof=2026-08-10")
    assert resp.status_code == 200
    data = resp.json()
    # Scan 3, not: scan 2 (earlier July), scan 4 (current month),
    # scan 5 (later July timestamp but empty -> not completed).
    assert data["as_of_scan_id"] == 3
    assert data["as_of_utc"] == "2026-07-31 21:30:00"
    assert data["snapshot_month"] == "2026-07"


def test_mid_current_month_scan_does_not_change_snapshot(client, fixture_db):
    """Determinism: a NEW scan landing mid-current-month leaves the same-asof
    response byte-identical."""
    before = client.get("/watchlist/valuation?asof=2026-08-10")
    assert before.status_code == 200

    w = sqlite3.connect(fixture_db)  # test-side writer; the ROUTER stays ro
    w.execute("INSERT INTO scans (id, timestamp) VALUES (6, '2026-08-09 14:00:00')")
    w.execute(
        "INSERT INTO scores (scan_id, ticker, price, lt_valuation, sector)"
        " VALUES (6, 'FRESH', 10.0, 100.0, 'cyber')"
    )
    w.commit()
    w.close()

    after = client.get("/watchlist/valuation?asof=2026-08-10")
    assert after.status_code == 200
    assert after.json() == before.json(), "a current-month scan changed the frozen snapshot"


def test_month_rollover_changes_snapshot(client):
    """In September the August scan becomes eligible and must take over."""
    resp = client.get("/watchlist/valuation?asof=2026-09-01")
    assert resp.status_code == 200
    data = resp.json()
    assert data["as_of_scan_id"] == 4
    assert data["snapshot_month"] == "2026-08"
    assert [e["ticker"] for e in data["entries"]] == ["AUGX"]


def test_no_eligible_scan_is_404_not_500(client):
    resp = client.get("/watchlist/valuation?asof=2026-06-15")  # nothing before June
    assert resp.status_code == 404


# -- ranking ------------------------------------------------------------------

def test_ranking_excludes_null_and_orders_desc_with_stable_ties(client):
    data = client.get("/watchlist/valuation?asof=2026-08-10").json()
    tickers = [e["ticker"] for e in data["entries"]]
    assert "NOSCORE" not in tickers, "NULL lt_valuation row leaked into the ranking"
    assert tickers == ["ALPH", "BETA", "TIEA", "TIEB"]  # desc, tie by ticker
    assert [e["rank"] for e in data["entries"]] == [1, 2, 3, 4]
    e0 = data["entries"][0]
    assert e0["lt_valuation"] == 88.0
    assert e0["sector"] == "cyber"
    assert e0["price"] == 120.0


def test_limit_param_bounds(client):
    resp = client.get("/watchlist/valuation?asof=2026-08-10&limit=2")
    assert resp.status_code == 200
    assert [e["ticker"] for e in resp.json()["entries"]] == ["ALPH", "BETA"]

    assert client.get("/watchlist/valuation?asof=2026-08-10&limit=201").status_code == 422
    assert client.get("/watchlist/valuation?asof=2026-08-10&limit=0").status_code == 422


def test_invalid_asof_is_4xx_not_500(client):
    for bad in ("2026-13-45", "garbage", "2026-8-1", "20260810", "2026-02-30"):
        resp = client.get(f"/watchlist/valuation?asof={bad}")
        assert 400 <= resp.status_code < 500, f"asof={bad} -> {resp.status_code}"


# -- read-only proof ----------------------------------------------------------

def test_router_connection_cannot_write(fixture_db, monkeypatch):
    """The router's own door (_open_ro) must fail any write at the sqlite layer."""
    monkeypatch.setenv("CYBERSCREENER_DB", str(fixture_db))
    from routers.watchlist import _open_ro
    conn = _open_ro()
    try:
        with pytest.raises(sqlite3.OperationalError, match="readonly|read-only|query_only"):
            conn.execute("INSERT INTO scores (scan_id, ticker) VALUES (99, 'EVIL')")
            conn.commit()
    finally:
        conn.close()


def test_request_does_not_mutate_the_db(client, fixture_db):
    import hashlib
    before = hashlib.sha256(fixture_db.read_bytes()).hexdigest()
    assert client.get("/watchlist/valuation?asof=2026-08-10").status_code == 200
    after = hashlib.sha256(fixture_db.read_bytes()).hexdigest()
    assert before == after, "serving the watchlist modified the database"


# -- registered copy ----------------------------------------------------------

def test_caveat_copy_is_verbatim(client):
    data = client.get("/watchlist/valuation?asof=2026-08-10").json()
    assert data["copy"]["caveat"] == (
        "Survivorship caveat: the 12-month out-of-sample Valuation quintile "
        "premium is +1.3% to +5.9% under defensible assumptions; 9.7% of the "
        "historical universe exited the sample and their prices are "
        "unrecoverable from free sources. This range, not the point estimate, "
        "is the evidence base. Horizon: 6-12 months. This is an experimental "
        "research surface, not investment advice."
    )
    assert data["copy"]["horizon"] == (
        "Monthly snapshot. The underlying signal operates on a 6-12 month "
        "horizon; intraday movement is deliberately not shown here."
    )


# -- smoke --------------------------------------------------------------------

def test_watchlist_smoke_schema(client):
    resp = client.get("/watchlist/valuation?asof=2026-08-10")
    assert resp.status_code == 200
    data = resp.json()
    for key in ("as_of_scan_id", "as_of_utc", "snapshot_month", "entries", "copy"):
        assert key in data, f"payload missing {key}"
    for entry in data["entries"]:
        missing = {"rank", "ticker", "lt_valuation", "sector", "price"} - set(entry)
        assert not missing, f"entry missing {missing}"
