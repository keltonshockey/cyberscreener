"""
Read-only narrative router contract.

Pins the four guarantees the store/API session promises:
  1. No row -> 202 {"status": "generating"} AND the view is logged to view_queue.
  2. Row present -> 200 with the exact payload schema.
  3. The `stale` flag is computed from the ST (24h) / LT (7d) TTLs.
  4. The router NEVER opens cyberscreener.db (prod DB) — it only touches the
     separate narratives.db. We prove this by making db.models.get_db explode
     for the duration of a request.

The narratives DB is repointed at a temp file via env BEFORE any import, mirroring
the isolation the other endpoint tests use for the prod DB.
"""
import os
import tempfile
from datetime import datetime, timedelta

_tmp = tempfile.mkdtemp(prefix="narratives-test-")
os.environ["CYBERSCREENER_NARRATIVES_DB"] = os.path.join(_tmp, "narratives.db")
os.environ.setdefault("CYBERSCREENER_DB", os.path.join(_tmp, "prod.db"))
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-minimum-pad!")
os.environ.setdefault("CYBERSCREENER_PASSWORD", "testpassword")

import pytest
from fastapi.testclient import TestClient

import db.narratives as narratives
from db.narratives import (
    init_narratives_db, get_narratives_db, upsert_narrative,
)

init_narratives_db()

from main import app

client = TestClient(app)


def _clear_store():
    conn = get_narratives_db()
    conn.execute("DELETE FROM narratives")
    conn.execute("DELETE FROM view_queue")
    conn.commit()
    conn.close()


def _view_row(ticker):
    conn = get_narratives_db()
    row = conn.execute(
        "SELECT * FROM view_queue WHERE ticker = ?", (ticker.upper(),)
    ).fetchone()
    conn.close()
    return row


def test_202_when_absent_and_view_is_logged():
    _clear_store()
    r = client.get("/narrative/CRWD")
    assert r.status_code == 202
    assert r.json() == {"status": "generating", "ticker": "CRWD"}

    # the lazy queue must have learned about the view
    vr = _view_row("CRWD")
    assert vr is not None
    assert vr["requested"] == 1
    assert vr["last_viewed_at"]


def test_200_payload_schema_when_row_present():
    _clear_store()
    now = datetime.utcnow().isoformat(timespec="seconds")
    upsert_narrative(
        "PANW",
        lt_story="Durable platform economics; Rule-of-40 at 58 anchors the LT case.",
        st_story="IV rank low into earnings; whale call flow building — asymmetric long.",
        sources=[{"title": "8-K filing", "url": "https://example.com/8k"}],
        signal_snapshot={"lt_score": 71, "opt_score": 64},
        snapshot_hash="abc123",
        confidence="ok",
        model="gemma3",
        lt_generated_at=now,
        st_generated_at=now,
    )
    r = client.get("/narrative/panw")  # lower-case in -> normalized out
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {
        "ticker", "lt_story", "st_story", "sources",
        "confidence", "lt_generated_at", "st_generated_at", "stale",
    }
    assert body["ticker"] == "PANW"
    assert body["sources"] == [{"title": "8-K filing", "url": "https://example.com/8k"}]
    assert body["confidence"] == "ok"
    assert body["stale"] is False


def test_stale_flag_math():
    _clear_store()
    fresh = datetime.utcnow().isoformat(timespec="seconds")
    old_st = (datetime.utcnow() - timedelta(hours=30)).isoformat(timespec="seconds")  # > 24h
    old_lt = (datetime.utcnow() - timedelta(days=10)).isoformat(timespec="seconds")   # > 7d

    # ST aged out, LT fresh -> stale
    upsert_narrative("AAA", lt_generated_at=fresh, st_generated_at=old_st)
    assert client.get("/narrative/AAA").json()["stale"] is True

    # LT aged out, ST fresh -> stale
    upsert_narrative("BBB", lt_generated_at=old_lt, st_generated_at=fresh)
    assert client.get("/narrative/BBB").json()["stale"] is True

    # both fresh -> not stale
    upsert_narrative("CCC", lt_generated_at=fresh, st_generated_at=fresh)
    assert client.get("/narrative/CCC").json()["stale"] is False

    # missing timestamps -> stale (never generated section)
    upsert_narrative("DDD", lt_generated_at=None, st_generated_at=None)
    assert client.get("/narrative/DDD").json()["stale"] is True


def test_router_never_opens_prod_db(monkeypatch):
    """If the narrative path ever reached cyberscreener.db, this would blow up."""
    _clear_store()
    import db.models as models

    def _boom(*a, **k):
        raise AssertionError("narrative router must not open cyberscreener.db")

    monkeypatch.setattr(models, "get_db", _boom)

    # both branches: 202 (absent) and 200 (present) must stay clear of prod DB
    assert client.get("/narrative/ZZZ").status_code == 202
    upsert_narrative("ZZZ", lt_story="x", lt_generated_at=datetime.utcnow().isoformat())
    assert client.get("/narrative/ZZZ").status_code == 200
