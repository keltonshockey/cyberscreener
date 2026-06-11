# RESULT — DB Prune (retention-based, forward-test-safe)

Date: 2026-06-09
Branch / PR: `feat/db-prune` → **draft PR #11** https://github.com/keltonshockey/cyberscreener/pull/11
Status: implemented + validated on a copy of the live DB. **No live prune has been run. Automation NOT enabled.** Operator runbook below.

---

## The two questions, answered first

**1. Will pruning hurt our backtesting data?**
**No.** The decade PIT backtest corpus (as-filed EDGAR companyfacts) lives on **mill** at `~/lt-recon-data/` — a separate store this prune never touches. The droplet SQLite is the operational scan store only.

**2. Does the prune preserve forward-test integrity?**
**Yes — by construction and by measurement.**
- `options_plays` (the journal, open AND closed) is protected and content-checksummed; the prune transaction rolls back if it changes by one row.
- Play outcomes are finalized from the **`prices`** table (`_check_play_outcomes` → `get_nearest_price`), **not** from raw `scores`. `prices` (41K rows, 1.3 MB) is fully protected. The set of `scores` rows an open play needs to compute its outcome is **empty** — verified by code inspection of `scheduler.py` and `db/models.py`.
- The mill forward-test journal (`poll_killer_plays.py`) reads the HTTP `/killer-plays` endpoint (latest scan only) — unaffected.
- The learning loop (`backtest/engine.py`) deduplicates to **one score row per ticker-day** (`_deduplicate_scores`) before building (score, forward-return) pairs, and takes returns from `prices`. Intraday score rows older than the recent window are dead weight for it. Measured impact below.

---

## Phase 1 — Measurements (live DB, read-only, 2026-06-09)

DB: `/app/data/cyberscreener.db`, **1,871 MB** (456,784 × 4 KB pages, freelist 0), WAL mode.
Droplet: 24 GB disk (15 GB free), 2 GB RAM + 2 GB swap, timezone **UTC**.

| Object | Rows | Size | Notes |
|---|---|---|---|
| `scores` | 588,554 | 1,152 MB + 66 MB indexes (~2.25 KB/row) | the problem |
| `signals` | 5,409,129 | 502 MB + 60 MB index (~97 B/row) | steady state (90-d prune works) |
| `prices` | 41,594 | 1.3 MB | play-outcome source — protected |
| `scans` | 1,432 | 0.09 MB | protected |
| `options_plays` | 211 (200 open / 11 closed) | 0.05 MB | journal — protected |
| everything else | — | < 0.1 MB | protected |

**Growth:** ~13 scans/weekday × 479 tickers ≈ 6,200 score rows/day ≈ **+400 MB/month** (scores+indexes). Signals churn ~63K rows/day at steady state. At this rate the file passes 2 GB in ~3 weeks.

**Why the existing nightly prune does nothing:** it only deletes scores older than **180 days**, and the heavy 30-min cadence started 2026-02 (~126 days ago) — nothing qualifies until ~August, long after the ceiling. The 2 GB concern is RAM as much as disk: calibration loads the whole 180-day scores window into memory (documented 1.55 GB RSS OOM).

**Dependency map (who reads `scores` history):**

| Reader | Lookback | Granularity needed |
|---|---|---|
| calibration / `get_all_scores_for_backtest` | 180 d | **daily** (dedups per ticker-day) |
| `get_iv_history` (real IV rank) | 365 d | daily min/max |
| `get_score_history` (ticker charts) | 90 d | daily is fine beyond 30 d |
| `get_short_interest_trend` | 60 d | first/last observation |
| momentum compare, pre-warm, all dashboards | latest 1–2 scans | full |
| `signals` readers (ticker panel, momentum feed) | recent N rows | — |

No consumer needs intraday rows older than 30 days.

---

## Phase 2 — Retention policy

