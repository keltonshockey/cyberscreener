#!/usr/bin/env python3
"""
Supervised backfill for the forward-test journal (options_plays).

DRY-RUN BY DEFAULT. Live writes only with --commit, run by the operator.

Steps (each idempotent, in order):
  1. Schema migration — settlement_v2 columns (additive ALTERs only).
  2. Entry-conviction backfill — fills entry_conviction from the scores table
     as of each play's generated_at (contemporaneous, no look-ahead). The
     journal filed lt_score=opt_score=0 on every row before the logging fix.
  3. (--migrate-legacy) Recompute rows closed by the legacy directional x4
     heuristic under the pre-registered settlement_v2 semantics; legacy
     values preserved in notes.
  4. Close due plays — open plays strictly past expiry: closed / pending
     (within the 10-day price grace) / unresolvable. Outcomes are never
     fabricated for data-missing plays.
  5. Gate metrics — win rate + profit factor by entry-conviction bucket over
     DISTINCT closed plays (earliest row per ticker/strategy/strike/expiry).

Usage:
  python3 scripts/backfill_play_closure.py --db /path/to/copy.db          # dry run
  python3 scripts/backfill_play_closure.py --db /app/data/cyberscreener.db --commit --migrate-legacy
"""
import argparse
import json
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "api"))


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.environ.get("CYBERSCREENER_DB",
                                                   "/app/data/cyberscreener.db"))
    ap.add_argument("--commit", action="store_true",
                    help="Apply writes (default: dry run, no changes)")
    ap.add_argument("--migrate-legacy", action="store_true",
                    help="Recompute legacy-closed rows under settlement_v2")
    ap.add_argument("--verbose", action="store_true", help="Print per-play details")
    args = ap.parse_args()
    dry = not args.commit

    # Import after sys.path setup; avoid db.models so DB_PATH env is irrelevant
    from core.play_closure import (close_due_plays, migrate_legacy_closures,
                                   backfill_entry_conviction, gate_metrics)
    from db.migrate_play_closure import COLUMNS

    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    print(f"DB: {args.db}  mode: {'COMMIT' if args.commit else 'DRY RUN'}")

    # 1. schema (additive; runs even in dry mode on a copy — refuse on live)
    existing = {r[1] for r in conn.execute("PRAGMA table_info(options_plays)")}
    missing = [c for c, t in COLUMNS if c not in existing]
    if missing and dry and args.db.startswith("/app/data/"):
        print(f"DRY RUN on live DB: schema columns missing {missing}; "
              f"re-run with --commit to add them (additive ALTER only). "
              f"Continuing with computable steps skipped.")
        return 1
    for col in missing:
        coltype = dict(COLUMNS)[col]
        conn.execute(f"ALTER TABLE options_plays ADD COLUMN {col} {coltype}")
    if missing:
        print(f"Schema: added {missing}")
    else:
        print("Schema: already migrated")

    # 2. conviction backfill
    conv = backfill_entry_conviction(conn, dry_run=dry)
    print(f"Conviction backfill: {json.dumps(conv)}")

    # 3. legacy migration
    if args.migrate_legacy:
        leg = migrate_legacy_closures(conn, dry_run=dry)
        print(f"Legacy migration: candidates={leg['candidates']} "
              f"migrated={leg['migrated']} unresolvable={leg['unresolvable']} "
              f"errors={leg['errors']}")
        if args.verbose:
            for d in leg["details"]:
                print(f"  {json.dumps(d)}")

    # 4. closure
    s = close_due_plays(conn, dry_run=dry)
    print(f"Closure: due={s['due']} closed={s['closed']} "
          f"unresolvable={s['unresolvable']} pending={s['pending']} "
          f"errors={s['errors']}")
    if args.verbose:
        for d in s["details"]:
            print(f"  {json.dumps(d)}")

    # 5. gate metrics (read-only; in dry mode reflects current DB state only)
    print("\nGate metrics over DISTINCT closed plays "
          "(win/EV defs: api/core/FORWARD_TEST_SEMANTICS.md):")
    print(json.dumps(gate_metrics(conn), indent=2))

    if dry:
        conn.rollback()
        print("\nDRY RUN — no changes written.")
    conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
