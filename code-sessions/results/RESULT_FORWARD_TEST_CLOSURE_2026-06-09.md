# RESULT — Forward-Test Closure (B2 / SESSION-LEARNING-LOOP core)

Date: 2026-06-09
Branch / PR: `feat/forward-test-closure` → **draft PR #12** https://github.com/keltonshockey/cyberscreener/pull/12
Status: implemented + validated on a copy of the live journal. **No live write has been run.** Operator runbook below. No deploy.

---

## Headline: the premise was wrong, and that matters

The brief said *"200 of 211 plays are OPEN, dating back to February — they should have resolved long ago."* The first half was true; the second half was not:

- The `options_plays` journal **began 2026-05-12** (ids 1–216 contiguous, no deletions; verified via `MAX(id)=COUNT(*)=sqlite_sequence=216`). Nothing dates to February — February is when the *scores* cadence started, and the two got conflated.
- All 205 currently-open plays have **future expiries** (2026-06-18 / 06-22 / 07-10 / 07-17). Zero are past expiry. Zero are missing `strategy/strike/expiry/entry_price`.
- The only plays that ever reached expiry — 11 AAPL rows expiring 6/5 — **were closed on schedule** on 6/6 (`journalctl`: "Play outcome check: closed 11 expired plays", Jun 06 16:09 UTC).
- The mill JSONL journal (`~/finance/forward_test/journal.jsonl`) is younger still: 24 entries since **2026-06-08**.

So the forward test is not broken-stale; it is **young**. Nothing needed unsticking. What the diagnosis *did* find is that the closure path would have silently corrupted the gate the moment real volume starts expiring (6/18). That is what this session fixed.

### Resolvable / invalid / unresolvable split (the 205 open plays)

| Cohort | Count | Notes |
|---|---|---|
| Open, future expiry, fully resolvable when due | 205 (80 distinct) | all fields present; `prices` covers all play tickers daily (~480/day) |
| Open and past expiry (the premised "stuck" cohort) | **0** | — |
| Invalid / missing completeness fields | **0** open | the early-play completeness problem manifests differently: see "pre-fix rows" below |
| Closed with **wrong** outcomes | 11 | legacy directional ×4 math on iron condors — see below |

The "early plays lacked completeness fields" note (STATUS.md was referenced in the brief but **does not exist** on the MacBook, mill, or droplet — closest artifact is the `fix/iv-gate-play-completeness` branch) shows up not as NULLs but as **semantic drift**: pre-fix May rows filed the *underlying* price in `entry_price` for iron condors (e.g. 300.71) where post-fix rows file the *credit* (e.g. 1.19). The v2 closure rescues these via the `Collect $X.XX` figure each play's notes already carry, and marks them `unresolvable` if no defensible cost basis exists — never guessed.

---

## Phase 1 — Why closure would have failed (the real defects)

1. **Wrong outcome math.** `_check_play_outcomes` closed *every* strategy as `underlying %move × direction × 4`. The 11 AAPL **iron condors** (neutral credit structures) settled at 310.26 — *inside* their 285/315 short strikes, i.e. **wins of ~+21…26% of max risk** — and were recorded as **−12.7…−16.6% losses**. The journal's only closed outcomes were all sign-flipped.
2. **Settlement look-ahead / gaps.** `get_nearest_price(..., window_days=5)` could pick a price up to 5 days *after* expiry. And `prices` has no 2026-06-05 row (scan gap), so the 6/5 expiries settled on the 6/4 close — defensible, but previously accidental rather than specified.
3. **Closed on expiry morning.** `expiry <= today` fired at 16:00 UTC (noon ET) *on* expiry day, before the expiry session's close existed.
4. **Silent sample loss.** No price ⇒ play closed with NULL pnl — indistinguishable from a real outcome being absent, and excluded from stats without a trace.
5. **Aging-out zombie bug.** Closure iterated `get_open_plays(days_old=180)`: any play still open >180 days after generation would fall out of the scan and stay open forever. (This is the failure mode the brief feared — latent, not yet triggered.)
6. **Scheduling race.** The check ran only when a loop iteration landed in `hour == 16`, but a weekday cycle is ~63 min (33-min scan + 30-min sleep) vs a 60-min window — some weekdays skip entirely (delay, recovered later; weekends always hit).
7. **Batch fragility.** One malformed play raised out of the whole loop — all remaining closures aborted for the day.
8. **Conviction gate unbucketable.** Every one of the 216 journal rows filed `lt_score = opt_score = 0`: the `log_play` call site reads them from `fetch_ticker_data()`'s dict, which never contains them (`data.get("lt_score", 0)`). The gate is "win rate at conviction ≥65" — uncomputable from as-filed journal data.
9. **Duplicate spam.** The post-scan pre-warm regenerates plays for top tickers every 30 min and re-logs them: 216 rows = **83 distinct** (ticker, strategy, strike, expiry); 137 rows on 6/9 alone. Naive stats would pseudo-replicate each play up to 9×.
10. **The broken cron is real but unrelated to closure.** `0 */2 * * 1-5 … scheduler.py --once` errors every 2h (`--once` was never a valid flag; confirmed in `/var/log/cyberscreener-cron.log`). Closure rides the systemd daemon (`--daemon --interval 1800`), which works. The cron line is pure noise → operator should remove it.