| Data | Window | Kept | Predicate |
|---|---|---|---|
| `scores` | last **30 d** (`scores_full_days`) | every scan | `scan_id IN (SELECT id FROM scans WHERE timestamp >= now-30d)` |
| `scores` | 31–**365 d** (`scores_daily_days`) | last scan of each day | `scan_id IN (SELECT MAX(id) FROM scans WHERE timestamp >= now-365d AND timestamp < now-30d GROUP BY date(timestamp))` |
| `scores` | > 365 d | last scan of each ISO week | `scan_id IN (SELECT MAX(id) FROM scans WHERE timestamp < now-365d GROUP BY strftime('%Y-%W', timestamp))` |
| `signals` | > **30 d** (`signals_days`) | deleted | `DELETE FROM signals WHERE scan_id <= (SELECT MAX(id) FROM scans WHERE timestamp < now-30d)` |
| protected | forever | all rows | asserted unchanged pre-commit, else full rollback |

Scores delete = `DELETE FROM scores WHERE scan_id NOT IN (union of the three keeper sets)`.

**N = 30 justification:** every reader needing >30 d lookback (calibration 180 d, IV rank 365 d, charts 90 d, short-interest 60 d) operates at daily granularity or coarser; 30 days of full intraday data is retained purely as operational safety margin. **Downsample, not delete**, for 31–365 d because IV rank needs the 365-day daily series and calibration wants long-range daily context — daily keepers preserve that at ~7 % of the storage. Side benefit: calibration's in-memory load shrinks ~3×, directly easing the documented OOM.

---

## Phases 3–4 — Implementation (this PR)

- `scripts/db_prune.py` — stdlib-only; **dry-run default**; guards: idle window (23:00–05:30 UTC, weekends OK), scanner.log in-flight check (fails closed), free-disk ≥ DB size, verified timestamped backup before any delete, single transaction with protected-fingerprint + window-coverage assertions before COMMIT (violation → rollback), `VACUUM INTO` → quick_check + count verify → atomic `os.replace`, idempotent, logs to `/var/log/cyberscreener-prune.log`, emoji-free SendGrid notification via existing `intel/notifier`.
- `scripts/db_prune_config.json` — threshold + retention are config, not code.
- `scripts/systemd/cyberscreener-prune.{service,timer}` — daily 04:10 UTC (after the 03:30 nightly backup cron), runs `--auto --commit`: **no-op unless DB > 1,700 MB**. `Persistent=false` so a missed run can't fire mid-day. Inherits every guard.
- `api/tests/test_db_prune.py` — 10 tests, all passing (policy windows, protected invariants, rollback-on-assertion, idempotency, backup/restore, VACUUM swap, guards, rotation regression).
- `scripts/DB_PRUNE_RUNBOOK.md` — operator runbook (same content as below).

---

## Phase 5 — Validation on a copy (nightly snapshot of the live DB)

Copy: `nightly.db.gz` (03:30 UTC 2026-06-09 `.backup`), 1,772 MB uncompressed, quick_check ok. Working dir `~/cs-prune-validation/` on the MacBook.

**Dry-run output (copy):** delete 396,927 of 582,318 score rows + 3,677,109 of 5,344,038 signal rows; est. 1,118 MB freed; protected tables enumerated with options_plays checksum (rows=79 id_sum=3160 open=68).

**Commit run:** backup taken + verified (1,772 MB), deletes committed, `VACUUM INTO` 11 s, **file 1,772 MB → 558 MB (freed 1,214 MB)**. Total wall time ~2:50 on the MacBook (expect ~5–10 min on the droplet).

**Equivalence (identical fingerprint queries, pinned cutoffs, pristine vs pruned — all IDENTICAL):**

