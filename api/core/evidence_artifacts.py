"""
Evidence artifact store + parsers (SESSION-V3B-EVIDENCE).

Reads the gate-read markdown and IC-report markdown/CSV pairs that mill
delivers into the evidence directory, and turns them into the JSON the public
Evidence page serves. Three properties are load-bearing:

1. FILES ONLY. This module never opens cyberscreener.db (or any sqlite DB).
   Its entire input surface is a directory of delivered artifacts.
2. STDLIB ONLY. No pandas, no numpy - the droplet has 1 GB of RAM and these
   run in the request path. The generators (which do use pandas) run on mill.
3. HONEST FAILURE. A malformed artifact is reported with verdict UNKNOWN and
   its raw markdown still served; a parser that fabricates a verdict is worse
   than no parser. Missing artifacts produce an explicit empty state, never
   an invented one and never a 500.

Filename contracts (dates are taken from the FILENAME, never from mtime -
rsync redelivery resets mtimes, the name is the ground truth):

  gate read : GATE_READ_YYYY-MM-DD.md          (api/core/gate_report.py)
  IC report : ic-report-YYYY-MM-DD[-suffix].md (research/harness/ic_report.py)
              ic-report-YYYY-MM-DD[-suffix].csv
              where suffix is the generator's append-only -02/-03 counter
              and/or a --label tag.

Anything not matching those exact patterns is ignored by listing and refused
by the reader - that is the whole path-traversal story: a name that is not a
valid artifact name never reaches open().
"""
import csv
import io
import os
import re
from datetime import date, datetime

# Default matches the forced-command wrapper's pinned destination
# (bin/evidence-rsync-only.sh). One constant, two sides.
DEFAULT_EVIDENCE_DIR = "/opt/cyberscreener/data/evidence"

# Either artifact older than this (days, judged from the filename date) marks
# the page stale: both generators run weekly, so > 8 days means a missed run.
STALE_DAYS = 8

GATE_NAME_RE = re.compile(r"^GATE_READ_(\d{4}-\d{2}-\d{2})\.md$")
IC_NAME_RE = re.compile(r"^ic-report-(\d{4}-\d{2}-\d{2})((?:-[A-Za-z0-9_]+)*)\.(md|csv)$")

VERDICTS = ("PASS", "FAIL", "NO_VERDICT", "UNKNOWN")


def evidence_dir() -> str:
    return os.environ.get("CYBERSCREENER_EVIDENCE_DIR", DEFAULT_EVIDENCE_DIR)


def is_safe_artifact_name(name: str) -> bool:
    """True only for an exact, whitelisted artifact filename.

    This is the single gate every filename passes before it is joined to the
    evidence directory. The patterns are anchored and admit no separators, no
    dots beyond the extension, no '..' - so a crafted name (traversal, absolute
    path, null byte, anything) simply is not an artifact name.
    """
    if not isinstance(name, str) or not name:
        return False
    if "/" in name or "\\" in name or "\x00" in name or ".." in name:
        return False
    return bool(GATE_NAME_RE.match(name) or IC_NAME_RE.match(name))


def _read_artifact(dirpath: str, name: str) -> str:
    """Read one artifact by validated name; refuses anything else."""
    if not is_safe_artifact_name(name):
        raise ValueError(f"not a valid artifact name: {name!r}")
    path = os.path.join(dirpath, name)
    # Belt and suspenders: the validated name cannot escape, but prove it.
    real_dir = os.path.realpath(dirpath)
    if os.path.commonpath([real_dir, os.path.realpath(path)]) != real_dir:
        raise ValueError(f"artifact path escapes the evidence dir: {name!r}")
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        return f.read()


def _parse_date(s: str):
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


def list_artifacts(dirpath: str) -> dict:
    """Inventory of valid artifacts in the directory, newest first.

    Returns {"gate": [names], "ic_md": [names], "ic_csv": [names]}. Names that
    fail validation (or dates that do not parse) are excluded, not guessed at.
    """
    out = {"gate": [], "ic_md": [], "ic_csv": []}
    try:
        names = os.listdir(dirpath)
    except OSError:
        return out
    for name in names:
        if not is_safe_artifact_name(name):
            continue
        m = GATE_NAME_RE.match(name)
        if m:
            if _parse_date(m.group(1)):
                out["gate"].append(name)
            continue
        m = IC_NAME_RE.match(name)
        if m and _parse_date(m.group(1)):
            out["ic_md" if m.group(3) == "md" else "ic_csv"].append(name)
    # Newest first: ISO date sorts lexicographically; the generator's -02/-03
    # counter sorts higher within a date, which is exactly "latest run wins".
    for k in out:
        out[k].sort(reverse=True)
    return out


def artifact_date(name: str):
    """The date embedded in a validated artifact filename (never mtime)."""
    m = GATE_NAME_RE.match(name) or IC_NAME_RE.match(name)
    return _parse_date(m.group(1)) if m else None


# ---------------------------------------------------------------------------
# Gate-read markdown parser
# ---------------------------------------------------------------------------

