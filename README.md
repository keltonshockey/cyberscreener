# QUAEST.TECH

Investment intelligence platform with automated scanning, scoring, options play generation, and a 3D Roman city interface.

**Live**: [cyber.keltonshockey.com](https://cyber.keltonshockey.com)

## Architecture

- **Backend**: FastAPI + SQLite (Python 3.11), systemd services on DigitalOcean
- **Frontend**: React 19 + Vite 7 SPA
- **3D World**: Three.js voxel-based Roman city
- **Data**: yfinance, SEC EDGAR, FinBERT sentiment, whale flow detection
- **AI**: Claude API (Haiku) for play analysis

## Pages

| Route | Name | Purpose |
|-------|------|---------|
| `/` | Basilica | Market overview, killer plays, leaders, interactive RSI chart |
| `/conviction` | Conviction | Full scoring table, breakdowns, intel layers |
| `/pactum` | Pactum | Options play generation, RC scoring, AI analysis |
| `/ticker/:symbol` | Ticker Summary | Per-ticker LT + Opt breakdowns, charts, signals |
| `/archive` | Archive | Backtesting, quintile analysis, calibration |
| `/world` | World | 3D Roman city with building-to-page integration |

## Scoring

**LT Score (0-100)**: Rule of 40, Valuation, FCF Margin, Trend, Earnings Quality, Momentum
**Opt Score (0-100)**: Earnings Catalyst, IV Context, Directional, Technical, Liquidity, Asymmetry
**Reality Check (0-100)**: Trade Quality, Execution, Score Alignment, IV Context, Catalyst, Technical

## Local Development

```bash
# Backend
cd api
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# Tests (adds pytest + pytest-asyncio on top of the runtime deps)
pip install -r requirements-dev.txt
cd .. && make test

# Frontend
cd frontend
npm install
npm run dev  # Vite on :5173
```

## Deploy to Production

```bash
# Build + push
cd frontend && npm run build && cd ..
git add -A && git commit -m "deploy" && git push origin main

# Deploy on droplet
ssh root@cyber.keltonshockey.com "cd /opt/cyberscreener && git pull && cd frontend && npm run build && cd .. && systemctl restart cyberscreener.service cyberscreener-scheduler.service"
```

## Universe

~490+ tickers across cybersecurity, energy, defense, tech, health, financials, REITs, consumer, and industrials. Scanner runs every 30 minutes via systemd scheduler.
