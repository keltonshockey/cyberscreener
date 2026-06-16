# RESULT — Router Split (main.py monolith → FastAPI routers)

Date: 2026-06-16
Branch / PR: `feat/router-split` → **draft PR #18** https://github.com/keltonshockey/cyberscreener/pull/18
Status: implemented + validated. Behavior-preserving refactor only. **No production changes, no deploys, no push to `origin` (Synology) or `main`.**

This is the Track-2 monolith split that SESSION-TEST-HARNESS was the prerequisite for. Every change is provable behavior-preserving: the 232-test harness stayed green throughout and the scoring golden files are **byte-identical** before and after.

---

## TL;DR

- Extracted two routers out of `api/main.py`, verbatim:
  - `routers/ticker.py` — `/tickers`, `/tickers/{sector}`, `/universe` (read-only; lowest risk, done first to prove the pattern).
  - `routers/plays.py` — the `/plays/*` + `/ai/status` cluster, plus the play cache/status state, the background play fetcher, and the unified Reality Check scorer `_compute_rc`, all moved as one self-contained unit.
- `api/main.py`: **2141 → 1568 lines** (−573).
- Tests: **232 → 245** (+13 additive). Existing assertions unchanged.
- Golden files: **byte-identical** (verified by sha256, see below).

---

## Reconciliation with the session brief (routes had already moved)

The brief named `ticker.py = /ticker/*, /chart/*` and `plays.py = /plays/*, /killer-plays, /weights, /calibrate`. Reality had already diverged — prior sessions extracted some of those:

- `/chart/{ticker}` already lives in `routers/scores.py`.
- `/killer-plays` already lives in `routers/market.py`.
- There is no `/ticker/*` route group in the code (the per-ticker UI page is a frontend route fed by `/scores/{ticker}`, `/chart/{ticker}`, `/plays/{ticker}`, etc.).

So `ticker.py` was repurposed for the read-only **ticker/universe** endpoints that were still in `main.py`, which is the same low-risk, read-only "prove the pattern" group the brief intended. `/weights*` and `/calibrate` were **deliberately left** in `main.py` — see below.

---

## Routers extracted

### `routers/ticker.py` (52 lines) — `tags=["ticker"]`
| Method | Path |
|---|---|
| GET | `/tickers` |
| GET | `/universe` |
| GET | `/tickers/{sector}` |

Self-contained: imports its universe symbols from `core.universe` and recomputes `ALL_TICKERS` with the identical one-liner used in `main.py` (a derived constant, duplicated so payloads are byte-identical — no new shared symbol introduced).

### `routers/plays.py` (596 lines) — `tags=["plays"]`
| Method | Path |
|---|---|
| GET | `/plays/top/recommendations` |
| POST | `/plays/{ticker}/generate` |
| GET | `/plays/{ticker}/status` |
| GET | `/plays/{ticker}` |
| GET | `/plays/history/all` |
| GET | `/plays/history/{ticker}` |
| POST | `/plays/{ticker}/analyze` |
| GET | `/ai/status` |
| GET | `/plays/open/tracked` |

Moved with the endpoints (their only callers): `_plays_cache`, `_plays_status`, `_PLAYS_CACHE_MAX`, `_evict_plays_cache`, `_latest_scores_for`, `_fetch_plays_background`, and `_compute_rc`.

`main.py` wires both via `include_router` (after the existing auth/backtest/scores/market routers). Route-resolution order is preserved: the catch-all `@app.get("/{full_path:path}")` is still an `@app` route registered after all `include_router` calls, so it cannot shadow the extracted routes, and no other `@app` route overlaps these paths.

---

## Import seam cut near `_compute_rc` (the one sensitive move)

`_compute_rc` (the 6-component unified Reality Check scorer, FROZEN pending the gate reads) is defined in `main.py` and has **exactly two callers** — both inside `/plays/{ticker}` and `_fetch_plays_background`, both of which moved to `plays.py`. (Confirmed by repo-wide grep: only `main.py:1445` and `main.py:1637` called it; `routers/market.py` merely mentions it in a comment.)

Leaving `_compute_rc` in `main.py` while moving its callers to `plays.py` would create a circular import (`main` imports `routers.plays`; `routers.plays` would import `_compute_rc` from `main`). Per the hard constraint — *"If `_compute_rc()` must move to break an import cycle, move it verbatim and keep a golden/behavior test on it"* — it was moved **verbatim** into `plays.py` alongside its callers, and a frozen behavior test was added:

