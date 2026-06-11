"""
SESSION-SLIM-SCOPE — world PAUSE flag (/config/ui).

The 3D world is paused by default (Kelton's call 2026-06-11: pause, not cut).
WORLD_ENABLED=1 in the service env revives it at runtime — no rebuild. The
frontend hides the World nav tab and serves a paused notice on /world while
the flag is off; the (already code-split) world JS chunk is never fetched.
"""
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("CYBERSCREENER_DB", f"{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-minimum-pad!")
os.environ.setdefault("CYBERSCREENER_PASSWORD", "testpassword")

from fastapi.testclient import TestClient
from db.models import init_db
init_db()
from main import app

client = TestClient(app)


def test_world_paused_by_default(monkeypatch):
    monkeypatch.delenv("WORLD_ENABLED", raising=False)
    resp = client.get("/config/ui")
    assert resp.status_code == 200
    assert resp.json() == {"world_enabled": False}


def test_world_disabled_explicitly(monkeypatch):
    monkeypatch.setenv("WORLD_ENABLED", "0")
    assert client.get("/config/ui").json()["world_enabled"] is False


def test_world_enabled_by_env(monkeypatch):
    monkeypatch.setenv("WORLD_ENABLED", "1")
    resp = client.get("/config/ui")
    assert resp.status_code == 200
    assert resp.json() == {"world_enabled": True}
