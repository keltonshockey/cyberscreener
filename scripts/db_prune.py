#!/usr/bin/env python3
"""
CyberScreener DB prune — retention-based, forward-test-safe.

Retention policy (all values configurable via db_prune_config.json):
  - scores, last `scores_full_days` (default 30):   every scan kept (full intraday granularity)
  - scores, `scores_full_days`..`scores_daily_days` (default 31..365):
        keep only the LAST scan of each calendar day ("daily keeper"); delete the rest.
        Daily granularity is all the learning loop uses: calibration builds
        (score, forward-return) pairs keyed on date (scan_date[:10]), and IV rank
        (get_iv_history, 365d) takes min/max over the window.
  - scores, older than `scores_daily_days`:          keep only the last scan of each ISO week
  - signals, older than `signals_days` (default 30): deleted (all readers fetch "recent N" only)

PROTECTED — never touched, asserted unchanged before commit:
  options_plays (the forward-test journal, open AND closed), prices (play outcomes
  are finalized from prices, not scores), scans, score_weights, users, watchlist,
  refresh_tokens, earnings_dates, augur_*.

Safety guards (all mandatory in live mode):
  - refuses to run mid-scan (scanner.log in-flight check) or outside the idle window
  - timestamped pre-prune backup (sqlite3 online backup API), verified, before any delete
  - aborts if free disk < current DB size
  - single transaction; protected-row assertions checked BEFORE commit; any
    violation rolls back everything
  - space reclaim via VACUUM INTO + integrity check + atomic rename (plain VACUUM
    would lock hard and need ~DB-size of temp in the same filesystem anyway)

Modes:
  db_prune.py                      dry-run (default): report only, zero writes
  db_prune.py --commit             prune + backup + VACUUM INTO swap
  db_prune.py --auto --commit      threshold-triggered: exit quietly unless
                                   DB size > size_threshold_mb; used by the systemd timer
  db_prune.py --assume-idle        skip idle-window/scan-lock/service checks —
                                   ONLY for offline copies, never the live DB

Exit codes: 0 ok / nothing to do, 1 guard refused, 2 assertion or runtime failure.
"""

import argparse
import datetime as dt
import json
import logging
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import time

DEFAULTS = {
    "db_path": "/app/data/cyberscreener.db",
    "scores_full_days": 30,
    "scores_daily_days": 365,
    "signals_days": 30,
    "size_threshold_mb": 1700,
    "backup_dir": "/app/data",
    "backup_keep": 2,
    "log_file": "/var/log/cyberscreener-prune.log",
    "scanner_log": "/opt/cyberscreener/api/scanner.log",
    "idle_window_utc": ["23:00", "05:30"],
    "services": ["cyberscreener.service", "cyberscreener-scheduler.service"],
    "manage_services": True,
    "notify": True,
    "api_dir": "/opt/cyberscreener/api",
}

# Tables the policy may delete from. Every OTHER table is protected and its
# row count is asserted unchanged before COMMIT.
PRUNABLE_TABLES = {"scores", "signals"}

BACKUP_PREFIX = "cyberscreener.db.preprune."

# Scans to keep all scores for. Parameters: :full_cutoff_ts, :daily_cutoff_ts
KEEP_SCANS_SQL = """
    SELECT id FROM scans WHERE timestamp >= :full_cutoff_ts
    UNION
    SELECT MAX(id) FROM scans
        WHERE timestamp >= :daily_cutoff_ts AND timestamp < :full_cutoff_ts
        GROUP BY date(timestamp)
    UNION
    SELECT MAX(id) FROM scans
        WHERE timestamp < :daily_cutoff_ts
        GROUP BY strftime('%Y-%W', timestamp)
"""

log = logging.getLogger("db_prune")


# ─────────────────────────────────────────────────────────────────────────────
# Setup
# ─────────────────────────────────────────────────────────────────────────────

