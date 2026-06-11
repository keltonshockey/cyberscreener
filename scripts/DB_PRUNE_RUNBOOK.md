# DB Prune — Operator Runbook

The prune is **retention-based, not a wipe**. It never touches the forward-test
journal (`options_plays`), `prices` (play outcomes are finalized from prices),
`scans`, `score_weights`, or any auth/user table — and it asserts that inside
the transaction, rolling back if any protected row would change.

**Policy** (see `db_prune_config.json`):

| Data | Window | Kept |
|---|---|---|
| `scores` | last 30 days | every scan (full intraday granularity) |
| `scores` | 31–365 days | last scan of each calendar day |
| `scores` | older | last scan of each ISO week |
| `signals` | last 30 days | everything |
| `signals` | older | deleted |
| everything else | forever | untouched (asserted) |

Why this is safe for the learning loop: calibration builds (score, forward-return)
pairs keyed on the **date** of the scan and gets returns from `prices` — multiple
intraday scans collapse to near-duplicate pairs. IV rank (`get_iv_history`, 365 d)
takes min/max over daily values. No reader needs intraday rows older than 30 days.
The decade PIT backtest corpus lives on **mill** (`~/lt-recon-data/`) and is a
separate store — this prune cannot touch it.

## One-time manual run (do this once before enabling the timer)

All steps on the droplet (`ssh root@64.23.150.209`), **outside market hours**
(scans run 06:00–22:00 UTC weekdays and take ~35 min; safe window 23:00–05:30 UTC,
or any time on weekends).

```bash
# 0. Pull the branch / deploy so /opt/cyberscreener/scripts/db_prune.py exists
cd /opt/cyberscreener && git pull

# 1. Fresh backup exists? The script takes its own, but belt and braces:
ls -la /app/data/nightly.db.gz          # nightly 03:30 UTC cron backup

# 2. DRY RUN (default mode; zero writes) — review the output
python3 scripts/db_prune.py --config scripts/db_prune_config.json

# 3. Commit run — takes its own verified pre-prune backup first,
#    prunes transactionally, then VACUUM INTO + atomic swap with a
#    brief (~2-4 min) stop of the two services
python3 scripts/db_prune.py --config scripts/db_prune_config.json --commit

# 4. Verify
sqlite3 /app/data/cyberscreener.db "PRAGMA quick_check; SELECT COUNT(*) FROM options_plays;"
curl -s localhost:8000/health
ls -la /app/data/                        # new size + preprune backup present
tail -50 /var/log/cyberscreener-prune.log
```

## Enable the automation (after the manual run looks right)

```bash
cp /opt/cyberscreener/scripts/systemd/cyberscreener-prune.* /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now cyberscreener-prune.timer
systemctl list-timers cyberscreener-prune.timer
```

The timer fires daily 04:10 UTC (after the 03:30 nightly backup). The service
runs `--auto --commit`: it exits immediately unless the DB exceeds
`size_threshold_mb` (1700), and every guard (idle window, scan-in-flight,
disk space, backup, protected-row assertions) applies on every run.
Completion/failure is mailed via the existing SendGrid alert path (emoji-free).

## Rollback

The pre-prune backup is the rollback:

```bash
systemctl stop cyberscreener.service cyberscreener-scheduler.service
ls /app/data/cyberscreener.db.preprune.*          # pick the timestamp
cp /app/data/cyberscreener.db.preprune.<TS>.bak /app/data/cyberscreener.db
rm -f /app/data/cyberscreener.db-wal /app/data/cyberscreener.db-shm
systemctl start cyberscreener.service cyberscreener-scheduler.service
curl -s localhost:8000/health
```

## Guards (all enforced by the script, every run)

- Refuses outside the idle window (23:00–05:30 UTC weekdays; weekends OK).
- Refuses if `scanner.log` shows a scan in flight (fails closed if unreadable).
- Refuses if free disk < current DB size.
- Verified pre-prune backup before any delete; keeps the last 2, rotates older.
- All deletes in one transaction; protected tables (counts + `options_plays`
  content checksum), the full-granularity window, daily coverage, and weekly
  coverage are asserted **before COMMIT** — any violation rolls back everything.
- VACUUM INTO a temp file, `quick_check` + per-table count verification on the
  new file, then atomic `os.replace`. The live DB is never the thing being
  rewritten in place.
- Idempotent: a second run deletes 0 rows.
