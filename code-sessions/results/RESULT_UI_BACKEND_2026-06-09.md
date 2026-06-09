# RESULT — SESSION-UI-BACKEND (make the UI's relevance + honesty real end-to-end)

**Date:** 2026-06-09
**Branch:** `feat/ui-backend-support`
**PR:** https://github.com/keltonshockey/cyberscreener/pull/8 (**DRAFT — no deploy**)
**Base:** `main`
**Follows:** PR #7 (`feat/ui-imperial-twilight`) which shipped the frontend and flagged these as client-side fakes.

This session makes real, at the data source, the things PR #7 inferred/faked in the
browser. Net **score delta = 0** — only #6 changes scores, and it was split out.

---

## What shipped, per task

### #1 — Emoji at source ✅
The API never emits a pictograph again.
- `api/core/text.py` → `strip_emoji()` is the canonical sanitizer (mirrors the old
  frontend `stripEmoji` regex so behaviour matched during migration).
- Stripped every emoji **literal** from:
  - `core/scanner.py` — all `reasons`/`signals` f-strings + the play `emoji` field
    (now `""`).
  - `routers/market.py` — `direction_label`, `catalyst` (killer-plays + buy-zone),
    inverse-plays interpretation; market-indices **flags → ISO region codes**.
  - `intel/sentiment.py`, `intel/news_intel.py`, `intel/sec_filings.py` — the
    insider/analyst/8-K/outage/**threat-landscape** signal generators.
- `db.models.save_scan` also runs `strip_emoji` defensively when persisting signal
  text (catches any straggler from a source not cleaned above).
- **Left intentionally:** `intel/notifier.py` (email, not API output); `main.py`
  backfill/email HTML; decorative emoji in the voxel `game/` (phase-4).
- The old emoji-based `impact` derivation in `save_scan` was dead once emoji were
  gone (always returned `neutral`); replaced — see #5.

### #5 — Signal relevance metadata at generation ✅
- `api/core/signals_meta.py` → `classify_signal(text, sector, breach_victim)` is the
  authoritative, server-side port of `frontend/utils/signals.js`. Returns
  `stack` (lt/options/both), `polarity` (tailwind/headwind/event),
  `sector_context` (general / cyber-demand / breach-headwind / **suppress**),
  `dedupe_key`, plus `impact` (derived from polarity) and `applies` (the gate flag).
- `signals` table gains `stack`, `polarity`, `sector_context`, `dedupe_key`
  (+ `_migrate_signals_table` for prod). `save_scan` persists them.
- `GET /signals/{ticker}/recent` emits the metadata; for rows written before the
  columns existed it **classifies live** using the ticker's latest sector context,
  so the endpoint is authoritative immediately (no re-scan required).
- A real-bug caught by the new tests: `\bpe\b` boundary — `pe\b` was matching
  "lands**ca­pe**" and mis-tagging threat signals as `lt`.

### #4 — Sector taxonomy in the data layer (multi-tag) ✅
- `api/core/sector_tags.py` → `tags_for(ticker, sector, subsector)` promotes the
  curated map (NVDA = AI+Semis+Tech) out of the browser. Expanded set: AI, Semis,
  Cyber, Energy, Nuclear, Defense, Fintech, Space, Quantum, Biotech, + coarse.
- New `scores.sector_tags` (JSON) column (+ migration). Scanner writes it per ticker;
  `save_scan` persists it. Flows out via `/scores/latest` (`SELECT *`).
- **Persist path aligned:** scores INSERT 67→68 cols; fixture `scores_schema.sql` +
  `test_scan_persist` updated in lockstep — no count drift (the #1412-class bug).

### #3 — Inline price series per row ✅
- `GET /prices/sparklines?tickers=NVDA,AMD&points=30` (in `routers/scores.py`).
  Last N closes per ticker from the existing `prices` table via one windowed
  (`ROW_NUMBER`) query, batched ≤200 tickers, ascending for plotting, **60s cache**,
  ticker input sanitized. Lean: closes only, no new storage.

### #2 — Per-row Reality Check: honest, not mislabeled ✅ (resolution = expose the real proxy)
- Finding: a real per-row value **already exists** — `_compute_ticker_rc` writes
  `scores.rc_score` on every row (the play-**independent** components: score
  alignment, IV context, RSI/trend, earnings proximity). It already flows via
  `/scores/latest`. PR #7's grid showed `Opt` and had **no** mislabeled "Reality".
- A full 6-component play-level RC for all ~490 tickers at scan time is infeasible
  (needs option chains; only top-25 get Schwab enrichment). So the honest fix is to
  surface the real proxy, not fake a play RC: the grid now has a **Reality** column
  reading `rc_score`, and the glossary is explicit that it's the play-independent
  setup proxy while the full 6-component RC is per-play on Pactum.

### #6 — Scoring relevance gate: **SPLIT OUT** (not in this PR) ⏸️
- **Why split:** it changes scores, so per the prompt it must be quantified vs
  `main`, sanity-checked against rankings, and coordinated with the in-flight
  scoring work (#6 directional deployed; held options reweight **B3** pending).
  Doing it here would collide with that work.
- **Foundation laid:** `classify_signal` already returns `applies=False` /
  `sector_context='suppress'`, so the gate has a single source of truth. The
  follow-up zeroes a sector-specific signal's **score contribution** when `applies`
  is false (e.g. threat-landscape tailwind must not inflate a non-cyber name; it's a
  headwind for a breach victim). Today the threat modifier in `scanner.py` (~L2095)
  is applied within threat-context; the gate generalizes/validates that and extends
  it to any future sector-specific signal.
- **Validation plan for the follow-up:** snapshot scores on `main`, apply the gate,
  diff per-ticker lt/opt deltas, confirm top-N rankings don't churn pathologically,
  ship isolated + flagged so it doesn't touch B3.

---

## Frontend wiring (done in this PR — end-to-end)
All additive, with fallbacks for rows scanned before the new fields exist:
- `utils/sectors.js` — `tagsFor` prefers backend `sector_tags`.
- `utils/signals.js` — `classifySignals` consumes backend `stack`/`polarity`/
  `sector_context`/`dedupe_key`; suppress gate is now server-driven; heuristics
  kept only as legacy fallback.
- `api/endpoints.js` + `ConvictionPage.jsx` — batched `fetchSparklines` feeds real
  price paths; MA-slope `trendSeries` is fallback-only.
- `ConvictionPage.jsx` — real **Reality** column from `rc_score`; `glossary.js`
  entry made honest.
- **Dead code removed:** `utils/text.js` (`stripEmoji`) deleted + last importer
  removed; `icons.jsx` note updated. `npm run build` passes.

Nothing left pending for the Forum grid. Pactum/Basilica still render a few
decorative bits (the play `emoji` field is now `""`; Pactum should swap to a Lucide
`DirectionIcon`) — phase-4, out of scope here.

---

## Tests
- New: `test_text_emoji`, `test_signal_metadata`, `test_sector_tags`,
  `test_prices_sparklines`, `test_recent_signals_endpoint`, + `conftest.py`
  (bootstraps a writable temp DB before `db.models` import).
- Updated: `test_scan_persist` fixture/schema for the new columns.
- **Result: 70 passed.** Pre-existing failures on `main` (unrelated to this work):
  `test_schwab_client` (`pd` undefined in `schwab_client.py`) and 2
  `test_killer_plays_fields` (seeding) — confirmed by `git stash` run on base.
- Local env note: repo needs Python ≥3.10 (`dict | None`); system was 3.9, so the
  test venv was built with `uv python install 3.11` (no sudo/brew-prefix needed).

## Commits
1. `feat(api): emoji-free output, signal relevance metadata, multi-tag sectors` (#1/#4/#5 data path — co-edit scanner/market/models)
2. `feat(api): inline recent price series for real grid sparklines (#3)`
3. `feat(ui): consume real backend fields (tags, signal metadata, sparklines, RC)`
4. `feat(api): strip emoji from intel signal generators (#1)`

## Deploy note
Draft only. When deploying (idle window, never mid-scan): the migrations add
`signals.{stack,polarity,sector_context,dedupe_key}` and `scores.sector_tags`
additively; existing rows backfill metadata lazily via the endpoint, fully on the
next scan. Frontend builds on the droplet as usual.
