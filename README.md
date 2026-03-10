# CyberScreener

Cybersecurity sector investment intelligence — automated scanning, scoring, and backtesting.

## Deploy to Railway

1. Push this repo to GitHub
2. Go to [railway.app](https://railway.app) and create a new project from the repo
3. Add a persistent volume mounted at `/data/db`
4. Set environment variable: `CYBERSCREENER_PASSWORD=your_password_here`
5. Deploy — the dashboard will be available at your Railway URL

The scheduler runs automatically every 2 hours, scanning all cybersecurity tickers and building historical data for backtesting.

## Local Development

```bash
cd api
python3 -m venv venv && source venv/bin/activate
pip install -r requirements.txt
python backfill.py --months 6   # Bootstrap historical data
uvicorn main:app --reload --port 8000
```

Visit http://localhost:8000 — default password: `cyber2026`
