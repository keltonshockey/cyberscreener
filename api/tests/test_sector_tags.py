"""
Sector taxonomy (UI_OVERHAUL_PLAN §4): the multi-tag map lives in the data layer
(core.sector_tags) and is persisted as the scores.sector_tags JSON column so the
UI chips are real, not client-inferred. Unit + end-to-end-through-save_scan.
"""
import os
import sys
import json
import sqlite3
import importlib
from pathlib import Path

import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.sector_tags import tags_for

SCHEMA = Path(__file__).parent / "fixtures" / "scores_schema.sql"


def test_curated_overlay_wins():
    assert tags_for("NVDA") == ["AI", "Semis", "Tech"]
    assert tags_for("nvda", "broad", "Technology") == ["AI", "Semis", "Tech"]


def test_fallback_from_sector_subsector():
    assert tags_for("FOO", "cyber", "") == ["Cyber", "Tech"]
    assert tags_for("BAR", "energy", "Uranium miners") == ["Energy", "Nuclear"]
    assert tags_for("BAZ", "broad", "Real Estate") == ["REITs"]
    assert tags_for("UNK", "broad", "Mystery") == ["Tech"]


def test_default_is_tech():
    assert tags_for("???", None, None) == ["Tech"]


@pytest.fixture
def models(tmp_path, monkeypatch):
    db_file = tmp_path / "test_tags.db"
    conn = sqlite3.connect(db_file)
    conn.executescript(SCHEMA.read_text())
    conn.commit()
    conn.close()
    monkeypatch.setenv("CYBERSCREENER_DB", str(db_file))
    import db.models as m
    importlib.reload(m)
    return m


def test_sector_tags_persisted_as_json(models):
    row = dict(
        ticker="NVDA", price=100.0, lt_score=70.0, opt_score=60.0, rc_score=55,
        sector="broad", subsector="Technology",
        sector_tags=["AI", "Semis", "Tech"],
        lt_breakdown={}, opt_breakdown={}, lt_reasons=[], opt_reasons=[],
    )
    sid, _ = models.save_scan([row])
    conn = models.get_db()
    raw = conn.execute(
        "SELECT sector_tags FROM scores WHERE scan_id=? AND ticker='NVDA'", (sid,)
    ).fetchone()[0]
    conn.close()
    assert json.loads(raw) == ["AI", "Semis", "Tech"]


def test_missing_tags_persist_as_empty_array(models):
    row = dict(
        ticker="ZZZ", price=10.0, lt_score=1.0, opt_score=1.0, rc_score=1,
        lt_breakdown={}, opt_breakdown={}, lt_reasons=[], opt_reasons=[],
    )
    sid, _ = models.save_scan([row])
    conn = models.get_db()
    raw = conn.execute(
        "SELECT sector_tags FROM scores WHERE scan_id=? AND ticker='ZZZ'", (sid,)
    ).fetchone()[0]
    conn.close()
    assert json.loads(raw) == []
