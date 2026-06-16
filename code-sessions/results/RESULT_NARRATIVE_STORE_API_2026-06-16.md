# RESULT — Narrative Store + Read-Only API + UI (SESSION_NARRATIVE_STORE_API)

**Date:** 2026-06-16
**Branch:** `feat/narrative-store-api` (off `main`)
**Draft PR:** https://github.com/keltonshockey/cyberscreener/pull/19
**Scope:** Phase 1 of NARRATIVE_LAYER_PLAN.md — droplet-side store, read-only API, and UI. Additive + read-only relative to the live system. No scoring/weights/journal/universe/calibration changes. No deploys.

## Files added
- `api/db/narratives.py` — the SEPARATE `narratives.db` store (own connection helper, WAL; never imports `db.models` / touches `cyberscreener.db`).
  - Tables: `narratives(ticker PK, lt_story, st_story, sources(json), signal_snapshot(json), snapshot_hash, confidence, model, lt_generated_at, st_generated_at)` and `view_queue(ticker PK, last_viewed_at, requested DEFAULT 1)`.
  - Helpers: `get_narrative(ticker)`, `record_view(ticker)`, `upsert_narrative(...)` (the last for the mill pipeline/sync), plus `get_narratives_db()` / `init_narratives_db()`.
  - Narrative config block (env-overridable module constants, the repo's config-loader idiom — see `DB_PATH` in `db/models.py`): `CYBERSCREENER_NARRATIVES_DB` (defaults alongside the prod DB as a distinct file `narratives.db`), `NARRATIVE_ST_TTL_HOURS=24`, `NARRATIVE_LT_TTL_DAYS=7`.
- `api/routers/narrative.py` — read-only `GET /narrative/{ticker}`.
- `api/tests/test_narrative_router.py` — 4 tests.

## Files modified
- `api/main.py` — `include_router(_narrative_router)` + bootstrap `init_narratives_db()` on startup (guarded; warns, never fails the app).
- `frontend/src/api/endpoints.js` — `fetchNarrative(ticker)`.
- `frontend/src/pages/TickerPage.jsx` — Story panel (LT/ST sections, source links, "as of" date, fresh/stale dot, low-confidence note, quiet "Generating narrative…" placeholder on 202). Single fetch per load — no polling storm. Imperial Twilight styling; zero emoji.

## API contract the pipeline must fill

`GET /narrative/{ticker}` — **200** (a row exists):
```json
{
  "ticker": "PANW",
  "lt_story": "string|null",
  "st_story": "string|null",
  "sources": [{"title": "...", "url": "..."}],
  "confidence": "ok",
  "lt_generated_at": "ISO8601|null",
  "st_generated_at": "ISO8601|null",
  "stale": false
}
```
- `stale` is computed server-side from the TTLs: a section is stale if its `*_generated_at` is missing or older than its TTL (ST 24h, LT 7d). `stale = st_stale OR lt_stale`.

`GET /narrative/{ticker}` — **202** (no row yet):
```json
{ "status": "generating", "ticker": "PANW" }
```
- The view is recorded into `view_queue` on **every** call (200 and 202) so the lazy queue learns what is being looked at.

**Pipeline writes** rows via `db.narratives.upsert_narrative(ticker, lt_story=, st_story=, sources=, signal_snapshot=, snapshot_hash=, confidence=, model=, lt_generated_at=, st_generated_at=)`. `sources`/`signal_snapshot` accept Python objects (JSON-encoded for you) or pre-encoded strings. Timestamps are ISO8601 (the store/router parse with `datetime.fromisoformat`; UTC recommended).

## Signal endpoint for the pipeline (Scope item 3 — SKIPPED)

No new `/ticker/{t}/signals` view was needed — the required signals are already exposed read-only:
- **`GET /scores/latest`** returns full `scores` rows (`SELECT *`): LT components (`lt_rule_of_40`, `lt_valuation`, `lt_fcf_margin`, `lt_trend`, `lt_earnings_quality`, `lt_discount_momentum`), opt components (`opt_earnings_catalyst`, `opt_iv_context`, `opt_directional`, `opt_technical`, `opt_liquidity`, `opt_asymmetry`), plus `iv_30d`, `iv_rank`, `sentiment_score`, `sentiment_bull_pct`, `whale_score`, `pc_ratio`, `rsi`, `sma_*`, and the `lt_breakdown` / `opt_breakdown` JSON blobs.
- **`GET /scores/{ticker}`** returns per-ticker score history.

**Pipeline should consume `GET /scores/latest` (latest row per ticker) + `GET /scores/{ticker}` (history).** Nothing is recomputed; existing read-only query paths are reused.

## Tests / golden

- `make test`: **236 passed in ~4.6s** (was 232 before; +4 from `test_narrative_router.py`).
- `test_narrative_router.py` pins: (1) 202 when absent **and** view logged to `view_queue`; (2) 200 payload schema when a row is seeded into a fixture `narratives.db`; (3) the stale-flag math (ST/LT aged-out, both-fresh, missing-timestamps); (4) the router **never opens `cyberscreener.db`** (monkeypatches `db.models.get_db` to raise for the duration of both branches).
- `scoring_golden.json` **byte-identical** — unchanged (not in `git status`; `test_scoring_golden` green in the suite).
- Frontend `npm run build` succeeds (1852 modules, no errors).

## Isolation confirmation
- New file `narratives.db` is matched by the existing `*.db` gitignore — not committed.
- The narrative router/store import only `db.narratives`; no path reaches `db.models` or `cyberscreener.db`. Enforced by test (4).

## Out of scope (untouched)
Generation, mill pipeline, the lazy-queue consumer, `narratives.db` sync to the droplet, deploys. Those are `SESSION_NARRATIVE_PIPELINE.md` and `SESSION_NARRATIVE_SYNC.md`.