- `tests/test_compute_rc_frozen.py` pins the exact input→output (score + full per-component breakdown) for two cases. The expected values were captured from the function as it stood in `main.py` immediately before the move (behavior, not a re-derivation). The cases intentionally lock existing quirks — e.g. `"bear call credit spread"` contains `"call"`, so the technical component scores via the bullish branch — so any silent drift fails loudly.

No edit was made to `_compute_rc`'s body, the scoring math, weight tables, `core/scanner.py`, the directional rule, the journal/closure code, the universe, or calibration.

---

## What was deliberately LEFT in `main.py` (and why)

- **`/weights`, `/weights/reset`, `/weights/history`, `/calibrate`** — the brief listed these under `plays.py`, but they were left in `main.py` on purpose. They sit on the **frozen scoring/calibration surface** the constraints repeatedly fence off, `/calibrate` is coupled to `tests/test_calibrate_job.py` via `from main import app, require_admin` (the test overrides the `main.require_admin` dependency object), and they are scoring-admin endpoints, not plays. Moving them into a file named `plays.py` would mislabel them and add reviewer risk near the pre-registered `v2-baseline` cohort for near-zero structural benefit. This is the brief's own "stop when remaining endpoints are awkward to move" escape hatch.
- **`/scan`, `/scan/status`** — interleaved with admin/rate-limit/scan-background state; not a clean group.
- **`/augur/*`, `/watchlist*`, `/earnings/*`, `/alerts/*`, `/notify/test`, `/config/ui`, `/health`, `/health/detailed`, `/backfill*`, `/api/info`, `/scores/latest/personalized`, `/debug/timing*`, SPA/dashboard serving + catch-all** — out of the two named groups; left for a future session to keep this PR narrow and the diff reviewable. `main.py` is now app-init + middleware + migrations + `include_router(...)` + these remaining endpoint groups, which is the intended direction without forcing a line target at the cost of behavior risk.

---

## Test gate (both directions)

`make test`, before and after every step:

```
232 passed   (baseline, before any change)
...
245 passed in 4.69s   (after both extractions + 13 new tests)
```

The +13 are purely additive (new files); no existing assertion was modified.

Golden files — sha256 identical before and after (`shasum -a 256 -c`):

```
tests/fixtures/scoring_golden.json: OK
tests/fixtures/scoring_fixtures.json: OK
tests/fixtures/scores_schema.sql: OK
```

Any golden diff would have meant changed behavior → stop/revert. None occurred.

Route-registration sanity (offline): each extracted route is registered on `main.app` **exactly once** at the same path and HTTP method as before (verified by enumerating `app.routes`).

---

## New tests added (additive only)

- `tests/test_router_ticker.py` (4 tests) — routes registered once at same paths; `/tickers`, `/universe`, `/tickers/{sector}` response schemas; `/universe.tickers.all` agrees with `/tickers.all_tickers`; invalid sector → 400.
- `tests/test_router_plays.py` (7 tests) — all 9 plays routes registered once at same paths/methods; offline-reachable schemas (`/ai/status`, `/plays/history/all`, `/plays/open/tracked`); `/plays/{t}/status` not-started; unknown-ticker `/plays/{t}/generate` + `/plays/{t}` → 404 (no network); `/plays/top/recommendations` empty-DB → `{"plays": [], "message": "No scans found."}`. Network-bound branches (live options/ticker fetch) are intentionally not exercised, matching the offline harness contract.
- `tests/test_compute_rc_frozen.py` (2 tests) — see import-seam section.

---

## main.py line count

| | lines |
|---|---|
| before | 2141 |
| after | 1568 |
| delta | −573 |

`routers/ticker.py` 52, `routers/plays.py` 596 (verbatim moves + module docstrings/imports).

---

## OUT OF SCOPE (untouched, as required)

Scoring/weights/universe/journal/calibration logic; `core/scanner.py`; `db/models.py` schema; security-audit items (next session: SESSION-SECURITY-AUDIT); UI/frontend; dependencies; deploys.

## Reproduce

```bash
cd ~/cyberscreener && git checkout feat/router-split
make test                       # 245 passed
cd api && shasum -a 256 -c <(...) # golden byte-identical
```