def load_config(path):
    cfg = dict(DEFAULTS)
    if path and os.path.exists(path):
        with open(path) as f:
            cfg.update(json.load(f))
    return cfg


def setup_logging(log_file):
    log.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    log.addHandler(sh)
    try:
        fh = logging.FileHandler(log_file)
        fh.setFormatter(fmt)
        log.addHandler(fh)
    except OSError as e:
        log.warning("Cannot open log file %s (%s); logging to stdout only", log_file, e)


def get_conn(db_path, ro=False):
    if ro:
        # mode=ro cannot read a WAL-mode DB whose -shm does not exist yet
        # (e.g. a standalone .backup copy). Fall back to a normal connection
        # locked down with query_only — identical zero-write guarantee.
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
        try:
            conn.execute("SELECT 1 FROM sqlite_master LIMIT 1")
        except sqlite3.OperationalError:
            conn.close()
            conn = sqlite3.connect(db_path, timeout=60)
            conn.execute("PRAGMA query_only=ON")
    else:
        conn = sqlite3.connect(db_path, timeout=60)
    conn.row_factory = sqlite3.Row
    return conn


# ─────────────────────────────────────────────────────────────────────────────
# Guards
# ─────────────────────────────────────────────────────────────────────────────

def in_idle_window(cfg, now=None):
    """True if now is inside the configured idle window (or a weekend).
    The scheduler only scans weekdays 06:00-22:00 box-local; scans take ~35 min,
    so the default window starts 23:00."""
    now = now or dt.datetime.now()
    if now.weekday() >= 5:
        return True, "weekend (scheduler idle)"
    start_s, end_s = cfg["idle_window_utc"]
    start = dt.datetime.strptime(start_s, "%H:%M").time()
    end = dt.datetime.strptime(end_s, "%H:%M").time()
    t = now.time()
    if start <= end:
        ok = start <= t <= end
    else:  # window crosses midnight
        ok = t >= start or t <= end
    return ok, f"now={t.strftime('%H:%M')} window={start_s}-{end_s}"


_START_RE = re.compile(r"Starting scan of \d+ tickers")
_DONE_RE = re.compile(r"Scan #\d+ complete|Scan failed")


def scan_in_flight(scanner_log):
    """True if the scheduler log shows a scan started but not yet finished.
    Errs on the side of 'in flight' if the log cannot be read."""
    try:
        with open(scanner_log, "rb") as f:
            f.seek(0, os.SEEK_END)
            f.seek(max(0, f.tell() - 262144))
            tail = f.read().decode("utf-8", errors="replace")
    except OSError as e:
        return True, f"cannot read scanner log {scanner_log}: {e}"
    last_start = last_done = -1
    for i, line in enumerate(tail.splitlines()):
        if _START_RE.search(line):
            last_start = i
        elif _DONE_RE.search(line):
            last_done = i
    if last_start > last_done:
        return True, "scanner log shows a scan in progress"
    return False, "no scan in flight"


def disk_ok(db_path):
    """Free disk on the DB filesystem must exceed the current DB size
    (room for VACUUM INTO output + pre-prune backup headroom)."""
    db_size = os.path.getsize(db_path)
    free = shutil.disk_usage(os.path.dirname(os.path.abspath(db_path))).free
    return free >= db_size, db_size, free


# ─────────────────────────────────────────────────────────────────────────────
# Plan (pure reads — used by dry-run and as the pre-flight for commit)
# ─────────────────────────────────────────────────────────────────────────────

