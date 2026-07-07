"""
Regression tests for the market-hours-aware /health freshness signal.

Context: the Uptime Kuma /health monitor asserted `scan_age_seconds < 4500`,
which is NOT market-hours-gated, so it flapped DOWN ~6.4h every night when scans
legitimately pause (the "scan-stall incident" of 2026-07-07 was a stale ~6/15
snapshot, not an outage -- but it surfaced this nightly false-flap). /health now
exposes a market-hours-aware `scan_stale` boolean + `latest_scan_id`; the monitor
should assert `scan_stale == false` instead.

These test the pure decision helpers so no DB/clock mocking is needed.
"""
from datetime import datetime, timezone, timedelta

from main import _scan_window_active, _compute_scan_stale

# 2026-07-08 is a Wednesday; 2026-07-11 is a Saturday.
WED = lambda h, m=0: datetime(2026, 7, 8, h, m, tzinfo=timezone.utc)
SAT = lambda h, m=0: datetime(2026, 7, 11, h, m, tzinfo=timezone.utc)

STALE = 8000   # > 75 min threshold (4500 s)
FRESH = 600    # well under threshold


def test_scan_window_weekday_in_hours():
    assert _scan_window_active(WED(15)) is True
    assert _scan_window_active(WED(6)) is True    # open boundary
    assert _scan_window_active(WED(22)) is True   # close boundary


def test_scan_window_weekday_off_hours():
    assert _scan_window_active(WED(3)) is False
    assert _scan_window_active(WED(23)) is False
    assert _scan_window_active(WED(5)) is False


def test_scan_window_weekend_even_midsession():
    assert _scan_window_active(SAT(15)) is False


def test_stale_none_age_returns_none():
    assert _compute_scan_stale(None, WED(15)) is None


def test_fresh_scan_in_window_is_not_stale():
    assert _compute_scan_stale(FRESH, WED(15)) is False


def test_stale_scan_in_window_is_stale():
    # Overdue during the scanning window, and overdue a threshold ago too.
    assert _compute_scan_stale(STALE, WED(15)) is True


def test_stale_scan_overnight_is_not_stale():
    # The normal overnight pause must never read as a stall.
    assert _compute_scan_stale(STALE, WED(2)) is False


def test_stale_scan_just_after_open_is_not_stale():
    # 06:30 UTC: now is in-window but now-75min (05:15) is not -> grace period,
    # so the morning cold-start does not false-alarm.
    assert _compute_scan_stale(STALE, WED(6, 30)) is False


def test_stale_scan_weekend_is_not_stale():
    assert _compute_scan_stale(STALE, SAT(15)) is False


def test_grace_boundary_is_consistent_with_window():
    # A real mid-morning stall (well after open) IS flagged.
    assert _compute_scan_stale(STALE, WED(9)) is True
    assert _scan_window_active(WED(9) - timedelta(seconds=75 * 60)) is True