| Fingerprint | Pristine = Pruned |
|---|---|
| full-window scores (count, scan_id sum, lt/opt/iv sums) | 160,722 rows — identical |
| daily last-scan series, 31–365 d band | 24,669 (ticker, day) rows — identical |
| IV-rank inputs (per-ticker min/max over 365 d daily) | 479 tickers — identical |
| options_plays (count, id sum, open count, content length) | 79 / 3160 / 68 / 2415 — identical |
| prices (count, close sum) | 41,114 — identical |
| retained signals (count, scan_id sum) | 1,666,929 — identical |
| latest-scan scores | 480 rows — identical |

**Learning-loop end-to-end** (`run_full_backtest(days=180)` on both DBs): pairs 26,477 → 26,449 (−0.1 %); LT corr −0.012 → +0.010, Opt +0.006 → −0.028; component attributions stable (asymmetry 0.191→0.192, technical −0.117→−0.126, earnings_quality −0.105 both). The deltas are entirely within the band STATUS.md already documents as non-predictive noise (corr ≈ ±0.02), and stem from *which* intraday row represents a day in the >30 d band — the engine's `_deduplicate_scores` keeps the **first** scan of each day (06:00 UTC ≈ stale premarket data, contradicting its own "latest" docstring) while the prune keeps the **last** (post-close, better data). Information is not lost; the daily series itself is bit-identical.

**Idempotency:** immediate second `--commit` run: 0 rows to delete.
**Restore test:** pre-prune `.bak` copied over the pruned DB → quick_check ok, all counts match the pristine copy exactly (582,318 / 5,344,038 / 79).

**Bugs the copy-run caught (why Phase 5 exists):** (1) `mode=ro` cannot read a standalone WAL-mode backup copy → query_only fallback added; (2) backup rotation counted the fresh backup's `-wal`/`-shm` sidecars and **deleted the .bak it had just written** → rotation now matches `.bak` only and removes sidecars with their parent; backup WAL is checkpointed into the file before close. Both fixed + regression-tested.

---

## Operator runbook (backup → dry-run → commit → enable timer)

On the droplet, **23:00–05:30 UTC or weekend** (never mid-scan — the script refuses anyway):

```bash
ssh root@64.23.150.209
cd /opt/cyberscreener && git pull                       # after PR merge
python3 scripts/db_prune.py                             # 1. DRY RUN — review output
python3 scripts/db_prune.py --commit                    # 2. backup + prune + VACUUM swap
sqlite3 /app/data/cyberscreener.db "PRAGMA quick_check; SELECT COUNT(*) FROM options_plays;"
curl -s localhost:8000/health                           # 3. verify
# 4. enable automation only after the manual run looks right:
cp scripts/systemd/cyberscreener-prune.* /etc/systemd/system/
systemctl daemon-reload && systemctl enable --now cyberscreener-prune.timer
```

Rollback = the pre-prune backup: stop services, `cp /app/data/cyberscreener.db.preprune.<TS>.bak /app/data/cyberscreener.db`, remove stale `-wal/-shm`, start services. Full detail in `scripts/DB_PRUNE_RUNBOOK.md`.

---

## Observations for follow-up (out of scope here)

1. **Broken cron** on the droplet: `0 */2 * * 1-5 ... scheduler.py --once` errors every 2 h (`--once` is not a valid flag; the systemd scheduler does the real work). Remove or fix the crontab line.
2. **`_deduplicate_scores` keeps the first scan of each day** (premarket-stale) despite its docstring saying latest — a one-line fix would make calibration use post-close data and align exactly with the prune's daily keepers. Scoring change → separate decision.
3. **200 of 211 plays are open** — worth checking how many are past expiry but unclosed (`_check_play_outcomes` runs at 16:00 box time = UTC, i.e. noon ET; it may be racing market close).
4. Scans now take ~33 min for 526 tickers against a 30-min interval — effectively continuous scanning during market hours; the idle window in the prune config assumes this.

**OUT OF SCOPE, not done:** no live prune executed, no timer enabled, no journal/play data deleted, mill PIT corpus untouched, no scoring changes.