def compute_cutoffs(conn, cfg, now=None):
    now = now or dt.datetime.now()
    fmt = "%Y-%m-%d %H:%M:%S"
    full_cutoff_ts = (now - dt.timedelta(days=cfg["scores_full_days"])).strftime(fmt)
    daily_cutoff_ts = (now - dt.timedelta(days=cfg["scores_daily_days"])).strftime(fmt)
    signals_cutoff_ts = (now - dt.timedelta(days=cfg["signals_days"])).strftime(fmt)
    row = conn.execute(
        "SELECT MAX(id) AS id FROM scans WHERE timestamp < ?", (signals_cutoff_ts,)
    ).fetchone()
    signals_cutoff_id = row["id"] if row and row["id"] else 0
    return {
        "full_cutoff_ts": full_cutoff_ts,
        "daily_cutoff_ts": daily_cutoff_ts,
        "signals_cutoff_ts": signals_cutoff_ts,
        "signals_cutoff_id": signals_cutoff_id,
    }


def all_table_counts(conn):
    tables = [r["name"] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    return {t: conn.execute(f"SELECT COUNT(*) FROM \"{t}\"").fetchone()[0] for t in tables}


def protected_fingerprint(conn):
    """Counts for every protected table, plus a content checksum on the
    forward-test journal (options_plays) — the rows that must never change."""
    fp = {t: n for t, n in all_table_counts(conn).items() if t not in PRUNABLE_TABLES}
    row = conn.execute("""
        SELECT COUNT(*) AS n, COALESCE(SUM(id), 0) AS id_sum,
               COALESCE(SUM(CASE WHEN status = 'open' THEN 1 ELSE 0 END), 0) AS open_n
        FROM options_plays
    """).fetchone()
    fp["_options_plays_checksum"] = (row["n"], row["id_sum"], row["open_n"])
    return fp


def table_bytes(conn):
    """Per-table bytes via dbstat when available (CLI builds have it; some
    Python builds do not). Returns {} if unavailable."""
    try:
        rows = conn.execute(
            "SELECT name, SUM(pgsize) AS b FROM dbstat GROUP BY name").fetchall()
        return {r["name"]: r["b"] for r in rows}
    except sqlite3.Error:
        return {}


def build_plan(conn, cfg, now=None):
    now = now or dt.datetime.now()
    cuts = compute_cutoffs(conn, cfg, now)
    params = {k: cuts[k] for k in ("full_cutoff_ts", "daily_cutoff_ts")}

    scores_total = conn.execute("SELECT COUNT(*) FROM scores").fetchone()[0]
    scores_del = conn.execute(
        f"SELECT COUNT(*) FROM scores WHERE scan_id NOT IN ({KEEP_SCANS_SQL})", params
    ).fetchone()[0]
    scores_recent = conn.execute(
        "SELECT COUNT(*) FROM scores WHERE scan_id IN "
        "(SELECT id FROM scans WHERE timestamp >= ?)", (cuts["full_cutoff_ts"],)
    ).fetchone()[0]
    score_days = conn.execute(
        "SELECT COUNT(DISTINCT date(sc.timestamp)) FROM scores s "
        "JOIN scans sc ON s.scan_id = sc.id").fetchone()[0]

    signals_total = conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0]
    signals_del = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE scan_id <= ?",
        (cuts["signals_cutoff_id"],)).fetchone()[0]

    tb = table_bytes(conn)
    est_bytes = 0
    if tb:
        if scores_total:
            est_bytes += int(tb.get("scores", 0) * scores_del / scores_total)
        if signals_total:
            est_bytes += int(tb.get("signals", 0) * signals_del / signals_total)

    return {
        "now": now.strftime("%Y-%m-%d %H:%M:%S"),
        "cutoffs": cuts,
        "scores_total": scores_total,
        "scores_delete": scores_del,
        "scores_keep": scores_total - scores_del,
        "scores_recent_window": scores_recent,
        "score_days_represented": score_days,
        "signals_total": signals_total,
        "signals_delete": signals_del,
        "signals_keep": signals_total - signals_del,
        "est_bytes_freed": est_bytes,
        "protected": protected_fingerprint(conn),
        "db_bytes": os.path.getsize(cfg["db_path"]) if os.path.exists(cfg["db_path"]) else 0,
    }


