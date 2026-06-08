"""Tests for the offline calibration job and the enqueue-only /calibrate endpoint.

Run from the api/ dir: `pytest tests/test_calibrate_job.py`.
"""

import os, tempfile
_tmp = tempfile.mkdtemp()
os.environ.setdefault("CYBERSCREENER_DB", f"{_tmp}/test.db")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-minimum-pad!")
os.environ.setdefault("CYBERSCREENER_PASSWORD", "testpassword")

import fcntl
import time
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from db.models import init_db
init_db()

import jobs.calibrate_job as cj
from main import app, require_admin


# ── market-hours guard ────────────────────────────────────────────────────────

def test_market_hours_blocks_weekday_session():
    # Wednesday 2026-06-10, 15:00 UTC — inside the 13:30-20:00 window.
    now = datetime(2026, 6, 10, 15, 0, tzinfo=timezone.utc)
    assert cj.is_market_hours(now) is True


def test_market_hours_allows_weekday_offhours():
    # Wednesday 2026-06-10, 06:00 UTC — before the window.
    now = datetime(2026, 6, 10, 6, 0, tzinfo=timezone.utc)
    assert cj.is_market_hours(now) is False


def test_market_hours_allows_weekend_even_midsession():
    # Saturday 2026-06-13, 15:00 UTC — weekend is always allowed.
    now = datetime(2026, 6, 13, 15, 0, tzinfo=timezone.utc)
    assert cj.is_market_hours(now) is False


def test_main_aborts_during_market_hours_without_calibrating():
    with patch.object(cj, "is_market_hours", return_value=True), \
         patch.object(cj, "run_calibration") as mock_run:
        rc = cj.main([])
    assert rc == 2
    mock_run.assert_not_called()


# ── single-instance lock ──────────────────────────────────────────────────────

def test_lock_prevents_concurrent_runs(tmp_path):
    lock_path = str(tmp_path / "cs_calibration.lock")
    held = open(lock_path, "w")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        with patch.object(cj, "LOCK_PATH", lock_path), \
             patch.object(cj, "is_market_hours", return_value=False), \
             patch.object(cj, "has_swap", return_value=True), \
             patch.object(cj, "run_calibration") as mock_run:
            rc = cj.main([])
        assert rc == 4  # lock-contended exit code
        mock_run.assert_not_called()
    finally:
        fcntl.flock(held, fcntl.LOCK_UN)
        held.close()


def test_main_runs_calibration_when_guards_pass(tmp_path):
    lock_path = str(tmp_path / "cs_calibration.lock")
    with patch.object(cj, "LOCK_PATH", lock_path), \
         patch.object(cj, "is_market_hours", return_value=False), \
         patch.object(cj, "has_swap", return_value=True), \
         patch.object(cj, "run_calibration") as mock_run:
        rc = cj.main([])
    assert rc == 0
    mock_run.assert_called_once()


def test_main_aborts_without_swap():
    with patch.object(cj, "is_market_hours", return_value=False), \
         patch.object(cj, "has_swap", return_value=False), \
         patch.object(cj, "run_calibration") as mock_run:
        rc = cj.main([])
    assert rc == 3
    mock_run.assert_not_called()


# ── endpoint is enqueue-only ──────────────────────────────────────────────────

@pytest.fixture
def admin_client():
    app.dependency_overrides[require_admin] = lambda: {"admin": True}
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(require_admin, None)


def test_calibrate_endpoint_returns_202_quickly_and_no_inline_calibrate(admin_client):
    # Patch the symbol bound in main's namespace so an accidental inline call is caught.
    with patch("main.calibrate_weights") as inline_calibrate:
        start = time.time()
        resp = admin_client.post("/calibrate")
        elapsed = time.time() - start

    assert resp.status_code == 202
    assert elapsed < 1.0
    inline_calibrate.assert_not_called()
    body = resp.json()
    assert body["status"] == "queued"
    assert body["job_id"].startswith("cal_")
