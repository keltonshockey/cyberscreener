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
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from core.scanner import run_scan, ALL_TICKERS
from db.models import init_db, save_scan, get_scan_count, get_open_plays, close_play, get_nearest_price
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

    while True:
        try:
            if is_market_hours():
                run_scheduled_scan()
            else:
                logger.info("Outside market hours, skipping scan.")

            # P2: Nightly play outcome check at ~4 PM (market close)
            now = datetime.now()
            today_str = now.strftime("%Y-%m-%d")
            if now.hour == 16 and _last_outcome_check_day != today_str:
                try:
                    _last_outcome_check_day = today_str
                    _check_play_outcomes()
                except Exception as oc_err:
                    logger.error(f"Outcome check error: {oc_err}")

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