def print_plan(plan, cfg):
    c = plan["cutoffs"]
    log.info("Prune plan (computed %s)", plan["now"])
    log.info("  policy: full granularity >= %s | daily keepers >= %s | weekly before that | signals after scan_id %s",
             c["full_cutoff_ts"], c["daily_cutoff_ts"], c["signals_cutoff_id"])
    log.info("  scores : %s rows total -> delete %s, keep %s (recent full window: %s rows)",
             f"{plan['scores_total']:,}", f"{plan['scores_delete']:,}",
             f"{plan['scores_keep']:,}", f"{plan['scores_recent_window']:,}")
    log.info("  signals: %s rows total -> delete %s, keep %s",
             f"{plan['signals_total']:,}", f"{plan['signals_delete']:,}",
             f"{plan['signals_keep']:,}")
    if plan["est_bytes_freed"]:
        log.info("  estimated bytes freed by VACUUM: %.0f MB", plan["est_bytes_freed"] / 1048576)
    else:
        log.info("  (dbstat unavailable in this Python build - no byte estimate)")
    log.info("  PROTECTED (asserted unchanged): %s",
             ", ".join(f"{t}={n}" for t, n in sorted(plan["protected"].items())
                       if not t.startswith("_")))
    n, id_sum, open_n = plan["protected"]["_options_plays_checksum"]
    log.info("  options_plays journal checksum: rows=%s id_sum=%s open=%s", n, id_sum, open_n)


# ─────────────────────────────────────────────────────────────────────────────
# Backup
# ─────────────────────────────────────────────────────────────────────────────

def make_backup(db_path, backup_dir):
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = os.path.join(backup_dir, f"{BACKUP_PREFIX}{ts}.bak")
    log.info("Backing up %s -> %s (online backup API)", db_path, dest)
    src = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=60)
    dst = sqlite3.connect(dest)
    try:
        src.backup(dst)
        # The destination inherits WAL mode from the source; fold any WAL
        # content into the .bak itself so the single file is the backup.
        dst.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    finally:
        dst.close()
        src.close()
    return dest


def verify_backup(backup_path, expected_plays):
    conn = get_conn(backup_path, ro=True)
    try:
        ok = conn.execute("PRAGMA quick_check").fetchone()[0] == "ok"
        plays = conn.execute("SELECT COUNT(*) FROM options_plays").fetchone()[0]
    finally:
        conn.close()
    if not ok:
        return False, "quick_check failed"
    if plays != expected_plays:
        return False, f"options_plays count {plays} != source {expected_plays}"
    return True, "ok"


def rotate_backups(backup_dir, keep):
    if keep <= 0:
        return
    # Match only the .bak files themselves — a backup's -wal/-shm sidecars
    # share the prefix and must not count toward (or survive) rotation.
    backups = sorted(
        f for f in os.listdir(backup_dir)
        if f.startswith(BACKUP_PREFIX) and f.endswith(".bak"))
    for old in backups[:-keep]:
        log.info("Rotating out old pre-prune backup %s", old)
        for name in (old, old + "-wal", old + "-shm"):
            path = os.path.join(backup_dir, name)
            if os.path.exists(path):
                os.remove(path)


# ─────────────────────────────────────────────────────────────────────────────
# Execute
# ─────────────────────────────────────────────────────────────────────────────

class PruneAssertionError(RuntimeError):
    pass