Also resolved en route: the second DB at `/opt/cyberscreener/data/` is a 0-byte red herring; both services point at `/app/data/cyberscreener.db`. The db-prune session's validation copy showing 79 plays vs 211 live the same day is explained by the logging surge (137 rows logged on 6/9 after the 03:30 snapshot), not by any data loss.

---

## Phase 2 — Pre-registered semantics (committed before computing outcomes)

`api/core/FORWARD_TEST_SEMANTICS.md`, commit `54658c2` — written and committed **before** any new outcome was computed. Summary:

- **Close trigger:** strictly past expiry (`today > expiry`); held to expiry (no exit signals exist).
- **Settlement:** latest `prices` close in **[expiry − 3d, expiry]**; never post-expiry. None within window: ≤10 days past → stays open (pending data); >10 days → `unresolvable`.
- **Outcomes:** standard settlement payoffs per strategy (long call/put; bull-call / bear-put spreads capped at width; straddle; iron condor as credit vs breached-leg loss, return on max risk). Cost basis as filed; pre-fix condors rescue credit from notes; unknown-credit condors are still decided where the payoff sign is determinate (inside short strikes = win; full max-width wing breach = −100% of risk) and `unresolvable` where it is not.
- **Win** := realized return > 0 strictly, net of as-filed cost; no commission/slippage modeled (stated).
- **EV gate** := profit factor (gross gains / gross losses on realized returns) ≥ 1.5; expectancy reported alongside.
- **Conviction** := 0.6·opt + 0.4·lt **as of entry**, backfilled from the `scores` table at the latest scan ≤ `generated_at` (contemporaneous; no look-ahead). Gate bucket ≥65.
- **Unit of analysis** := distinct (ticker, strategy, strike, expiry), earliest row; duplicates excluded from metrics.
- **Disclosure:** during read-only diagnosis I had already seen the 11 legacy rows' settlement (310.26) and strikes, so the condor flip to wins was foreseeable when the semantics were written. The formulas are standard payoff identities with no free parameters; nothing was tuned after seeing an outcome.

## Phase 3 — Implementation (draft PR #12)