def parse_gate_md(md: str) -> dict:
    """Parse a GATE_READ markdown into verdict + headline metrics.

    Verdict comes from the bolded verdict line the generator always emits
    (historical and current format alike): a line reading **PASS BAR MET...**,
    **FAIL RULE TRIGGERED...** or **NO VERDICT...**. Headline metrics come
    from the '## Cohort C' table's '>=65' aggregate row. Any ambiguity ->
    UNKNOWN with metrics null; the raw markdown is the fallback of record.
    """
    verdict = "UNKNOWN"
    metrics = {"n_decided": None, "win_rate": None, "expectancy": None}
    if not md or not md.strip():
        return {"verdict": verdict, "headline_metrics": metrics}

    for line in md.splitlines():
        s = line.strip()
        if s.startswith("**") and s.endswith("**") and len(s) > 4:
            body = s.strip("*").strip()
            if body.startswith("PASS BAR MET"):
                verdict = "PASS"
            elif body.startswith("FAIL RULE TRIGGERED"):
                verdict = "FAIL"
            elif body.startswith("NO VERDICT"):
                verdict = "NO_VERDICT"
            break

    table = _cohort_c_gate_row(md)
    if table is not None:
        metrics = table
    return {"verdict": verdict, "headline_metrics": metrics}


def _num(cell: str):
    cell = cell.strip()
    if cell in ("", "-", "--"):
        return None
    try:
        return float(cell)
    except ValueError:
        return None


def _cohort_c_gate_row(md: str):
    """The n_decided / win_rate / expectancy of Cohort C's '>=65' row.

    Column positions are resolved from the table's own header, so a reordered
    column moves with us; a header we cannot resolve returns None (UNKNOWN
    metrics) instead of misreading a different column as a win rate.
    """
    lines = md.splitlines()
    in_c = False
    header = None
    for line in lines:
        s = line.strip()
        if s.startswith("## "):
            in_c = s.startswith("## Cohort C")
            header = None
            continue
        if not in_c or not s.startswith("|"):
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if header is None:
            if "bucket" in [c.lower() for c in cells]:
                header = [c.lower() for c in cells]
            continue
        if set(c.strip("-: ") for c in cells) <= {""}:
            continue  # the |---|---| separator row
        if cells and cells[0] == ">=65":
            try:
                nd = header.index("n_decided")
                wr = header.index("win_rate")
                ex = header.index("expectancy")
            except ValueError:
                return None
            if max(nd, wr, ex) >= len(cells):
                return None
            n = _num(cells[nd])
            return {
                "n_decided": int(n) if n is not None else None,
                "win_rate": _num(cells[wr]),
                "expectancy": _num(cells[ex]),
            }
    return None


# ---------------------------------------------------------------------------
# IC report parsers (markdown summary + CSV table)
# ---------------------------------------------------------------------------

def parse_ic_md(md: str) -> dict:
    """Verdict counts, hypothesis count and the delta paragraph from the md.

    Everything is optional-null: a summary bullet we cannot read stays None
    rather than becoming a zero that looks like a real count.
    """
    out = {"supported": None, "noise": None, "insufficient": None,
           "hypotheses": None, "delta_paragraph": None}
    if not md or not md.strip():
        return out

    m = re.search(r"\|\s*\*\*hypotheses tested\*\*\s*\|\s*\*\*(\d+)\*\*", md)
    if m:
        out["hypotheses"] = int(m.group(1))

    m = re.search(r"^- SUPPORTED:\s*\*\*(\d+)\*\*\s*of\s*(\d+)", md, re.M)
    if m:
        out["supported"] = int(m.group(1))
        if out["hypotheses"] is None:
            out["hypotheses"] = int(m.group(2))
    m = re.search(r"^- noise:\s*(\d+)", md, re.M)
    if m:
        out["noise"] = int(m.group(1))
    m = re.search(r"^- INSUFFICIENT:\s*(\d+)", md, re.M)
    if m:
        out["insufficient"] = int(m.group(1))

    delta = _section_body(md, "## Delta vs previous run")
    if delta:
        out["delta_paragraph"] = delta
    return out


def _section_body(md: str, heading: str):
    lines = md.splitlines()
    buf, in_section = [], False
    for line in lines:
        if line.strip().startswith("## "):
            if in_section:
                break
            in_section = line.strip().startswith(heading)
            continue
        if in_section:
            buf.append(line)
    body = "\n".join(buf).strip()
    return body or None


IC_CSV_COLUMNS = ["series", "horizon", "n_days", "n_obs", "mean_ic", "std_ic",
                  "t_raw", "t_adj", "ic_h1", "ic_h2", "same_sign", "verdict",
                  "note"]
_IC_INT_COLS = {"horizon", "n_days", "n_obs"}
_IC_FLOAT_COLS = {"mean_ic", "std_ic", "t_raw", "t_adj", "ic_h1", "ic_h2"}