def execute_prune(conn, cfg, now=None):
    """Run the deletes in one transaction; verify every protected invariant
    BEFORE commit; roll back on any violation. Returns stats dict."""
    now = now or dt.datetime.now()
    cuts = compute_cutoffs(conn, cfg, now)
    params = {k: cuts[k] for k in ("full_cutoff_ts", "daily_cutoff_ts")}

    pre_protected = protected_fingerprint(conn)
    pre_recent = conn.execute(
        "SELECT COUNT(*) FROM scores WHERE scan_id IN "
        "(SELECT id FROM scans WHERE timestamp >= ?)", (cuts["full_cutoff_ts"],)
    ).fetchone()[0]
    pre_days = conn.execute(
        "SELECT COUNT(DISTINCT date(sc.timestamp)) FROM scores s "
        "JOIN scans sc ON s.scan_id = sc.id WHERE sc.timestamp >= ?",
        (cuts["daily_cutoff_ts"],)).fetchone()[0]
    pre_weeks = conn.execute(
        "SELECT COUNT(DISTINCT strftime('%Y-%W', sc.timestamp)) FROM scores s "
        "JOIN scans sc ON s.scan_id = sc.id WHERE sc.timestamp < ?",
        (cuts["daily_cutoff_ts"],)).fetchone()[0]
    pre_signals_recent = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE scan_id > ?",
        (cuts["signals_cutoff_id"],)).fetchone()[0]

    conn.execute("BEGIN IMMEDIATE")
    try:
        scores_deleted = conn.execute(
            f"DELETE FROM scores WHERE scan_id NOT IN ({KEEP_SCANS_SQL})", params
        ).rowcount
        signals_deleted = conn.execute(
            "DELETE FROM signals WHERE scan_id <= ?", (cuts["signals_cutoff_id"],)
        ).rowcount

        # ── Assertions: every one must hold or the whole prune rolls back ──
        post_protected = protected_fingerprint(conn)
        if post_protected != pre_protected:
            diff = {k: (pre_protected.get(k), post_protected.get(k))
                    for k in set(pre_protected) | set(post_protected)
                    if pre_protected.get(k) != post_protected.get(k)}
            raise PruneAssertionError(f"protected rows changed: {diff}")

        post_recent = conn.execute(
            "SELECT COUNT(*) FROM scores WHERE scan_id IN "
            "(SELECT id FROM scans WHERE timestamp >= ?)", (cuts["full_cutoff_ts"],)
        ).fetchone()[0]
        if post_recent != pre_recent:
            raise PruneAssertionError(
                f"full-granularity window touched: {pre_recent} -> {post_recent}")

        post_days = conn.execute(
            "SELECT COUNT(DISTINCT date(sc.timestamp)) FROM scores s "
            "JOIN scans sc ON s.scan_id = sc.id WHERE sc.timestamp >= ?",
            (cuts["daily_cutoff_ts"],)).fetchone()[0]
        if post_days != pre_days:
            raise PruneAssertionError(
                f"daily coverage lost: {pre_days} -> {post_days} scan-days with scores")

        post_weeks = conn.execute(
            "SELECT COUNT(DISTINCT strftime('%Y-%W', sc.timestamp)) FROM scores s "
            "JOIN scans sc ON s.scan_id = sc.id WHERE sc.timestamp < ?",
            (cuts["daily_cutoff_ts"],)).fetchone()[0]
        if post_weeks != pre_weeks:
            raise PruneAssertionError(
                f"weekly coverage lost: {pre_weeks} -> {post_weeks} scan-weeks with scores")

        post_signals_recent = conn.execute(
            "SELECT COUNT(*) FROM signals WHERE scan_id > ?",
            (cuts["signals_cutoff_id"],)).fetchone()[0]
        if post_signals_recent != pre_signals_recent:
            raise PruneAssertionError(
                f"recent signals touched: {pre_signals_recent} -> {post_signals_recent}")

        conn.commit()
    except Exception:
        conn.rollback()
        raise

    return {"scores_deleted": scores_deleted, "signals_deleted": signals_deleted,
            "cutoffs": cuts}


# ─────────────────────────────────────────────────────────────────────────────
# VACUUM INTO + atomic swap
# ─────────────────────────────────────────────────────────────────────────────

def systemctl(action, services):
    for svc in services:
        log.info("systemctl %s %s", action, svc)
        subprocess.run(["systemctl", action, svc], check=True, timeout=120)


