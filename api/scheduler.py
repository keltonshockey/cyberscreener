"""
Scheduler — runs scans on a schedule and saves to DB.

Usage:
  python scheduler.py                  # Run once now
  python scheduler.py --daemon         # Run on schedule (weekdays at market close)
  python scheduler.py --interval 3600  # Run every N seconds
"""

import sys
import time
import argparse
import logging
import threading
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.scanner import run_scan, ALL_TICKERS
from db.models import init_db, save_scan, get_scan_count, get_open_plays, close_play, get_nearest_price, get_db
try:
    from intel.notifier import notify_momentum_digest, notify_top_plays_digest
    NOTIFIER_AVAILABLE = True
except ImportError:
    NOTIFIER_AVAILABLE = False

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("scanner.log"),
    ]
)
logger = logging.getLogger(__name__)


def run_scheduled_scan():
    """Execute a full scan and save results to database."""
    logger.info(f"Starting scan of {len(ALL_TICKERS)} tickers...")
    start = time.time()

    def log_progress(ticker, i, total):
        if (i + 1) % 5 == 0 or i == 0:
            logger.info(f"  Scanning {ticker} ({i+1}/{total})")

    results = run_scan(
        callback=log_progress,
        enable_sec=True,
        enable_sentiment=True,
    )
    duration = time.time() - start

    if results:
        scan_id, momentum_events = save_scan(
            results,
            intel_layers=["sec", "sentiment", "whale"],
            duration_seconds=duration,
        )
        logger.info(f"✅ Scan #{scan_id} complete: {len(results)} tickers in {duration:.1f}s "
                     f"(total scans in DB: {get_scan_count()})")
        if momentum_events:
            logger.info(f"🔥 {len(momentum_events)} momentum event(s) detected")
            if NOTIFIER_AVAILABLE:
                try:
                    notify_momentum_digest(momentum_events)
                except Exception as ne:
                    logger.warning(f"Momentum notification failed: {ne}")

        # Pre-warm play cache for top killer play tickers
        threading.Thread(target=_prewarm_killer_plays, daemon=True).start()

        # Morning digest: send top plays once per day at first scan after 9:30 AM ET
        now = datetime.now()
        if NOTIFIER_AVAILABLE and now.hour == 9 and now.minute >= 30:
            try:
                notify_top_plays_digest(results)
                logger.info("📧 Morning digest sent")
            except Exception as de:
                logger.warning(f"Morning digest failed: {de}")
    else:
        logger.error("❌ Scan failed — no results returned.")


def _prewarm_killer_plays():
    """
    After a scan, pre-generate plays for the top killer play tickers so users
    clicking from the dashboard get instant results instead of a 15-30s wait.
    Fires async HTTP POSTs to the local API — best-effort, never blocks the scan.
    """
    try:
        import requests
        conn = get_db()
        rows = conn.execute("""
            SELECT s.ticker, (s.opt_score * 0.6 + s.lt_score * 0.4) AS combined
            FROM scores s
            INNER JOIN (
                SELECT ticker, MAX(scan_id) AS max_scan_id FROM scores GROUP BY ticker
            ) latest ON s.ticker = latest.ticker AND s.scan_id = latest.max_scan_id
            WHERE (s.opt_score >= 45 OR s.lt_score >= 55)
            ORDER BY combined DESC
            LIMIT 6
        """).fetchall()
        conn.close()
        tickers = [r[0] for r in rows]

        def _fire(ticker):
            try:
                requests.post(f"http://localhost:8000/plays/{ticker}/generate", timeout=120)
                logger.info(f"🎯 Pre-warmed plays for {ticker}")
            except Exception as e:
                logger.debug(f"Play pre-warm for {ticker} failed: {e}")

        for t in tickers:
            threading.Thread(target=_fire, args=(t,), daemon=True).start()

        logger.info(f"🎯 Triggered play pre-warm for: {', '.join(tickers)}")
    except Exception as e:
        logger.warning(f"Play pre-warm setup failed: {e}")


