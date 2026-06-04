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