def vacuum_swap(cfg, expected_counts):
    """VACUUM INTO a new file, verify it, atomically swap it in.
    Caller is responsible for having stopped the services first."""
    db_path = cfg["db_path"]
    tmp = db_path + ".vacuum.tmp"
    if os.path.exists(tmp):
        os.remove(tmp)

    conn = get_conn(db_path)
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        log.info("VACUUM INTO %s ...", tmp)
        t0 = time.time()
        conn.execute("VACUUM INTO ?", (tmp,))
        log.info("VACUUM INTO done in %.1fs", time.time() - t0)
    finally:
        conn.close()

    # Verify the new file before it replaces anything
    vconn = get_conn(tmp, ro=True)
    try:
        if vconn.execute("PRAGMA quick_check").fetchone()[0] != "ok":
            raise RuntimeError("vacuumed file failed quick_check; live DB untouched")
        for table, expected in expected_counts.items():
            got = vconn.execute(f"SELECT COUNT(*) FROM \"{table}\"").fetchone()[0]
            if got != expected:
                raise RuntimeError(
                    f"vacuumed file {table} count {got} != expected {expected}; live DB untouched")
    finally:
        vconn.close()

    old_size = os.path.getsize(db_path)
    new_size = os.path.getsize(tmp)
    os.replace(tmp, db_path)
    # Stale WAL/SHM belong to the replaced inode; remove so SQLite does not
    # try to recover a mismatched WAL into the fresh file.
    for suffix in ("-wal", "-shm"):
        leftover = db_path + suffix
        if os.path.exists(leftover):
            os.remove(leftover)
    log.info("Swapped in vacuumed DB: %.0f MB -> %.0f MB (freed %.0f MB)",
             old_size / 1048576, new_size / 1048576, (old_size - new_size) / 1048576)
    return old_size, new_size


# ─────────────────────────────────────────────────────────────────────────────
# Notification (existing alert path: intel/notifier SendGrid HTTPS; emoji-free)
# ─────────────────────────────────────────────────────────────────────────────