def _check_play_outcomes():
    """
    P2: Close expired plays and estimate P&L.
    Runs once daily around market close (4 PM).
    Uses stored price snapshots + ~4x ATM options leverage estimate.
    """
    today = datetime.now().strftime("%Y-%m-%d")
    open_plays = get_open_plays(days_old=180)
    closed = 0
    for play in open_plays:
        expiry = play.get("expiry")
        if not expiry:
            continue
        # Close plays whose expiry has passed
        if expiry <= today:
            ticker = play["ticker"]
            entry_price = play.get("entry_price")
            direction = play.get("direction", "bullish")
            # Get the price nearest to expiry
            outcome_price = get_nearest_price(ticker, expiry, window_days=5)
            if outcome_price and entry_price and entry_price > 0:
                pct_move = (outcome_price - entry_price) / entry_price * 100
                dir_sign = 1 if direction == "bullish" else -1
                # ATM options rough leverage: ~4x the underlying move
                pnl_pct = round(pct_move * dir_sign * 4, 1)
                close_play(
                    play_id=play["id"],
                    outcome_price=outcome_price,
                    pnl_pct=pnl_pct,
                    outcome_date=today,
                )
                closed += 1
            else:
                # No price data available — close as expired with null P&L
                close_play(
                    play_id=play["id"],
                    outcome_price=None,
                    pnl_pct=None,
                    outcome_date=today,
                )
                closed += 1

    if closed > 0:
        logger.info(f"📊 Play outcome check: closed {closed} expired plays")


def _prune_and_checkpoint():
    """
    Nightly maintenance: delete scores older than 6 months (keep weekly snapshots),
    then run WAL checkpoint to reclaim disk space.
    At ~100MB/month growth, without pruning the 1GB droplet fills by August.
    """
    conn = get_db()
    # Find the scan_id cutoff: last scan before the 6-month window
    cutoff_row = conn.execute(
        "SELECT MAX(id) as id FROM scans WHERE timestamp < date('now', '-180 days')"
    ).fetchone()
    cutoff_id = cutoff_row["id"] if cutoff_row and cutoff_row["id"] else None

    if cutoff_id:
        # Keep one scan per week (the last scan of each ISO week) beyond the cutoff
        weekly_keepers = conn.execute("""
            SELECT MAX(id) as id FROM scans
            WHERE id <= ? AND timestamp < date('now', '-180 days')
            GROUP BY strftime('%Y-%W', timestamp)
        """, (cutoff_id,)).fetchall()
        keeper_ids = {r["id"] for r in weekly_keepers if r["id"]}

        # Delete scores from old scans that aren't weekly keepers
        if keeper_ids:
            placeholders = ",".join("?" * len(keeper_ids))
            deleted = conn.execute(
                f"DELETE FROM scores WHERE scan_id <= ? AND scan_id NOT IN ({placeholders})",
                (cutoff_id, *keeper_ids)
            ).rowcount
        else:
            deleted = conn.execute(
                "DELETE FROM scores WHERE scan_id <= ?", (cutoff_id,)
            ).rowcount

        conn.commit()
        logger.info(f"🗑️  Pruned {deleted} old score rows (kept weekly snapshots)")
    else:
        logger.info("🗑️  Prune: no records old enough to prune yet")

    # WAL checkpoint — merges WAL into main DB file and truncates it
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    logger.info("✅ WAL checkpoint complete")


def is_market_hours():
    """Check if we're in a reasonable window for scanning (weekday, not too early/late)."""
    now = datetime.now()
    # Skip weekends
    if now.weekday() >= 5:
        return False
    # Only scan between 6 AM and 10 PM
    if now.hour < 6 or now.hour > 22:
        return False
    return True


def daemon_loop(interval_seconds=3600):
    """Run scans on a loop."""
    logger.info(f"Starting scheduler daemon (interval: {interval_seconds}s)")
    logger.info(f"Tracking {len(ALL_TICKERS)} tickers")

    _last_outcome_check_day: str = ""
    _last_prune_day: str = ""

    while True:
        try:
            if is_market_hours():
                run_scheduled_scan()
            else:
                logger.info("Outside market hours, skipping scan.")

            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")

            # Nightly play outcome check at ~4 PM (market close)
            if now.hour == 16 and _last_outcome_check_day != today_str:
                try:
                    _last_outcome_check_day = today_str
                    _check_play_outcomes()
                except Exception as oc_err:
                    logger.error(f"Outcome check error: {oc_err}")

            # Nightly DB prune + WAL checkpoint at ~2 AM — keeps DB under control
            if now.hour == 2 and _last_prune_day != today_str:
                try:
                    _last_prune_day = today_str
                    _prune_and_checkpoint()
                except Exception as pe:
                    logger.error(f"Prune/checkpoint error: {pe}")

        except Exception as e:
            logger.error(f"Scan error: {e}")

        logger.info(f"Next scan in {interval_seconds}s...")
        time.sleep(interval_seconds)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="CyberScreener Scheduler")
    parser.add_argument("--daemon", action="store_true", help="Run in daemon mode")
    parser.add_argument("--interval", type=int, default=3600, help="Seconds between scans (default: 3600)")
    args = parser.parse_args()

    init_db()

    if args.daemon:
        daemon_loop(args.interval)
    else:
        run_scheduled_scan()
