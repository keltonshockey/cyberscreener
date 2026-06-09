"""
/signals/{ticker}/recent must emit §6b relevance metadata. Persisted metadata is
used when present; rows written before the metadata columns existed are classified
live (using the ticker's latest sector context) so the endpoint is always
authoritative without a re-scan.
"""
import os
import tempfile

_tmp = tempfile.mkdtemp()
os.environ.setdefault("CYBERSCREENER_DB", f"{_tmp}/test_sig.db")
os.environ.setdefault("JWT_SECRET", "test-secret-32-chars-minimum-pad!")
os.environ.setdefault("CYBERSCREENER_PASSWORD", "testpassword")

from fastapi.testclient import TestClient
from db.models import init_db, get_db

init_db()

from main import app

client = TestClient(app)


def _seed():
    conn = get_db()
    cur = conn.execute(
        "INSERT INTO scans (timestamp, tickers_scanned) VALUES ('2026-06-09 12:00:00', 1)"
    )
    scan_id = cur.lastrowid
    # latest score row gives the sector context (cyber) for live classification
    conn.execute(
        "INSERT INTO scores (scan_id, ticker, sector, breach_victim) VALUES (?, 'CRWD', 'cyber', 0)",
        (scan_id,),
    )
    # pre-§6b signal rows (no metadata columns set) with emoji-laden text
    conn.execute(
        "INSERT INTO signals (scan_id, ticker, signal_type, signal_text, impact) "
        "VALUES (?, 'CRWD', 'score', '🌋 Demand Signal — active threat landscape', 'neutral')",
        (scan_id,),
    )
    conn.execute(
        "INSERT INTO signals (scan_id, ticker, signal_type, signal_text, impact) "
        "VALUES (?, 'CRWD', 'score', '🚀 Rule of 40: 75 (elite)', 'neutral')",
        (scan_id,),
    )
    conn.commit()
    conn.close()


def test_recent_signals_emit_metadata_and_strip_emoji():
    _seed()
    r = client.get("/signals/CRWD/recent")
    assert r.status_code == 200
    sigs = r.json()["signals"]
    assert sigs, "expected seeded signals"
    by_text = {s["signal_text"]: s for s in sigs}

    # emoji stripped on the way out
    assert all("🌋" not in s["signal_text"] and "🚀" not in s["signal_text"] for s in sigs)

    demand = by_text["Demand Signal — active threat landscape"]
    # live-classified: cyber vendor → tailwind, cyber-demand context
    assert demand["polarity"] == "tailwind"
    assert demand["sector_context"] == "cyber-demand"
    assert demand["stack"] in ("options", "both")

    r40 = by_text["Rule of 40: 75 (elite)"]
    assert r40["stack"] == "lt"
    assert r40["polarity"] == "tailwind"


def test_invalid_ticker_rejected():
    # too long (>10 chars) → 400 from the endpoint's ticker guard
    assert client.get("/signals/AAAAAAAAAAAAA/recent").status_code == 400