def notify(cfg, subject, body):
    if not cfg.get("notify"):
        return
    try:
        sys.path.insert(0, cfg["api_dir"])
        from intel.notifier import _send  # noqa: PLC0415
        _send(subject, f"<pre>{body}</pre>")
        log.info("Notification sent: %s", subject)
    except Exception as e:  # never let notification failure mask the result
        log.warning("Notification failed (%s): %s", subject, e)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def run(cfg, commit, auto, no_vacuum, assume_idle):
    db_path = cfg["db_path"]
    if not os.path.exists(db_path):
        log.error("DB not found: %s", db_path)
        return 2

    db_mb = os.path.getsize(db_path) / 1048576
    if auto and db_mb <= cfg["size_threshold_mb"]:
        log.info("DB %.0f MB <= threshold %s MB - nothing to do", db_mb, cfg["size_threshold_mb"])
        return 0

    # ── Guards ──
    ok, db_size, free = disk_ok(db_path)
    if not ok:
        log.error("GUARD: free disk %.0f MB < DB size %.0f MB - refusing",
                  free / 1048576, db_size / 1048576)
        notify(cfg, "CyberScreener DB prune refused", "Insufficient free disk for safe prune.")
        return 1

    if not assume_idle:
        idle, why = in_idle_window(cfg)
        if not idle:
            log.error("GUARD: outside idle window (%s) - refusing", why)
            return 1
        busy, why = scan_in_flight(cfg["scanner_log"])
        if busy:
            log.error("GUARD: %s - refusing (cardinal rule: never mid-scan)", why)
            return 1
        log.info("Guards passed: idle window ok, no scan in flight, disk ok")

    conn = get_conn(db_path, ro=True)
    try:
        plan = build_plan(conn, cfg)
    finally:
        conn.close()
    print_plan(plan, cfg)

    if plan["scores_delete"] == 0 and plan["signals_delete"] == 0:
        log.info("Nothing to prune - DB already conforms to policy")
        return 0

    if not commit:
        log.info("DRY RUN - no changes made. Re-run with --commit to apply.")
        return 0

    # ── Backup (before any delete) ──
    backup = make_backup(db_path, cfg["backup_dir"])
    ok, why = verify_backup(backup, plan["protected"]["_options_plays_checksum"][0])
    if not ok:
        log.error("Backup verification failed (%s) - aborting before any delete", why)
        return 2
    log.info("Backup verified: %s (%.0f MB)", backup, os.path.getsize(backup) / 1048576)

    # ── Prune (transactional, asserted) ──
    conn = get_conn(db_path)
    try:
        stats = execute_prune(conn, cfg)
    except PruneAssertionError as e:
        log.error("ASSERTION FAILED, rolled back, DB unchanged: %s", e)
        notify(cfg, "CyberScreener DB prune failed", f"Assertion failed, rolled back: {e}")
        return 2
    finally:
        conn.close()
    log.info("Deleted %s score rows, %s signal rows (committed)",
             f"{stats['scores_deleted']:,}", f"{stats['signals_deleted']:,}")

    # ── VACUUM INTO + swap (brief service stop) ──
    freed = None
    if not no_vacuum:
        vconn = get_conn(db_path, ro=True)
        try:
            expected = {t: c for t, c in all_table_counts(vconn).items()}
        finally:
            vconn.close()
        manage = cfg["manage_services"] and not assume_idle
        try:
            if manage:
                systemctl("stop", cfg["services"])
            old_size, new_size = vacuum_swap(cfg, expected)
            freed = old_size - new_size
        finally:
            if manage:
                systemctl("start", cfg["services"])

    rotate_backups(cfg["backup_dir"], cfg["backup_keep"])

    summary = (
        f"Pruned {stats['scores_deleted']:,} score rows and "
        f"{stats['signals_deleted']:,} signal rows.\n"
        f"Backup: {backup}\n"
        + (f"DB file: {old_size / 1048576:.0f} MB -> {new_size / 1048576:.0f} MB "
           f"(freed {freed / 1048576:.0f} MB)\n" if freed is not None else
           "VACUUM skipped (--no-vacuum); space will be reused, file not shrunk.\n")
        + "Protected tables verified unchanged (options_plays journal intact)."
    )
    log.info("%s", summary.replace("\n", " | "))
    notify(cfg, "CyberScreener DB prune completed", summary)
    return 0


def main():
    p = argparse.ArgumentParser(description="CyberScreener DB prune (dry-run by default)")
    p.add_argument("--config", default=os.path.join(os.path.dirname(__file__), "db_prune_config.json"))
    p.add_argument("--db", help="override db_path")
    p.add_argument("--commit", action="store_true", help="actually prune (default: dry run)")
    p.add_argument("--auto", action="store_true",
                   help="threshold mode: exit 0 quietly unless DB > size_threshold_mb")
    p.add_argument("--threshold-mb", type=int, help="override size_threshold_mb")
    p.add_argument("--no-vacuum", action="store_true", help="prune only, skip VACUUM INTO swap")
    p.add_argument("--assume-idle", action="store_true",
                   help="skip idle/scan-lock/service guards - offline copies ONLY")
    args = p.parse_args()

    cfg = load_config(args.config)
    if args.db:
        cfg["db_path"] = args.db
    if args.threshold_mb:
        cfg["size_threshold_mb"] = args.threshold_mb
    setup_logging(cfg["log_file"])

    try:
        rc = run(cfg, commit=args.commit, auto=args.auto,
                 no_vacuum=args.no_vacuum, assume_idle=args.assume_idle)
    except Exception as e:
        log.exception("Prune failed: %s", e)
        notify(cfg, "CyberScreener DB prune failed", str(e))
        rc = 2
    sys.exit(rc)


if __name__ == "__main__":
    main()
