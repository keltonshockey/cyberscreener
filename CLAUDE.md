# QUAEST.TECH — Claude Code Guide

## Project Overview

**QUAEST.TECH** is an investment intelligence platform with a 3D voxel world interface. Users explore a Roman city where each building contains a different section of the site — stock scoring, options plays, backtesting, and market overview. The backend scans, scores, and backtests stocks across cybersecurity, energy, defense, and broad market sectors.

**Live at**: https://cyber.keltonshockey.com (SSL via Let's Encrypt, nginx reverse proxy)
**World**: https://cyber.keltonshockey.com/world (3D voxel city)
**VPS**: DigitalOcean at `64.23.150.209`, code at `/opt/cyberscreener`
**Repo**: `sniffer9793/cyberscreener` on GitHub

---

## Project Structure

```
cyberscreener2/
├── Dockerfile
├── railway.toml
├── api/
│   ├── main.py              # FastAPI app + all endpoints (~1,000 lines)
│   ├── scheduler.py         # Scheduled scan daemon (every 2 hours)
│   ├── backfill.py          # Historical data bootstrapping
│   ├── requirements.txt
│   ├── core/
│   │   ├── scanner.py       # Score computation engine (~1,743 lines)
│   │   ├── universe.py      # Stock universe + sector definitions (~103 lines)
│   │   └── timing.py        # Options timing intelligence (~413 lines)
│   ├── db/
│   │   ├── models.py        # SQLite schema + ORM helpers (~885 lines)
│   │   ├── migrate_timing.py
│   │   └── migrate_sectors.py
│   ├── backtest/
│   │   └── engine.py        # Quintile analysis, attribution, calibration (~508 lines)
│   └── intel/
│       ├── sec_filings.py   # SEC EDGAR + insider transactions
│       ├── sentiment.py     # FinBERT + keyword-bag sentiment
│       └── earnings_calendar.py
├── frontend/                # React + Vite SPA
│   ├── src/
│   │   ├── App.jsx          # Root router + data loading
│   │   ├── api/
│   │   │   ├── client.js    # Fetch wrapper with JWT auth
│   │   │   └── endpoints.js # All API endpoint functions
│   │   ├── auth/
│   │   │   ├── AuthContext.jsx  # JWT auth state management
│   │   │   ├── LoginPage.jsx
│   │   │   ├── RegisterPage.jsx
│   │   │   └── QuaestorCreator.jsx  # Character creation
│   │   ├── pages/
│   │   │   ├── BasilicaPage.jsx   # Overview (market indices, killer plays, leaders)
│   │   │   ├── ConvictionPage.jsx # Stock scores, breakdowns, intel layers
│   │   │   ├── AnvilPage.jsx      # Options plays, weight tuner, Reality Check
│   │   │   ├── ArchivePage.jsx    # Backtest, calibration, research
│   │   │   └── WorldPage.jsx      # 3D voxel game + building panel integration
│   │   ├── components/
│   │   │   ├── ui/           # Card, Badge, ScoreBar, BreakdownPanel, BuildingPanel, etc.
│   │   │   ├── charts/       # SvgAreaChart, SvgPriceChart, SvgBarChart, etc.
│   │   │   └── layout/       # Header, NavBar, Footer
│   │   ├── game/
│   │   │   ├── VoxelGame.jsx      # React wrapper for Three.js world
│   │   │   ├── config.js          # Constants, building defs, brand colors
│   │   │   ├── entities/
│   │   │   │   └── NPCData.js     # NPC registry (dialogs, behaviors, sprites)
│   │   │   └── voxel/
│   │   │       ├── VoxelWorld.js       # Main scene orchestrator (~860 lines)
│   │   │       ├── VoxelMeshBuilder.js # Per-building mesh groups
│   │   │       ├── BuildingDecorator.js # Architectural features (roofs, columns, etc.)
│   │   │       ├── TextureAtlas.js     # Procedural 128×128 texture atlas (50 slots)
│   │   │       ├── SpriteGenerator.js  # Procedural Roman character sprite sheets
│   │   │       ├── PlayerController.js # WASD movement, camera-relative, billboard sprite
│   │   │       ├── VoxelNPC.js         # NPC patrol/wander/idle + dialog
│   │   │       └── CameraController.js # 3rd-person orbit, follow-cam
│   │   ├── theme/            # CSS variables, global styles, animations
│   │   └── utils/            # formatters, scoring helpers
│   ├── scripts/
│   │   └── generate-map.mjs  # Tiled-format JSON map generator
│   ├── public/assets/maps/   # Generated roman-city.json
│   └── dist/                 # Production build (committed for VPS deploy)
└── scripts/
```