def parse_ic_csv(text: str):
    """The per-hypothesis table from the generator's CSV, as list-of-dicts.

    Returns None (not a partial table) if the header is not the generator's -
    a half-parsed table under a verdict headline would be fabricated evidence.
    NaN/empty numeric cells become None so the JSON stays valid; json.dumps
    would otherwise emit bare NaN, which is not JSON.
    """
    if not text or not text.strip():
        return None
    try:
        rows = list(csv.reader(io.StringIO(text)))
    except csv.Error:
        return None
    if not rows or rows[0] != IC_CSV_COLUMNS:
        return None
    out = []
    for raw in rows[1:]:
        if len(raw) != len(IC_CSV_COLUMNS):
            return None
        rec = {}
        for key, cell in zip(IC_CSV_COLUMNS, raw):
            cell = cell.strip()
            if key in _IC_INT_COLS:
                try:
                    rec[key] = int(float(cell))
                except ValueError:
                    rec[key] = None
            elif key in _IC_FLOAT_COLS:
                try:
                    v = float(cell)
                    rec[key] = v if v == v and abs(v) != float("inf") else None
                except ValueError:
                    rec[key] = None
            elif key == "same_sign":
                rec[key] = cell.lower() == "true"
            else:
                rec[key] = cell
        out.append(rec)
    return out


# ---------------------------------------------------------------------------
# Staleness + assembled payloads
# ---------------------------------------------------------------------------

def staleness(gate_date, ic_date, today=None) -> dict:
    """Days since each artifact's FILENAME date, and the stale flag.

    `today` is injectable for tests; the router passes date.today(). A missing
    artifact contributes null days and does not by itself set the flag - its
    absence is already reported as the artifact being null.
    """
    today = today or date.today()
    gate_days = (today - gate_date).days if gate_date else None
    ic_days = (today - ic_date).days if ic_date else None
    is_stale = ((gate_days is not None and gate_days > STALE_DAYS)
                or (ic_days is not None and ic_days > STALE_DAYS))
    return {"gate_days": gate_days, "ic_days": ic_days, "is_stale": is_stale}


def latest_payload(dirpath: str, today=None) -> dict:
    """The full GET /evidence/latest body. Never raises for a bad artifact."""
    inv = list_artifacts(dirpath)
    if not inv["gate"] and not inv["ic_md"] and not inv["ic_csv"]:
        return {"status": "no_artifacts_yet", "gate": None, "ic": None,
                "stale": None}

    gate = None
    gate_date = None
    if inv["gate"]:
        name = inv["gate"][0]
        gate_date = artifact_date(name)
        try:
            raw = _read_artifact(dirpath, name)
        except (OSError, ValueError):
            raw = None
        parsed = (parse_gate_md(raw) if raw is not None
                  else {"verdict": "UNKNOWN",
                        "headline_metrics": {"n_decided": None,
                                             "win_rate": None,
                                             "expectancy": None}})
        gate = {"file": name, "date": gate_date.isoformat(),
                "verdict": parsed["verdict"],
                "headline_metrics": parsed["headline_metrics"],
                "raw_md": raw}

    ic = None
    ic_date = None
    if inv["ic_md"]:
        name = inv["ic_md"][0]
        ic_date = artifact_date(name)
        try:
            raw = _read_artifact(dirpath, name)
        except (OSError, ValueError):
            raw = None
        parsed = parse_ic_md(raw or "")
        # Pair the CSV by identical stem; fall back to the newest CSV of the
        # same date, else no table (null, not an invented one).
        table = None
        csv_name = None
        stem = name[:-3]  # strip ".md"
        want = stem + ".csv"
        if want in inv["ic_csv"]:
            csv_name = want
        else:
            same_day = [c for c in inv["ic_csv"]
                        if artifact_date(c) == ic_date]
            csv_name = same_day[0] if same_day else None
        if csv_name:
            try:
                table = parse_ic_csv(_read_artifact(dirpath, csv_name))
            except (OSError, ValueError):
                table = None
        ic = {"file": name, "csv_file": csv_name,
              "date": ic_date.isoformat(),
              "supported": parsed["supported"], "noise": parsed["noise"],
              "insufficient": parsed["insufficient"],
              "hypotheses": parsed["hypotheses"],
              "delta_paragraph": parsed["delta_paragraph"],
              "table": table, "raw_md": raw}

    return {"status": "ok", "gate": gate, "ic": ic,
            "stale": staleness(gate_date, ic_date, today=today)}


def history_payload(dirpath: str) -> dict:
    """The GET /evidence/history body: what exists, newest first."""
    inv = list_artifacts(dirpath)
    if not inv["gate"] and not inv["ic_md"] and not inv["ic_csv"]:
        return {"status": "no_artifacts_yet", "gate_reads": [], "ic_reports": []}

    def entry(name):
        d = artifact_date(name)
        return {"file": name, "date": d.isoformat() if d else None}

    return {
        "status": "ok",
        "gate_reads": [entry(n) for n in inv["gate"]],
        "ic_reports": [entry(n) for n in inv["ic_md"] + inv["ic_csv"]],
    }
