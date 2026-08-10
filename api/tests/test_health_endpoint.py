import os, tempfile
_tmp = tempfile.mkdtemp()
os.environ.setdefault("CYBERSCREENER_DB", f"{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-minimum-pad!")
os.environ.setdefault("CYBERSCREENER_PASSWORD", "testpassword")

from fastapi.testclient import TestClient
from db.models import init_db
init_db()
from main import app

client = TestClient(app)

def test_health_returns_200():
    response = client.get("/health")
    assert response.status_code == 200

def test_health_has_required_keys():
    response = client.get("/health")
    data = response.json()
    required_keys = {"status", "last_scan_utc", "scan_age_seconds", "db_size_mb", "droplet", "version", "scans"}
    assert all(key in data for key in required_keys)

def test_health_scan_age_is_int_or_null():
    response = client.get("/health")
    data = response.json()
    assert isinstance(data["scan_age_seconds"], int) or data["scan_age_seconds"] is None

def test_health_db_size_is_float_or_null():
    response = client.get("/health")
    data = response.json()
    assert isinstance(data["db_size_mb"], float) or data["db_size_mb"] is None

def test_health_droplet_value():
    response = client.get("/health")
    data = response.json()
    assert data["droplet"] == "64.23.150.209"


# ── V3C: /health version resolves the real git SHA at process start ──

def test_health_version_is_nonempty_string():
    data = client.get("/health").json()
    assert isinstance(data["version"], str)
    assert data["version"].strip()


def test_health_version_is_cached_not_per_request(monkeypatch):
    """APP_VERSION is resolved once at import; /health must not shell out."""
    import subprocess
    import main as main_mod

    def boom(*args, **kwargs):
        raise AssertionError("/health called subprocess at request time")

    monkeypatch.setattr(subprocess, "run", boom)
    data = client.get("/health").json()
    assert data["version"] == main_mod.APP_VERSION
    assert data["version"].strip()


def test_resolver_falls_back_cleanly_when_git_unavailable(monkeypatch, tmp_path):
    """Subprocess failure -> VERSION file -> old constant; never an exception."""
    import subprocess
    from main import _resolve_version

    def boom(*args, **kwargs):
        raise FileNotFoundError("git: command not found")

    monkeypatch.setattr(subprocess, "run", boom)

    # No VERSION file anywhere -> the old static fallback.
    empty = tmp_path / "empty"
    empty.mkdir()
    assert _resolve_version(app_dir=str(empty)) == "unknown"

    # VERSION file present (deploy-time escape hatch) -> its contents.
    vdir = tmp_path / "app"
    vdir.mkdir()
    (vdir / "VERSION").write_text("v3c-deploy-stamp\n", encoding="utf-8")
    assert _resolve_version(app_dir=str(vdir)) == "v3c-deploy-stamp"
