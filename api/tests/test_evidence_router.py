"""
Evidence store + router (SESSION-V3B-EVIDENCE).

The fixtures under fixtures/evidence/ are REAL generator output, not
hand-written imitations: GATE_READ_2026-08-10.md came from
api/core/gate_report.py run against a fixture options_plays DB whose cohort C
trips the pre-registered fail rule (n=90 >= 80, win_rate 0.40 < 0.50), and the
ic-report-2026-05-22 pair came from research/harness/ic_report.py run against
the deterministic fixture DB in test_ic_harness.py. Parsing THOSE files is the
round-trip contract; if either generator's format drifts, these tests are the
tripwire.

Also pinned here: honest empty state (never a 500, never fabricated), UNKNOWN
on malformed input with the raw markdown preserved, filename-date staleness
with a frozen "now", and the strict-name gate that closes path traversal.
"""
import importlib
import shutil
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from core import evidence_artifacts as ea

FIXTURES = Path(__file__).parent / "fixtures" / "evidence"
GATE_FIXTURE = FIXTURES / "GATE_READ_2026-08-10.md"
IC_MD_FIXTURE = FIXTURES / "ic-report-2026-05-22.md"
IC_CSV_FIXTURE = FIXTURES / "ic-report-2026-05-22.csv"


@pytest.fixture
def evdir(tmp_path):
    d = tmp_path / "evidence"
    d.mkdir()
    for f in (GATE_FIXTURE, IC_MD_FIXTURE, IC_CSV_FIXTURE):
        shutil.copy(f, d / f.name)
    return d


# -- Parser round-trips on the real generated artifacts -----------------------

def test_gate_parser_reads_real_fail_verdict():
    parsed = ea.parse_gate_md(GATE_FIXTURE.read_text())
    assert parsed["verdict"] == "FAIL"
    m = parsed["headline_metrics"]
    assert m["n_decided"] == 90
    assert m["win_rate"] == pytest.approx(0.400)
    assert m["expectancy"] == pytest.approx(0.002)


def test_gate_parser_pass_and_no_verdict_lines():
    # Same renderer, other verdict branches (gate_report.evaluate wording).
    base = GATE_FIXTURE.read_text()
    passed = base.replace(
        "**FAIL RULE TRIGGERED: stop new feature work, re-architect signals**",
        "**PASS BAR MET (powered)**")
    assert ea.parse_gate_md(passed)["verdict"] == "PASS"
    nv = base.replace(
        "**FAIL RULE TRIGGERED: stop new feature work, re-architect signals**",
        "**NO VERDICT - cohort C n=12 (pass needs n>=384; fail rule arms at n>=80)**")
    assert ea.parse_gate_md(nv)["verdict"] == "NO_VERDICT"


def test_ic_md_parser_reads_real_summary():
    parsed = ea.parse_ic_md(IC_MD_FIXTURE.read_text())
    assert parsed["supported"] == 1
    assert parsed["noise"] == 29
    assert parsed["insufficient"] == 0
    assert parsed["hypotheses"] == 30
    assert "First run in this directory" in parsed["delta_paragraph"]


def test_ic_csv_parser_reads_real_table():
    table = ea.parse_ic_csv(IC_CSV_FIXTURE.read_text())
    assert table is not None and len(table) == 30
    by_key = {(r["series"], r["horizon"]): r for r in table}
    supported = by_key[("lt_valuation", 21)]
    assert supported["verdict"] == "SUPPORTED"
    assert supported["same_sign"] is True
    assert isinstance(supported["mean_ic"], float)
    assert by_key[("opt_liquidity", 5)]["verdict"] == "noise"


def test_ic_csv_parser_nan_cells_become_null_not_nan():
    text = IC_CSV_FIXTURE.read_text().replace("noise,", "noise,")
    lines = text.splitlines()
    parts = lines[1].split(",")
    parts[4] = ""  # empty mean_ic cell (how pandas writes NaN)
    lines[1] = ",".join(parts)
    table = ea.parse_ic_csv("\n".join(lines))
    assert table[0]["mean_ic"] is None  # not NaN - NaN is not JSON


