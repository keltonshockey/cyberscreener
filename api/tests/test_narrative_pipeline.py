"""
Offline tests for the mill-side narrative pipeline. No network, no real model —
the LiteLLM call is injected/mocked. Pins the anti-slop gates and the floor.
"""
import os
import json
import tempfile

_tmp = tempfile.mkdtemp(prefix="narrative-pipe-test-")
os.environ["CYBERSCREENER_NARRATIVES_DB"] = os.path.join(_tmp, "narratives.db")
os.environ.setdefault("CYBERSCREENER_DB", os.path.join(_tmp, "prod.db"))

import pytest

from jobs import narrative_verify as V
from jobs import narrative_grist as G
import jobs.narrative_pipeline as P
from jobs.narrative_pipeline import (
    build_signal_snapshot, parse_generation, signals_only_narrative,
    build_narrative_record, snapshot_hash,
)
import db.narratives as N

# ── Fixtures ──────────────────────────────────────────────────────────────────

SNAPSHOT = {
    "lt": {"lt_valuation": 18.0, "lt_rule_of_40": 12.0, "lt_fcf_margin": 9.0},
    "opt": {"opt_asymmetry": 8.0, "opt_iv_context": 14.0, "opt_directional": 11.0},
    "lt_score": 71.0, "opt_score": 64.0, "rsi": 42.0, "iv_rank": 35.0,
    "sector": "tech", "combined_conviction": 66.2,
}
FACTS = [
    {"id": "sec1", "kind": "sec_filing", "title": "10-K filed 2026-02-01",
     "url": "https://www.sec.gov/x", "date": "2026-02-01"},
    {"id": "news1", "kind": "news", "title": "Company beats on revenue",
     "url": "https://news.example/a", "date": "Tue, 10 Jun 2026"},
]


def _good_parsed():
    return {
        "lt_story": "LT score 71 is driven by valuation 18 and rule of 40 12; FCF margin 9 supports durability.",
        "st_story": "Opt score 64: IV context 14 with RSI 42 and IV rank 35 favor an asymmetric long.",
        "claims": [
            {"text": "LT score 71", "source_id": "signal"},
            {"text": "revenue beat", "source_id": "news1"},
        ],
        "used_sources": ["news1"],
    }


# ── Gate: number-match ────────────────────────────────────────────────────────

def test_number_match_catches_planted_wrong_figure():
    bad = _good_parsed()
    bad["lt_story"] = "LT score 99 is elite."  # 99 not in snapshot
    ok, reasons = V.verify(bad, SNAPSHOT, FACTS)
    assert not ok
    assert "number_mismatch" in reasons

    # control: the unmodified draft passes the number gate
    assert V.check_numbers(_good_parsed()["lt_story"], SNAPSHOT, FACTS) == []


# ── Gate: citation ────────────────────────────────────────────────────────────

def test_citation_check_flags_unsupported_claim():
    bad = _good_parsed()
    bad["claims"] = [{"text": "made up", "source_id": "nope"}]
    ok, reasons = V.verify(bad, SNAPSHOT, FACTS)
    assert not ok
    assert "unsupported_citation" in reasons


# ── Gate: cite-only-fetched ───────────────────────────────────────────────────

def test_cite_only_fetched_rejects_fabricated_source():
    bad = _good_parsed()
    bad["used_sources"] = ["news9"]  # not among fetched facts
    ok, reasons = V.verify(bad, SNAPSHOT, FACTS)
    assert not ok
    assert "fabricated_source" in reasons


# ── Gate: boilerplate ─────────────────────────────────────────────────────────

def test_boilerplate_rejected():
    bad = _good_parsed()
    bad["lt_story"] = "The company is a leading provider of cloud software."
    ok, reasons = V.verify(bad, SNAPSHOT, FACTS)
    assert not ok
    assert "boilerplate" in reasons


# ── Happy path through build_narrative_record ─────────────────────────────────

def test_good_draft_yields_ok_confidence_and_sources():
    def llm(messages, model):
        return json.dumps(_good_parsed())
    rec = build_narrative_record("HPE", SNAPSHOT, FACTS, llm, model="gemma3", critic=None)
    assert rec["confidence"] == "ok"
    assert rec["model"] == "gemma3"
    assert rec["sources"] == [{"title": "Company beats on revenue", "url": "https://news.example/a"}]
    assert rec["snapshot_hash"] == snapshot_hash(SNAPSHOT)


# ── Floor: two failures -> signals-only low-confidence ────────────────────────

def test_two_failures_fall_to_signals_only_floor():
    calls = {"n": 0}

    def bad_llm(messages, model):
        calls["n"] += 1
        # always invalid: planted wrong number + boilerplate
        return json.dumps({
            "lt_story": "LT score 99 — a leading provider of widgets.",
            "st_story": "Buy now.",
            "claims": [], "used_sources": [],
        })

    rec = build_narrative_record("HPE", SNAPSHOT, FACTS, bad_llm, model="gemma3", critic=None)
    assert calls["n"] == 2          # initial + exactly one regen
    assert rec["confidence"] == "low"
    assert rec["model"].endswith("+floor")
    assert rec["sources"] == []
    # the floor explains the actual numbers
    assert "71" in rec["lt_story"]
    assert "64" in rec["st_story"]


# ── Critic is a SOFT gate: flags downgrade confidence, keep the prose ─────────

