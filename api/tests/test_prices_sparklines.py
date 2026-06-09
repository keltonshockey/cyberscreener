"""
Inline price series (UI_OVERHAUL_PLAN §3): /prices/sparklines returns a real
recent close-price path per ticker for grid sparklines (replacing the client-side
[sma200, sma50, sma20, price] slope proxy). Batched + cached; this pins the shape
and the windowing.
"""
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("CYBERSCREENER_DB", f"{_tmp}/test_spark.db")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-minimum-pad!")
os.environ.setdefault("CYBERSCREENER_PASSWORD", "testpassword")

from fastapi.testclient import TestClient
from db.models import init_db, get_db

init_db()

from main import app

client = TestClient(app)


def _seed_prices():
    conn = get_db()
    rows = []
    for i in range(40):
        d = f"2026-{(i // 28) + 1:02d}-{(i % 28) + 1:02d}"
        rows.append(("NVDA", d, 100.0 + i))
        rows.append(("AMD", d, 50.0 + i * 0.5))
    conn.executemany(
        "INSERT OR IGNORE INTO prices (ticker, date, close_price) VALUES (?, ?, ?)", rows
    )
    conn.commit()
    conn.close()


def test_returns_recent_series_per_ticker():
    _seed_prices()
    r = client.get("/prices/sparklines?tickers=NVDA,AMD&points=30")
    assert r.status_code == 200
    body = r.json()
    assert body["points"] == 30
    assert set(body["series"].keys()) == {"NVDA", "AMD"}
    # last `points` closes, ascending — NVDA's most recent (largest) close is last
    nvda = body["series"]["NVDA"]
    assert len(nvda) == 30
    assert nvda == sorted(nvda)            # ascending for plotting
    assert nvda[-1] == 139.0               # 100 + 39 (latest)
    assert nvda[0] == 110.0                # window starts at the 30th-from-newest


def test_unknown_and_blank_tickers_are_safe():
    assert client.get("/prices/sparklines?tickers=ZZZZ").json()["series"] == {}
    assert client.get("/prices/sparklines?tickers=,,").json()["series"] == {}


def test_rejects_garbage_tickers():
    # non-alnum junk is filtered out, not crashed on
    r = client.get("/prices/sparklines?tickers=DROP TABLE;,NVDA")
    assert r.status_code == 200
    assert "NVDA" in r.json()["series"]
