#!/usr/bin/env python3
import os, sys, requests, time
from datetime import datetime

FMP_KEY = os.environ.get("EARNINGS_API_KEY", "")
BASE_URL = os.environ.get("CYBERSCREENER_URL", "http://64.23.150.209:8000")
PASSWORD = os.environ.get("CYBERSCREENER_PASSWORD", "cybershield2026")

ALL_TICKERS = [
    "CRWD","PANW","FTNT","ZS","CSCO","OKTA","CYBR","SAIL",
    "NET","AKAM","CHKP","QLYS","TENB","RPD","FFIV",
    "S","DDOG","MSFT","GOOGL","AVBO","GEN","OTEX","RDWR",
    "IBM","NTCT","ATEN","VRNS","VRNT",
    "CACI","LDOS","SAIC","BAH","BBAI","PLTR",
    "TLS","OSPN","JAMF","DT","ESTC","RBBN",
    "CCJ","CEG","VST","NRG","ETR","GEV",
    "FSLR","AES","NEE","EQIX","DLR","AMT",
    "AVAV","KTOS","LHX","NOC","RTX","GD","LMT","LUNR","RDW",
]

if not FMP_KEY:
    print("❌ EARNINGS_API_KEY not set")
    sys.exit(1)

dates = {}
for ticker in ALL_TICKERS:
    url = f"https://financialmodelingprep.com/api/v3/historical/earning_calendar/{ticker}?limit=4&apikey={FMP_KEY}"
    try:
        resp = requests.get(url, timeout=10)
        data = resp.json()
        today = datetime.today().date()
        for item in data if isinstance(data, list) else []:
            raw = item.get("date","")
            if not raw: continue
            try:
                d = datetime.strptime(raw[:10], "%Y-%m-%d").date()
                if d >= today:
                    dates[ticker] = raw[:10]
                    print(f"  ✅ {ticker:<6} → {raw[:10]}")
                    break
            except: continue
        else:
            print(f"  ⚠️  {ticker:<6} → not found")
    except Exception as e:
        print(f"  ❌ {ticker}: {e}")
    time.sleep(0.3)

print(f"\nFound {len(dates)} dates. Seeding to server...")
resp = requests.post(f"{BASE_URL}/earnings/seed",
    json={"dates": dates, "password": PASSWORD}, timeout=30)
print(resp.json())