# -- Malformed artifacts: UNKNOWN, raw preserved, never a crash ---------------

def test_malformed_gate_md_is_unknown_not_fabricated():
    garbage = "This is not a gate read at all.\nNo table. No verdict.\n"
    parsed = ea.parse_gate_md(garbage)
    assert parsed["verdict"] == "UNKNOWN"
    assert parsed["headline_metrics"] == {
        "n_decided": None, "win_rate": None, "expectancy": None}


def test_truncated_gate_md_before_verdict_is_unknown():
    # Cut the real artifact off before the Rule evaluation section: the table
    # still parses, the verdict must NOT be guessed from it.
    md = GATE_FIXTURE.read_text().split("## Rule evaluation")[0]
    parsed = ea.parse_gate_md(md)
    assert parsed["verdict"] == "UNKNOWN"
    assert parsed["headline_metrics"]["n_decided"] == 90  # honest partials ok


def test_malformed_ic_csv_returns_none_not_partial():
    assert ea.parse_ic_csv("series,wrong,header\n1,2,3\n") is None
    assert ea.parse_ic_csv("") is None


def test_latest_serves_raw_md_even_when_malformed(evdir):
    (evdir / "GATE_READ_2026-08-10.md").write_text("corrupted beyond parse\n")
    payload = ea.latest_payload(str(evdir), today=date(2026, 8, 10))
    assert payload["status"] == "ok"
    assert payload["gate"]["verdict"] == "UNKNOWN"
    assert payload["gate"]["raw_md"] == "corrupted beyond parse\n"


# -- Staleness: filename dates against a frozen now ---------------------------

def test_stale_at_nine_days_fresh_at_seven():
    nine = ea.staleness(date(2026, 8, 1), date(2026, 8, 1),
                        today=date(2026, 8, 10))
    assert nine["gate_days"] == 9 and nine["ic_days"] == 9
    assert nine["is_stale"] is True
    seven = ea.staleness(date(2026, 8, 3), date(2026, 8, 3),
                         today=date(2026, 8, 10))
    assert seven["gate_days"] == 7 and seven["ic_days"] == 7
    assert seven["is_stale"] is False


def test_stale_when_only_one_artifact_is_old():
    s = ea.staleness(date(2026, 8, 9), date(2026, 7, 1),
                     today=date(2026, 8, 10))
    assert s["is_stale"] is True


def test_staleness_judged_from_filename_not_mtime(evdir):
    import os
    # Touch the files to "now": if staleness read mtimes this would be fresh.
    for f in evdir.iterdir():
        os.utime(f)
    payload = ea.latest_payload(str(evdir), today=date(2026, 8, 20))
    assert payload["stale"]["gate_days"] == 10  # from GATE_READ_2026-08-10
    assert payload["stale"]["is_stale"] is True


# -- Empty states -------------------------------------------------------------

def test_empty_dir_yields_no_artifacts_yet(tmp_path):
    d = tmp_path / "empty"
    d.mkdir()
    payload = ea.latest_payload(str(d))
    assert payload == {"status": "no_artifacts_yet", "gate": None,
                       "ic": None, "stale": None}
    hist = ea.history_payload(str(d))
    assert hist["status"] == "no_artifacts_yet"
    assert hist["gate_reads"] == [] and hist["ic_reports"] == []


def test_missing_dir_yields_no_artifacts_yet(tmp_path):
    payload = ea.latest_payload(str(tmp_path / "never-created"))
    assert payload["status"] == "no_artifacts_yet"


