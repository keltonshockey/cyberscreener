"""Offline calibration job.

Runs `calibrate_weights()` off the HTTP request path so it can take as long as it
needs without tripping nginx's 60s proxy_read_timeout (the reason the synchronous
/calibrate endpoint 502'd on 2026-06-05).

Run it directly:
    cd api && python -m jobs.calibrate_job [--days 180] [--forward-period 30]

Guards (all must pass before calibration starts):
  - file lock at /tmp/cs_calibration.lock so two runs can't overlap
  - market-hours guard: refuses Mon-Fri 13:30-20:00 UTC (calibration + an active
    scan together spiked ~1.55GB RSS and OOM-froze scans on 2026-06-04)
  - swap-present check (the droplet OOM'd before a swapfile was added 2026-06-06)

A structured run record is always written to logs/calibration_<utc>.json (relative
to the api/ working dir), on both success and failure. Exit code is 0 on success,
non-zero on any guard failure or calibration error, so a scheduler can alert on it.
"""

import argparse
import json
import os
import sys
import fcntl
from datetime import datetime, timezone

LOCK_PATH = "/tmp/cs_calibration.lock"
SWAPS_PATH = "/proc/swaps"
LOG_DIR = "logs"

# Market-hours guard window, UTC (US regular session 9:30-16:00 ET ≈ 13:30-20:00 UTC).
MARKET_OPEN_MIN = 13 * 60 + 30   # 13:30 UTC
MARKET_CLOSE_MIN = 20 * 60       # 20:00 UTC


def is_market_hours(now=None):
    """True only Mon-Fri within 13:30-20:00 UTC. Weekends are always allowed."""
    now = now or datetime.now(timezone.utc)
    if now.weekday() >= 5:  # Saturday=5, Sunday=6
        return False
    minutes = now.hour * 60 + now.minute
    return MARKET_OPEN_MIN <= minutes < MARKET_CLOSE_MIN


def has_swap():
    """True if the OS reports an active swap area.

    The job is meant to run on the Linux droplet, where /proc/swaps lists active
    swap. If the file is missing (e.g. macOS) or lists no entries, treat swap as
    absent so the caller aborts rather than risking the OOM that froze scans.
    """
    try:
        with open(SWAPS_PATH, "r") as f:
            lines = [ln for ln in f.read().splitlines() if ln.strip()]
        # Line 0 is the header; at least one entry below it means swap is active.
        return len(lines) >= 2
    except OSError:
        return False


def _utc_stamp(dt):
    return dt.strftime("%Y%m%dT%H%M%SZ")


def _write_run_record(record, start):
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"calibration_{_utc_stamp(start)}.json")
    with open(path, "w") as f:
        json.dump(record, f, indent=2, default=str)
    return path


def run_calibration(days=180, forward_period=30):
    """Execute calibration and write a run record. Returns the record dict.

    Raises on calibration failure after recording it (caller maps to exit code).
    """
    # Imported lazily so the guards (and unit tests) don't pull in the heavy
    # backtest / scanner stack unless we actually calibrate.
    from backtest.engine import calibrate_weights
    from core.scanner import get_weights

    start = datetime.now(timezone.utc)
    before = get_weights()
    try:
        results = calibrate_weights(days, forward_period, dry_run=False)
        after = get_weights()
        end = datetime.now(timezone.utc)
        record = {
            "status": results.get("status", "unknown"),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "duration_seconds": (end - start).total_seconds(),
            "days": days,
            "forward_period": forward_period,
            "before_weights": before,
            "after_weights": after,
            "results": results,
        }
        path = _write_run_record(record, start)
        print(f"[calibrate_job] {record['status']} in {record['duration_seconds']:.0f}s -> {path}")
        return record
    except Exception as exc:  # noqa: BLE001 - record then re-raise
        end = datetime.now(timezone.utc)
        record = {
            "status": "error",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "duration_seconds": (end - start).total_seconds(),
            "days": days,
            "forward_period": forward_period,
            "before_weights": before,
            "error": repr(exc),
        }
        _write_run_record(record, start)
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description="Offline weight calibration job")
    parser.add_argument("--days", type=int, default=180)
    parser.add_argument("--forward-period", type=int, default=30)
    args = parser.parse_args(argv)

    if is_market_hours():
        print("[calibrate_job] refusing to run during US market hours "
              "(Mon-Fri 13:30-20:00 UTC); try an off-hours / weekend window.",
              file=sys.stderr)
        return 2

    if not has_swap():
        print("[calibrate_job] no active swap detected; aborting to avoid OOM. "
              "Enable a swapfile before calibrating.", file=sys.stderr)
        return 3

    # Single-instance lock. Held for the lifetime of the process; released on exit.
    lock_file = open(LOCK_PATH, "w")
    try:
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except (BlockingIOError, OSError):
        print("[calibrate_job] another calibration is already running; aborting.",
              file=sys.stderr)
        return 4

    try:
        run_calibration(days=args.days, forward_period=args.forward_period)
        return 0
    except Exception as exc:  # noqa: BLE001
        print(f"[calibrate_job] calibration failed: {exc!r}", file=sys.stderr)
        return 1
    finally:
        fcntl.flock(lock_file, fcntl.LOCK_UN)
        lock_file.close()


if __name__ == "__main__":
    raise SystemExit(main())
