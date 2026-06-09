# RESULT — UI Phase 4 (Imperial Twilight rollout to the remaining pages)

**Date:** 2026-06-09
**Branch:** `feat/ui-phase4` (draft PR — no deploy, no merge)
**Base:** `main` @ merged #8 (Imperial Twilight tokens + rebuilt Conviction/Forum page)

## Goal
Finish the overhaul that #7/#8 only landed on `/conviction`. Bring every other page onto
the Imperial Twilight design system (tokens, shared primitives, Lucide icons, hover-explain)
and remove every emoji from `frontend/src`. The homepage `/` (BasilicaPage) was the priority —
the front door was still old-design and emoji-heavy.

## Pages rebuilt / restyled

| Page | File | What changed |
|------|------|--------------|
| **Homepage `/` (Basilica)** — full rebuild | `pages/BasilicaPage.jsx` + `.module.css` | Rebuilt on direct Imperial Twilight tokens. Section headers use Lucide icons (`Globe`, `Crosshair`, `Sprout`, `Flame`, `Layers`). Killer Plays use `TierBadge` + `DirectionIcon`; Send Alert is a `Mail` button. Score Momentum filter is now a `SegmentedControl` (was emoji buttons) with `TrendingUp/Down` polarity rows. Intel Layers use `FileText`/`MessageSquare`/`Waves`/`Shield`. New token-styled stat tiles, gold-gradient leader bars, restyled market indices + RSI overview. **Hover-explain (`<Explain>`) on every metric** (LT, Opt, RSI, conviction, earnings, intel layers). |
| **Pactum `/pactum`** | `pages/PactumPage.jsx` | Emoji → Lucide: empty-state `Crosshair`, Play History `BarChart3`, loading/refresh `RefreshCw`, errors/risk `AlertTriangle`, AI panel `Brain`, Weight Tuner `Settings`. Play-header server emoji replaced with `DirectionIcon`. RC-breakdown rows now render the real Lucide `comp.Icon` (was a dead `comp.icon` that resolved to `undefined`). Hover-explain added to RSI / IV / Reality Check. Toggle chevrons replace `▲▼▶`. |
| **Archive `/archive`** | `pages/ArchivePage.jsx` | Emoji → Lucide: empty-state `Hourglass`/`AlertTriangle`/`BarChart3`, Retry `RefreshCw`, Auto-Calibrate `Settings`. Hover-explain on LT Correlation and Q5−Q1 Spread. |
| **World `/world`** | `pages/WorldPage.jsx` | Building legend emoji (`🏦🏛⚖📜`) → Lucide (`Landmark`/`Scroll`/`Zap`/`Library`). **Voxel game left fully intact** — only the chrome around it changed. |
| **Ticker `/ticker/:symbol`** | `pages/TickerPage.jsx` | Section/button emoji → Lucide; breakdown cards now render real `comp.Icon`; hover-explain on LT/Opt/RSI/IV-rank and the two breakdown cards. |

### Shared components touched (reuse, not duplication)
- `components/ui/icons.jsx` — **added** Lucide exports needed across pages (`Mail, Crosshair, Sprout, Shield, Settings, Brain, Clock, Layers, BarChart3, Coins, Compass, Hourglass, KeyRound, MessageSquare`). One family only (Lucide).
- `components/ui/SystemHealthWidget.jsx` — status glyphs (`● ▲ ✕ ▼`) → Lucide (`Activity/AlertTriangle/X/Chevron`); migrated inline colors to direct tokens.
- `components/ui/Explain.jsx` — rendered `→` deep-dive arrow → `ChevronRight`.
- `components/world/DistrictPanel.jsx` — close `✕` → `X` icon (+ aria-label).
- `auth/QuaestorCreator.jsx` — six attribute emoji (`🛡⚔📜🎲👁💧`) → Lucide (`Shield/Target/Scroll/Sprout/Compass/Waves`).

Primitives **reused** (not re-created): `Card`, `Explain`, `TierBadge`, `SegmentedControl`,
`Stat`/stat-tile pattern, `DirectionIcon`, `glossary.js`, `sectors.js`, `scoring.js`. **Zero new
color values** — everything resolves to the §2 token table in `theme/variables.css`.

## Emoji kill — verifiable (acceptance met)

Command (exactly as specified in the task):
```
grep -rnP "[\x{1F000}-\x{1FAFF}\x{2600}-\x{27BF}\x{2190}-\x{21FF}\x{2B00}-\x{2BFF}]" frontend/src
```
- **Before:** 65 matches across 21 files (6 pages, QuaestorCreator, SystemHealthWidget, Explain, Sparkline, DistrictPanel, game files, glossary/signals/sectors/scoring, variables.css).
- **After:** **0 matches — clean.**

All pictographic emoji were replaced with Lucide icons or removed. The remaining `→` glyphs (almost
all in code comments / one prose string in `glossary.js`) were converted to `->` / plain English so the
strict grep passes — including comment arrows in the voxel game files and a stray comment in the
otherwise-clean `ConvictionPage.jsx`.

### Server-side emoji: none — no backend follow-up needed
Checked `api/` for emitted emoji. The #8 backend work already neutralized it:
- `core/scanner.py` play objects emit `"emoji": ""` (empty) — the field is dead. The frontend now
  ignores it entirely and derives a `DirectionIcon` from `direction`.
- `routers/market.py` index `flag` is an **ISO country code** (e.g. `US`/`GB`/`JP`), not a flag emoji;
  the Basilica rebuild no longer renders it at all (a `Globe` header icon replaces it).
- `core/text.strip_emoji` exists as a backend guard and `tests/test_text_emoji.py` asserts the
  data-emitting modules stay emoji-free.

The `stripEmoji` client shim flagged dead in #8 is **confirmed absent** from `frontend/src` (only a
doc-comment in `icons.jsx` references the backend `core/text.strip_emoji`, not a shim).

## Usability (carried the #7 audit forward)
- Basilica Score-Momentum filter is now a `SegmentedControl` (consistent with the Forum two-stack control) instead of emoji toggle buttons.
- Killer-play and leader rows are token-consistent with the Forum grid (tabular figures, gold hairlines, tier badges, polarity tints).
- Hover-explain on every metric across all rebuilt pages, sourced from the shared `glossary.js`.
- Latin page identity preserved (Basilica / Forum / Pactum / Archive / World); the voxel World is untouched.

## Verification
- `npx vite build` — **passes** (1851 modules, no errors).
- Emoji grep — **zero**.
- **Screenshots** (mocked-data render via a local same-origin static+API harness; `?theme=` override
  for deterministic dark/light). See `code-sessions/results/phase4-screens/`:
  - `basilica-dark.png`, `basilica-light.png` — the rebuilt front door, both themes.
  - `conviction-dark.png` — the Forum reference, for side-by-side consistency.
  - `pactum-dark.png`, `archive-dark.png` — restyled, emoji-free.
  - Basilica is visually 1:1 with the Forum's language (same header/nav, gold hairlines, tabular
    figures, tier badges, Explain icons, footer rubric). Light mode (museum daylight) renders correctly.

> Note: screenshots use seeded mock data (no populated DB locally). A representative live capture
> belongs to the deferred idle-window deploy. Render fidelity of the **design system** is fully shown.

## Out of scope (untouched, as instructed)
Deploy / merge, backend scoring changes, the signals DB-prune ops task.

## Draft PR
`feat/ui-phase4` → opened as **draft** (link in PR). No deploy, no merge.