def test_unrecognized_files_are_ignored_not_served(tmp_path):
    d = tmp_path / "junk"
    d.mkdir()
    (d / "notes.txt").write_text("x")
    (d / "GATE_READ_notadate.md").write_text("x")
    (d / "ic-report-2026-99-99.md").write_text("x")
    assert ea.latest_payload(str(d))["status"] == "no_artifacts_yet"


# -- Path safety --------------------------------------------------------------

def test_traversal_and_crafted_names_are_rejected():
    for name in (
        "../GATE_READ_2026-08-10.md",
        "../../etc/passwd",
        "GATE_READ_2026-08-10.md/../../evil",
        "/etc/passwd",
        "GATE_READ_2026-08-10.md\x00.txt",
        "ic-report-2026-05-22.md.sh",
        "GATE_READ_2026-08-10.MD",
        "",
    ):
        assert ea.is_safe_artifact_name(name) is False, name


def test_reader_refuses_unvalidated_name(evdir):
    with pytest.raises(ValueError):
        ea._read_artifact(str(evdir), "../secrets.env")
    with pytest.raises(ValueError):
        ea._read_artifact(str(evdir), "sync.log")


def test_valid_names_pass_the_gate():
    assert ea.is_safe_artifact_name("GATE_READ_2026-08-02.md")
    assert ea.is_safe_artifact_name("ic-report-2026-08-03.md")
    assert ea.is_safe_artifact_name("ic-report-2026-08-03-02.csv")
    assert ea.is_safe_artifact_name("ic-report-2026-08-03-smoke.md")


# -- History ordering ---------------------------------------------------------

def test_history_lists_newest_first(evdir):
    (evdir / "GATE_READ_2026-08-02.md").write_text("older\n")
    hist = ea.history_payload(str(evdir))
    gate_files = [e["file"] for e in hist["gate_reads"]]
    assert gate_files == ["GATE_READ_2026-08-10.md", "GATE_READ_2026-08-02.md"]


# -- API smoke through the real app -------------------------------------------

@pytest.fixture
def client(evdir, monkeypatch):
    monkeypatch.setenv("CYBERSCREENER_EVIDENCE_DIR", str(evdir))
    import main
    return TestClient(main.app)


def test_evidence_latest_endpoint_smoke(client):
    resp = client.get("/evidence/latest")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["gate"]["verdict"] == "FAIL"
    assert data["gate"]["date"] == "2026-08-10"
    assert data["gate"]["headline_metrics"]["n_decided"] == 90
    assert "FAIL RULE TRIGGERED" in data["gate"]["raw_md"]
    assert data["ic"]["supported"] == 1
    assert data["ic"]["hypotheses"] == 30
    assert len(data["ic"]["table"]) == 30
    assert data["ic"]["csv_file"] == "ic-report-2026-05-22.csv"
    assert set(data["stale"]) == {"gate_days", "ic_days", "is_stale"}


def test_evidence_history_endpoint_smoke(client):
    resp = client.get("/evidence/history")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["gate_reads"][0]["file"] == "GATE_READ_2026-08-10.md"
    assert len(data["ic_reports"]) == 2


def test_evidence_latest_empty_env_is_200(tmp_path, monkeypatch):
    monkeypatch.setenv("CYBERSCREENER_EVIDENCE_DIR",
                       str(tmp_path / "not-there"))
    import main
    resp = TestClient(main.app).get("/evidence/latest")
    assert resp.status_code == 200
    assert resp.json()["status"] == "no_artifacts_yet"


def test_router_module_never_touches_the_prod_db():
    import re
    import routers.evidence as rev
    importlib.reload(rev)
    for mod in (rev, ea):
        src = Path(mod.__file__).read_text()
        imports = re.findall(r"^\s*(?:import|from)\s+([\w.]+)", src, re.M)
        for name in imports:
            root = name.split(".")[0]
            assert root not in ("db", "sqlite3", "pandas", "numpy"), (
                f"{mod.__name__} imports {name} - evidence is FILE-only, "
                f"stdlib-parsed, and never opens the DB")