def test_critic_flag_downgrades_confidence_but_keeps_content():
    def llm(messages, model):
        return json.dumps(_good_parsed())

    def critic(parsed, snapshot, facts):
        return ["critic_unsupported"]

    rec = build_narrative_record("HPE", SNAPSHOT, FACTS, llm, model="gemma3", critic=critic)
    assert rec["confidence"] == "low"          # downgraded
    assert rec["model"] == "gemma3"            # NOT the +floor model
    assert rec["lt_story"].startswith("LT score 71")  # rules-verified prose kept
    assert rec["sources"]                      # sources preserved


# ── JSON-shape parse tolerance ────────────────────────────────────────────────

def test_parse_tolerance_handles_fences_and_prose():
    fenced = "```json\n" + json.dumps(_good_parsed()) + "\n```"
    assert parse_generation(fenced)["lt_story"].startswith("LT score 71")

    prose = "Sure! Here is the JSON:\n" + json.dumps(_good_parsed()) + "\nHope that helps."
    assert parse_generation(prose)["st_story"].startswith("Opt score 64")

    assert parse_generation("not json at all") is None


# ── Snapshot assembly from a scores row ───────────────────────────────────────

def test_build_signal_snapshot_extracts_components_and_conviction():
    row = {
        "ticker": "HPE", "lt_score": 71, "opt_score": 64, "lt_valuation": 18,
        "opt_iv_context": 14, "rsi": 42, "sector": "tech",
    }
    snap = build_signal_snapshot(row)
    assert snap["lt"]["lt_valuation"] == 18
    assert snap["opt"]["opt_iv_context"] == 14
    assert snap["combined_conviction"] == round(64 * 0.6 + 71 * 0.4, 1)
    assert snap["peers"]  # tech peer set is non-empty


# ── Moat rule: claude refused without escalate ────────────────────────────────

def test_call_grist_refuses_claude_without_escalate():
    with pytest.raises(PermissionError):
        G.call_grist([{"role": "user", "content": "hi"}], model="claude-sonnet")

    # resolve_model never returns claude unless escalate is set
    assert G.resolve_model(escalate=False, model="claude-sonnet") == "gemma3"
    assert G.resolve_model(escalate=True, model="claude-sonnet") == "claude-sonnet"


# ── Canonical narratives path: store default == sync destination, no drop-in ──

CANONICAL = "/opt/cyberscreener/data/narratives/narratives.db"


def test_default_narratives_path_is_canonical_droplet_location():
    # The default is the sync wrapper's pinned destination — so a fresh pull +
    # restart serves the delivered file with no systemd drop-in.
    assert N.CANONICAL_NARRATIVES_DB == CANONICAL
    assert N._default_narratives_path() == CANONICAL


def test_default_no_longer_derived_from_prod_db_path(monkeypatch):
    # Old behavior derived narratives.db from CYBERSCREENER_DB's dir; the new
    # default must ignore the prod DB path entirely.
    monkeypatch.setenv("CYBERSCREENER_DB", "/some/other/place/cyberscreener.db")
    assert N._default_narratives_path() == CANONICAL


def test_db_path_falls_back_to_canonical_when_env_unset(monkeypatch):
    monkeypatch.delenv("CYBERSCREENER_NARRATIVES_DB", raising=False)
    assert N._db_path() == CANONICAL


def test_db_path_honors_explicit_env_override(monkeypatch):
    monkeypatch.setenv("CYBERSCREENER_NARRATIVES_DB", "/tmp/custom/narratives.db")
    assert N._db_path() == "/tmp/custom/narratives.db"


# ── --universe selection: generate for every scored ticker, ignore the queue ──

def _stub_record(ticker, snapshot, facts, llm, **kw):
    return {
        "ticker": ticker, "lt_story": "x", "st_story": "y", "sources": [],
        "signal_snapshot": snapshot, "snapshot_hash": "h", "confidence": "ok",
        "model": "gemma3", "lt_generated_at": "t", "st_generated_at": "t",
    }


def test_universe_mode_processes_every_scored_ticker(monkeypatch):
    scores = {
        "HPE": {"ticker": "HPE", "sector": "tech"},
        "IBM": {"ticker": "IBM", "sector": "tech"},
        "AMD": {"ticker": "AMD", "sector": "semis"},
    }
    monkeypatch.setattr(P, "fetch_latest_scores", lambda *a, **k: scores)
    monkeypatch.setattr(P, "assemble_facts", lambda *a, **k: [])
    monkeypatch.setattr(P, "build_narrative_record", _stub_record)
    # If universe selection leaned on the queue this would matter; it must not.
    monkeypatch.setattr(P, "select_work", lambda *a, **k: (_ for _ in ()).throw(
        AssertionError("universe mode must not call select_work")))

    res = P.run(universe=True, dry_run=True, use_critic=False)
    assert sorted(p["ticker"] for p in res["processed"]) == ["AMD", "HPE", "IBM"]


def test_universe_mode_aborts_cleanly_when_no_scores(monkeypatch):
    monkeypatch.setattr(P, "fetch_latest_scores", lambda *a, **k: {})
    res = P.run(universe=True, dry_run=True, use_critic=False)
    assert res.get("error") == "no_scores"
    assert res["processed"] == []


def test_non_universe_run_still_uses_select_work(monkeypatch):
    # The lazy/explicit path is unchanged: it consults select_work and no-ops
    # when there is nothing queued or stale.
    monkeypatch.setattr(P, "select_work", lambda explicit=None: [])
    called = {"scores": False}
    monkeypatch.setattr(P, "fetch_latest_scores",
                        lambda *a, **k: called.__setitem__("scores", True) or {})
    res = P.run(universe=False, dry_run=True, use_critic=False)
    assert res["processed"] == []
    # empty work short-circuits before fetching scores (behavior preserved)
    assert called["scores"] is False