- `api/core/play_closure.py` — pure payoff math separated from DB access; `close_due_plays` idempotent (`status='open'` only), per-play error isolation; conviction backfill; gate metrics over distinct plays; legacy-closure migration with audit trail appended to notes.
- `api/db/migrate_play_closure.py` — additive columns: `closed_at, settlement_price, settlement_date, realized_pnl, realized_return, outcome, win, close_method, entry_conviction`. Legacy `outcome_price/outcome_date/pnl_pct` still written for UI compatibility (`pnl_pct` = realized return ×100; `close_method` disambiguates eras).
- `api/scheduler.py` — closure on **every** daemon iteration (kills the hour-16 race; harmless because idempotent and indexed); `--close-outcomes` CLI for supervised/cron runs.
- `api/db/models.py` — `log_play` now **dedupes** (returns the existing open play's id instead of re-inserting) and records `entry_conviction`; `init_db` creates `options_plays` + new columns (fresh DBs/tests previously lacked the table).
- `api/main.py` — logs real lt/opt scores at entry from the latest `scores` row (was constant 0).
- `scripts/backfill_play_closure.py` — supervised, **dry-run by default**, `--commit` and `--migrate-legacy` explicit.
- **Tests:** `api/tests/test_play_closure.py`, 29 tests, all passing — payoff math per strategy (incl. condor credit-rescue, unknown-credit regions, spread cap, underlying-as-debit rejection), settlement window (post-expiry excluded, 3-day reach-back limit), expiry boundary (expiry-day NOT closed), idempotency, open-stays-open, pending-within-grace, unresolvable-is-flagged-never-fabricated, batch error isolation, no-look-ahead conviction backfill, dedup-to-earliest, gate-metrics bucketing. Full suite: 99 passed; the 2 `test_killer_plays_fields` failures and the `test_schwab_client` collection error **pre-exist on main** (verified via stash).

## Phase 4 — Copy-run validation + first gate read

Copy: `~/cs-closure-validation/copy.db` built read-only from the live DB (full `options_plays`, `prices` (41,594), `scans`, and a `scores` extract for play tickers).

| Step | Result |
|---|---|
| Schema migration | 9 columns added (additive only) |
| Conviction backfill | **216/216 filled**, 0 without contemporaneous scores |
| Legacy migration (`--migrate-legacy`) | **11/11 recomputed; all flip loss → win** (+0.20…+0.26 of max risk vs legacy −12.7…−16.6%); legacy values preserved in notes |
| Closure | **due = 0** — correct: nothing is past expiry |
| Re-run (idempotency) | all zeros |
| `scheduler.py --close-outcomes` against copy | works end-to-end |

**First gate read (distinct closed plays, pre-registered definitions):**

| Bucket | n decided | wins | win rate | profit factor | expectancy |
|---|---|---|---|---|---|
| conviction ≥65 (65–75) | 3 | 3 | 1.00 | ∞ (no losses) | +0.229 |
| all other buckets | 0 | — | — | — | — |
| overall | 3 | 3 | 1.00 | ∞ | +0.229 |

**Honest framing: this is underpowered to the point of meaninglessness** — 3 distinct plays, one ticker (AAPL), one expiry date (6/5), one strategy (iron condor), and the win rate is 1.00 only because the sole expiry batch happened to settle in-range. It says nothing about the ≥55%/EV≥1.5× bar. What changed is that the gate is now **measurable**: definitions are pre-registered, outcomes are strategy-correct, conviction buckets exist, and the sample arrives on a known schedule — distinct-play closure waves of **12 on 6/18, 11 on 6/22, 9 on 7/10, 48 on 7/17** (79 of the 80 distinct open plays sit at conviction ≥65, so the gate bucket will be nearly the whole sample). By late July: ~83 distinct closed plays. Still modest; live capital waits on the real bar *and* sample size.

---

## Operator runbook (supervised — nothing here was executed against live)

```bash
# after PR #12 merges, on the droplet:
cd /opt/cyberscreener && git pull
# 1. dry run against live (read-only on live data; prints what would change):
venv/bin/python scripts/backfill_play_closure.py --db /app/data/cyberscreener.db
# 2. live write (supervised):
venv/bin/python scripts/backfill_play_closure.py --db /app/data/cyberscreener.db --commit --migrate-legacy
# 3. restart so the daemon picks up settlement_v2:
systemctl restart cyberscreener.service cyberscreener-scheduler.service
# 4. remove the broken cron line (errors every 2h; scanning is systemd's job):
crontab -e   # delete the "scheduler.py --once" line
#    optional replacement (closure safety net independent of the daemon):
#    15 22 * * 1-5 cd /opt/cyberscreener/api && CYBERSCREENER_DB=/app/data/cyberscreener.db /opt/cyberscreener/venv/bin/python scheduler.py --close-outcomes >> /var/log/cyberscreener-cron.log 2>&1
```

Note: the dry run on live exits early asking for `--commit` if the schema columns don't exist yet (it refuses to ALTER live in dry mode); run it against a copy first if a full preview is wanted — `~/cs-closure-validation/` has the procedure.

## Coordination / out of scope

- Consumes the `prices` table the db-prune session protects — compatible (prune keeps `prices` whole; this is the dependency that protection exists for).
- The `log_play` dedup will flatten the journal growth curve (was 137 rows/day of duplicates); the db-prune numbers for `options_plays` stay valid since the table is protected either way.
- **OUT OF SCOPE, not done:** deploy/merge, live `options_plays` writes, enabling live trading, scoring/weight changes, survivorship archive, mill PIT corpus (untouched).
