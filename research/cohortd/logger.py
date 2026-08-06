#!/usr/bin/env python3
"""
Cohort D paper logger — the daily job.

Executes PREREG_COHORT_D.md exactly. It does not get to reinterpret the
registration: the entry threshold, structure, settlement math and verdict rules
all come from the prereg and are referenced by section here.

The job is safe to run every day. It acts only on:
  * the first trading day of a calendar month (entry evaluation, §5), and
  * any date on or after an open position's expiry (settlement, §6).
Every other day it does nothing and says so.

Isolation (§11): imports nothing from `api/`, never opens `cyberscreener.db`,
writes only `~/cs-research/cohortD.db`.

Usage:
    python -m research.cohortd.logger --dry-run        # decide + print, write NOTHING
    python -m research.cohortd.logger                  # live: records + notifies
    python -m research.cohortd.logger --report         # monthly read
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from research.cohortd import condor as cd  # noqa: E402
from research.cohortd import data, harrv, metrics, notify, store  # noqa: E402

# PREREG §5 — fixed at registration, never tuned.
ENTRY_THRESHOLD_VOL_POINTS = 2.0


def is_first_trading_day(day: dt.date, closes_index=None) -> bool:
    """
    First TRADING day of the month.

    Weekday-based: the first weekday of the month, which is the first trading
    day except when it is an exchange holiday. On such a month the live job's
    chain fetch returns no data and the cycle is recorded as a data-gap SKIP
    rather than silently vanishing.
    """
    if day.weekday() >= 5:
        return False
    d = day.replace(day=1)
    while d.weekday() >= 5:
        d += dt.timedelta(days=1)
    return day == d


def evaluate_entry(closes, iv30_points: float) -> dict:
    """
    The registered entry rule (§5):  IV30 − HAR_RV_21d >= 2.0 vol points.

    Returns the decision AND the computed inputs, because §5 requires skipped
    cycles to be logged with their values — an unrecorded rejection cannot be
    audited, and the rejection rate is a reported statistic (§7).
    """
    har = harrv.forecast_har(closes)
    garch = harrv.forecast_garch(closes)
    out = {
        "iv30": iv30_points,
        "har_ok": har["ok"],
        "har_forecast": har.get("forecast_vol_points"),
        "garch_forecast": garch.get("forecast_vol_points") if garch["ok"] else None,
        "garch_reason": None if garch["ok"] else garch.get("reason"),
        "threshold": ENTRY_THRESHOLD_VOL_POINTS,
    }
    if not har["ok"]:
        out.update(decision="SKIP", spread=None,
                   reason=f"HAR unavailable: {har.get('reason')}")
        return out
    spread = iv30_points - har["forecast_vol_points"]
    out["spread"] = spread
    out["har_detail"] = {k: har[k] for k in ("rv_d", "rv_w", "rv_m", "clamped")}
    if spread >= ENTRY_THRESHOLD_VOL_POINTS:
        out.update(decision="ENTER",
                   reason=f"spread {spread:.2f} >= {ENTRY_THRESHOLD_VOL_POINTS} vol points")
    else:
        out.update(decision="SKIP",
                   reason=f"spread {spread:.2f} < {ENTRY_THRESHOLD_VOL_POINTS} vol points")
    return out


def run_entry(conn, today, dry_run, quiet=False):
    """Evaluate (and, live, record) the entry decision for `today`."""
    key = today.isoformat()
    if conn is not None and store.has_cycle(conn, key):
        if not quiet:
            print(f"cycle {key} already recorded — no action (dedup, PREREG §11)")
        return None

    closes = data.fetch_closes()
    if not closes["ok"]:
        print(f"SKIP (data gap): {closes['reason']}")
        return None
    chain = data.fetch_chain(asof=today)
    if not chain["ok"]:
        print(f"SKIP (data gap): {chain['reason']}")
        return None
    iv = data.atm_iv30(chain["ticker"], chain["expiries_dte"], closes["spot"])
    if not iv["ok"]:
        print(f"SKIP (data gap): {iv['reason']}")
        return None

    decision = evaluate_entry(closes["closes"], iv["iv30_vol_points"])
    row = {"cycle_date": key, "decision": decision["decision"], "spot": closes["spot"],
           "iv30": decision["iv30"], "har_forecast": decision["har_forecast"],
           "garch_forecast": decision["garch_forecast"], "spread": decision["spread"],
           "threshold": ENTRY_THRESHOLD_VOL_POINTS, "notes": decision["reason"],
           "entered_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")}

    print(f"\ncycle date      : {key}")
    print(f"SPY spot        : {closes['spot']:.2f}  (closes through {closes['last_date']})")
    print(f"ATM IV30        : {decision['iv30']:.2f} vol points")
    print(f"HAR-RV 21d      : {decision['har_forecast']:.2f} vol points"
          if decision["har_forecast"] else "HAR-RV 21d      : unavailable")
    if decision["garch_forecast"]:
        print(f"GARCH(1,1) 21d  : {decision['garch_forecast']:.2f} vol points  (logged only, "
              "does NOT gate — PREREG §5)")
    elif decision["garch_reason"]:
        print(f"GARCH(1,1) 21d  : unavailable ({decision['garch_reason']}) — logged, not fatal")
    if decision["spread"] is not None:
        print(f"spread          : {decision['spread']:.2f} vol points "
              f"(threshold {ENTRY_THRESHOLD_VOL_POINTS})")
    print(f"DECISION        : {decision['decision']} — {decision['reason']}")

    if decision["decision"] == "ENTER":
        expiry = cd.choose_expiry(chain["expiries_dte"])
        if not expiry:
            print("SKIP: no expiry in the 30-45 DTE window")
            row.update(decision="SKIP", notes="no expiry in 30-45 DTE window")
        else:
            legs = data.fetch_expiry_legs(chain["ticker"], expiry)
            built = (cd.build_condor(closes["spot"], expiry, chain["expiries_dte"][expiry],
                                     legs["puts"], legs["calls"]) if legs["ok"] else None)
            if built is None:
                print("SKIP: could not build a complete condor from the chain")
                row.update(decision="SKIP", notes="incomplete condor from chain")
            else:
                row.update(built.as_dict())
                print(f"expiry          : {built.expiry} ({built.dte} DTE)")
                print(f"structure       : {built.long_put:g}P / {built.short_put:g}P  --  "
                      f"{built.short_call:g}C / {built.long_call:g}C")
                print(f"credit (mid)    : {built.credit:.2f}   widths "
                      f"{built.put_width:g}/{built.call_width:g}")
                print(f"defined risk    : {built.defined_risk:.2f}  "
                      "(mid-pricing is a KNOWN upward bias — PREREG §4)")

    if dry_run:
        print("\nDRY RUN — nothing written, no notification sent.")
        return row
    store.record_cycle(conn, row)
    notify.notify_and_log(
        f"Cohort D {key}: {row['decision']}"
        + (f" condor {row.get('expiry')} credit {row.get('credit'):.2f}"
           if row["decision"] == "ENTER" and row.get("credit") else "")
        + f" | IV30 {decision['iv30']:.1f} - HAR {decision['har_forecast'] or float('nan'):.1f}"
          f" = {decision['spread']:.1f}" if decision["spread"] is not None else "")
    return row


def run_settlements(conn, today, dry_run):
    """Settle any open position whose expiry has arrived (§6)."""
    rows = store.open_positions(conn, today.isoformat())
    if not rows:
        return 0
    closes = data.fetch_closes(period="6mo")
    if not closes["ok"]:
        print(f"settlement deferred (data gap): {closes['reason']}")
        return 0

    done = 0
    for r in rows:
        built = cd.Condor(expiry=r["expiry"], dte=r["dte"], short_put=r["short_put"],
                          long_put=r["long_put"], short_call=r["short_call"],
                          long_call=r["long_call"], credit=r["credit"],
                          put_width=r["put_width"], call_width=r["call_width"])
        s = cd.settle(built, closes["spot"])
        print(f"\nsettling {r['cycle_date']} (expiry {r['expiry']})")
        print(f"  settlement price : {s['settlement_price']:.2f}")
        print(f"  pnl              : {s['pnl']:+.2f}   R = {s['r_multiple']:+.3f}   "
              f"{'WIN' if s['win'] else 'LOSS'}")
        if dry_run:
            print("  DRY RUN — not written")
            continue
        if store.settle_cycle(conn, r["cycle_date"], s,
                              dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")):
            done += 1
            notify.notify_and_log(
                f"Cohort D settled {r['cycle_date']}: R {s['r_multiple']:+.3f} "
                f"({'win' if s['win'] else 'loss'}), SPY {s['settlement_price']:.2f}")
    return done


def run_report(conn):
    """Monthly read — every metric the prereg registered (§7, §8, §9, §10)."""
    rows = store.settled_rows(conn)
    c = store.counts(conn)
    m = metrics.summarize(rows)
    print("=" * 66)
    print("COHORT D READ — PREREG_COHORT_D.md")
    print("=" * 66)
    print(f"cycles evaluated : {c['cycles']}   entered {c['entered']}   skipped {c['skipped']}")
    if c["cycles"]:
        print(f"filter rejection : {c['skipped'] / c['cycles']:.1%}")
    print(f"settled          : {m['n']}")
    if m["n"]:
        lo, hi = m["win_rate_ci95"]
        elo, ehi = m["expectancy_ci95"]
        print(f"win rate         : {m['win_rate']:.1%}  Wilson 95% [{lo:.1%}, {hi:.1%}]")
        print(f"expectancy (R)   : {m['expectancy_r']:+.3f}  bootstrap 95% "
              f"[{elo:+.3f}, {ehi:+.3f}]")
        print(f"profit factor    : {m['profit_factor']:.2f}")
        print(f"max drawdown (R) : {m['max_drawdown_r']:+.2f}")
        print(f"total (R)        : {m['total_r']:+.2f}")
    print(f"\nVERDICT          : {m['verdict']}")
    if m["fail_stop_triggered"]:
        print("FAIL-STOP TRIGGERED (PREREG §10) — the cohort stops here.")
    print("\nReminder: credit is computed at mid (PREREG §4) — a KNOWN upward bias")
    print("versus realistic fills. Win rate alone is NOT a pass (PREREG §9).")
    return m


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    p.add_argument("--db", default=None, help=f"default {store.DEFAULT_DB}")
    p.add_argument("--date", default=None, help="evaluate as of this date (YYYY-MM-DD)")
    p.add_argument("--dry-run", action="store_true",
                   help="decide and print; write nothing, notify nothing")
    p.add_argument("--report", action="store_true", help="print the monthly read and exit")
    p.add_argument("--force-entry", action="store_true",
                   help="evaluate entry regardless of calendar position (dry-run diagnostics)")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)

    today = dt.date.fromisoformat(a.date) if a.date else dt.date.today()
    conn = None if a.dry_run else store.connect(a.db)

    if a.report:
        m = run_report(store.connect(a.db))
        if a.json:
            print(json.dumps(m, indent=2, default=str))
        return 0

    print(f"cohort D logger — {today} (cohort {store.COHORT_VERSION})"
          + ("  [DRY RUN]" if a.dry_run else ""))

    acted = False
    if is_first_trading_day(today) or a.force_entry:
        if a.force_entry and not is_first_trading_day(today):
            print("--force-entry: evaluating outside the registered entry date "
                  "(diagnostic only; the live job never does this)")
        run_entry(conn, today, a.dry_run)
        acted = True

    if conn is not None:
        n = run_settlements(conn, today, a.dry_run)
        if n:
            print(f"\nsettled {n} position(s)")
            acted = True

    if not acted:
        print("not an entry date and no expiries due — no action")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
