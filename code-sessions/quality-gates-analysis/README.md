# Quality-gate PIT analysis (run on `mill`)

Validation scripts for `api/core/quality_gates.py`. They read the point-in-time corpus
at `~/lt-recon-data/` on **mill** (427 price series + 422 SEC companyfacts; 127 monthly
snapshots 2014-12..2025-06) and are faithful to `~/mill-local-edits/lt_reconstruct.py`
(the decade LT reconstruction engine — see RESULT_LT_RECONSTRUCTION_2026-06-08).

Run order (on mill, from `~/mill-local-edits/`):
1. `qg_panel.py`   — build the enriched PIT panel (lt_score + every gate input) → `qg_panel.json`
2. `qg_sanity.py`  — coverage + faithfulness check (reproduces RESULT §7.2 component ICs)
3. `qg_analyze.py` — Phase-1: per-gate flag rate + flagged-vs-unflagged fwd-return/left-tail, both regimes
4. `qg_refine.py`  — Tier-A re-thresholding + organic-normalization simulation + earned-gate pipeline
5. `qg_gen.py`     — credit-cap normalization variant + the GEN before/after trace

Findings → `code-sessions/results/RESULT_QUALITY_GATES_2026-06-09.md`.