---

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Backend | FastAPI 0.115.6 + Uvicorn 0.34.0 (Python 3.11) |
| Database | SQLite at `/data/db/cyberscreener.db` |
| Frontend | React 19 + Vite 7 SPA |
| 3D Engine | Three.js (voxel renderer, procedural textures/sprites) |
| Data Sources | yfinance, SEC EDGAR, Yahoo Finance, HuggingFace FinBERT |
| Deployment | DigitalOcean VPS (systemd + nginx + Let's Encrypt) |

---

## The 3D World

The game world is a Roman city built with Three.js voxel rendering. Each building maps to a section of the site:

| Building | Site Tab | Content |
|----------|----------|---------|
| **Basilica Julia** | Overview | Market indices, killer plays, momentum signals, leaders |
| **The Curia** | Conviction Board | Long-term stock scores, breakdowns, intel layers, charts |
| **The Subura** | The Anvil | Options plays, weight tuner, Reality Check scoring |
| **The Tabularium** | The Archive | Backtesting, quintile analysis, calibration, research |

**Building entry**: Walking inside a building triggers a full-screen `BuildingPanel` overlay with the corresponding site content. Player can dismiss with ESC, click outside, or walk out.

### Key 3D Features
- **3rd-person orbit camera** with auto-follow behind player (right-click to orbit)
- **Procedural texture atlas** (128×128 canvas, 8×8 grid, NearestFilter pixel art)
- **Procedural character sprites** (7 types: player, legionary, senator, merchant, scholar, guard, vendor)
- **Sky dome** with gradient (warm blue → golden horizon)
- **Ground shadows** under buildings and trees
- **Atmospheric fog** for depth layering (near=25, far=90)
- **Mediterranean lighting** (warm ambient + hemisphere fill + directional sun)
- **Indoor/outdoor transitions** (hide exterior walls/roof, zoom camera, dim outdoor lights)
- **Historically accurate roofs** (pitched terracotta, nave roof, flat terracotta, slate turrets)
- **NPC behaviors** (patrol, wander, idle with dialog system)

### Map Generation
Run `node frontend/scripts/generate-map.mjs` to regenerate the Tiled-format JSON map. Includes 4 buildings, forum plaza, natural landscape (rocky edges, boulders, pond, dirt paths, trees).

---

## Local Development

```bash
# Backend
cd api
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python backfill.py --months 6  # Bootstrap historical data
uvicorn main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev  # Vite dev server on :5173
```

## Production Deployment (DigitalOcean VPS)

**Deploy workflow**: Build frontend → commit dist → merge to main → push → SSH deploy

```bash
# On Mac
cd frontend && npm run build
git add dist/ && git commit -m "build"
# Merge worktree branch to main if using worktrees
cd /path/to/cyberscreener2
git checkout main && git merge claude/wizardly-shamir --no-edit && git push origin main

# On VPS
ssh root@64.23.150.209 "cd /opt/cyberscreener && git pull origin main && sudo systemctl restart cyberscreener"
```

**Stack on VPS**: FastAPI (systemd service) + nginx reverse proxy + Let's Encrypt SSL.

---

## Testing

No formal test suite. Validation approaches:
- `GET /health` — basic health check
- `POST /calibrate?dry_run=true` — test weight calibration without applying
- `GET /backtest/score-vs-returns?days=180` — validate scoring accuracy
- Manual endpoint testing via curl or dashboard
- Frontend: `npm run build` checks for compilation errors

### Known Testing Gaps (from March 2026 review)
- No unit tests for scoring components (`score_long_term`, `score_options`)
- No tests for whale flow detection edge cases
- No validation of synthetic IV rank accuracy (hardcoded 0.6-1.8x multipliers)
- No tests for play generation logic or liquidity filtering
- No integration tests for scan → backtest → calibrate pipeline

---

## Architecture Notes

### Scoring System

**Long-Term Score (0-100)** — "Would you hold this for 1-3 years?"
- Rule of 40 (25 pts), Relative Valuation (20 pts), FCF Margin (15 pts)
- Technical Trend (15 pts), Earnings Quality (10 pts), Discount+Momentum (15 pts)

**Options Score (0-100)** — "Is there an asymmetric short-term trade?"
- Earnings Catalyst (25 pts), IV Context (20 pts), Directional Conviction (20 pts)
- Technical Setup (15 pts), Liquidity (10 pts), Asymmetry (10 pts)

**Sector-specific weights** defined in `api/core/universe.py` — profiles for SaaS, Energy, REIT, Defense, Financial.

### Stock Universe (~90+ tickers)
- **Cybersecurity**: CRWD, PANW, FTNT, ZS, OKTA, CYBR, NET, S, DDOG, PLTR, etc.
- **Energy**: CCJ, CEG, FSLR, NEE, EQIX, DLR, etc.
- **Defense**: LMT, RTX, NOC, GD, AVAV, KTOS, etc.
- **Broad**: S&P 500 / Nasdaq sectors (Tech, Finance, Health, Consumer, etc.)

### Database Schema (SQLite)
- `scans` — scan run metadata
- `scores` — per-ticker scores per scan (all components + technicals + fundamentals)
- `prices` — historical close prices
- `signals` — alert signals
- `score_weights` — calibration history
- `watchlist` — user-added custom tickers
- `earnings_dates` — multi-source earnings calendar
- `options_plays` — play P&L tracking
- `users` — JWT auth with augur profiles
- `augur_profiles` — character attributes (prudentia, audacia, sapientia, etc.)
- `refresh_tokens` — JWT rotation

### Intel Layers
- **SEC Filings**: Insider transactions (Form 4), analyst recommendations, 8-K filing counts
- **Sentiment**: FinBERT via HuggingFace API (falls back to keyword-bag)
- **Earnings Calendar**: Multi-source (DB → yfinance → FMP API → Yahoo scrape)
- **Whale Flow**: Unusual options activity detection from pre-fetched chains

---

## Important Files to Know

### Backend
- `api/main.py` — All API endpoints (~1,000 lines)
- `api/core/scanner.py` — Core scoring + play generation (~1,743 lines)
- `api/core/universe.py` — Stock universe + sector profiles
- `api/core/timing.py` — Options timing + horizon classification
- `api/db/models.py` — Database schema + queries
- `api/backtest/engine.py` — Backtesting + self-calibration

### Frontend
- `frontend/src/App.jsx` — Root router, data loading, auth flows
- `frontend/src/pages/WorldPage.jsx` — Game page + building panel integration
- `frontend/src/game/voxel/VoxelWorld.js` — Main 3D scene orchestrator
- `frontend/src/game/config.js` — Building defs, camera constants, brand colors
- `frontend/src/game/voxel/TextureAtlas.js` — Procedural texture generation
- `frontend/src/game/voxel/SpriteGenerator.js` — Procedural character sprites
- `frontend/src/components/ui/BuildingPanel.jsx` — Building overlay panel

---

## Common Tasks

### Adding a new ticker
Edit `api/core/universe.py` — add to appropriate sector list and assign scoring profile.

### Adding a new API endpoint
Add to `api/main.py`. Follow existing patterns (auth via JWT, background tasks for long-running ops).

### Changing score weights
Use `POST /calibrate` to auto-adjust, or edit defaults in `api/core/scanner.py`.

### Modifying the 3D world
- **Map layout**: Edit `frontend/scripts/generate-map.mjs`, run `node generate-map.mjs`
- **Building textures**: Edit `frontend/src/game/voxel/TextureAtlas.js` PAL colors or drawing functions
- **Character sprites**: Edit `frontend/src/game/voxel/SpriteGenerator.js` palettes or drawing
- **Building features**: Edit `frontend/src/game/voxel/BuildingDecorator.js`
- **Building defs**: Edit `frontend/src/game/config.js` BUILDING_DEFS
- **Camera/movement**: Edit `CameraController.js` or `PlayerController.js`
- **NPCs**: Edit `frontend/src/game/entities/NPCData.js`

### Adding content to a building
The building panel system is in `WorldPage.jsx`. Each building ID maps to a site tab component:
```
basilica   → <BasilicaPage />
curia      → <ConvictionPage />
subura     → <AnvilPage />
tabularium → <ArchivePage />
```
To change what content appears in a building, edit the `renderBuildingContent()` function in WorldPage.jsx.

### Frontend build + deploy
```bash
cd frontend && npm run build
# Commit dist/, merge to main, push, then SSH deploy
```

---

## Current State (as of March 2026)

- **~90+ tickers** across cyber/energy/defense/broad sectors
- **React SPA frontend** with 5 tabs (Basilica, Conviction, Anvil, Archive, World)
- **3D voxel world** with 4 buildings, each containing a site tab's content
- **Visual upgrades complete**: sky dome, shadows, fog, warm Mediterranean palette, procedural Roman sprites
- **Building-to-tab integration live**: walk into a building to access its tools
- **No formal test suite** — biggest risk for refactoring
- **Known issues**: synthetic IV rank uses unvalidated multipliers, whale flow has two entry points, play generation doesn't check option liquidity
