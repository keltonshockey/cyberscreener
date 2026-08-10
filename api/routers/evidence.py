"""
Evidence router - the system telling the truth about itself.

Serves the pre-registered forward-test gate reads and the weekly IC reports
that mill delivers into the evidence directory (default
/opt/cyberscreener/data/evidence, override CYBERSCREENER_EVIDENCE_DIR).

ADDITIVE + FILE-ONLY. This router never opens cyberscreener.db, never imports
db.models, and cannot influence a score. Its inputs are markdown/CSV files;
its failure mode is an honest empty state or an UNKNOWN verdict with the raw
markdown attached - never a 500 for a missing or malformed artifact, and
never a fabricated verdict.

Contract:
  GET /evidence/latest  -> newest gate read + IC report, parsed, with a
                           staleness block (dates from FILENAMES, not mtimes).
  GET /evidence/history -> inventory of delivered artifacts, newest first.

Both endpoints take no client-supplied filenames or paths; every name they
touch is validated against the strict artifact patterns in
core.evidence_artifacts before it is joined to the directory.
"""
from fastapi import APIRouter

from core.evidence_artifacts import (
    evidence_dir, history_payload, latest_payload,
)

router = APIRouter(tags=["evidence"])


@router.get("/evidence/latest")
def get_evidence_latest():
    return latest_payload(evidence_dir())


@router.get("/evidence/history")
def get_evidence_history():
    return history_payload(evidence_dir())
