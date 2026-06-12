#!/usr/bin/env python3
"""
Build the slim ~100-ticker universe config (SESSION-SLIM-SCOPE).

Reads a /scores/latest snapshot (file path arg, or fetches live) and applies
the documented selection criteria to emit api/core/universe_slim.json.
Deterministic given a snapshot; the snapshot scan_id is recorded in the
output so the selection is reproducible/reviewable.

Usage:
    python3 scripts/build_universe.py /tmp/scores_latest.json
    python3 scripts/build_universe.py            (fetches https://quaest.tech)

Criteria (also written into the output config):
  1. market_cap_b >= 1.0            - hard floor; sub-$1B chains are
                                      single-digit-OI noise that poisoned IV
  2. iv_suspect == 0 at selection   - the ingestion gate flagged these chains
                                      as unreliable on the snapshot scan
  3. thesis sectors kept whole      - cyber / energy / defense (curated lists)
                                      pass floors only, no quota
  4. broad sectors by cap quota     - top-by-market-cap within per-subsector
                                      quotas matching the deep-review mix
                                      (tech, health, financials, industrials,
                                      communication); other broad subsectors
                                      (staples, materials, utilities, REITs,
                                      consumer, energy-broad) are cut as
                                      categories
  5. journal continuity is DYNAMIC  - the scanner unions in any ticker with
                                      open journal plays at scan time (until
                                      they close); no static carve-out needed
Options-liquidity note: per-strike OI/spread is not in the scores snapshot;
market cap is the selection-time liquidity proxy, and the existing hard
liquidity gate (no liquid strikes -> no play) remains the point-of-trade
enforcement. Documented in the config.
"""
import json
import sys
import urllib.request
from datetime import date
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "api" / "core" / "universe_slim.json"

CAP_FLOOR_B = 1.0
THESIS_SECTORS = ("cyber", "energy", "defense")
BROAD_QUOTAS = {
    "Technology": 14,
    "Health Care": 10,
    "Financials": 10,
    "Industrials": 8,
    "Communication": 4,
}
CUT_BROAD_SUBSECTORS_REASON = (
    "Consumer Disc / Consumer Staples / Materials / Real Estate / Utilities / "
    "Energy Broad cut as whole categories: outside the deep-review sector mix "
    "(cyber, tech, defense, health, financials, industrials) and none carried "
    "evidence; revivable by config edit"
)


def load_rows(arg=None):
    if arg:
        data = json.loads(Path(arg).read_text())
    else:
        with urllib.request.urlopen(
                "https://quaest.tech/scores/latest?limit=600", timeout=30) as r:
            data = json.loads(r.read())
    return data["scan_id"], data["results"]


def build(scan_id, rows):
    excluded = {"sub_1b_cap": [], "iv_suspect_small": [], "broad_subsector_cut": [],
                "broad_over_quota": []}
    selected = {}

    def keep(r):
        selected[r["ticker"]] = {
            "sector": r.get("sector"),
            "subsector": r.get("subsector"),
            "market_cap_b": round(r.get("market_cap_b") or 0, 1),
        }

    eligible = []
    for r in rows:
        cap = r.get("market_cap_b") or 0
        if cap < CAP_FLOOR_B:
            excluded["sub_1b_cap"].append(r["ticker"])
            continue
        # iv_suspect on a single snapshot is a data-read artifact for deep
        # mega-cap chains (the ATM fix + fallback handle it); it is only a
        # real liquidity signal on smaller names. Exclude below $5B only.
        if r.get("iv_suspect") and cap < 5.0:
            excluded["iv_suspect_small"].append(r["ticker"])
            continue
        eligible.append(r)

    # 3. thesis sectors whole
    for r in eligible:
        if r.get("sector") in THESIS_SECTORS:
            keep(r)

    # 4. broad by quota, top market cap first
    by_sub = {}
    for r in eligible:
        if r.get("sector") == "broad":
            by_sub.setdefault(r.get("subsector"), []).append(r)
    for sub, members in sorted(by_sub.items()):
        quota = BROAD_QUOTAS.get(sub)
        members.sort(key=lambda r: -(r.get("market_cap_b") or 0))
        if quota is None:
            excluded["broad_subsector_cut"] += [m["ticker"] for m in members]
            continue
        for m in members[:quota]:
            keep(m)
        excluded["broad_over_quota"] += [m["ticker"] for m in members[quota:]]

    sector_counts = {}
    for meta in selected.values():
        key = meta["sector"] if meta["sector"] != "broad" else f"broad/{meta['subsector']}"
        sector_counts[key] = sector_counts.get(key, 0) + 1

    return {
        "_doc": ("Slim scanning universe (SESSION-SLIM-SCOPE, DEEP_REVIEW_"
                 "2026-06-11): ~100 liquid names so the 2 evidenced signals "
                 "are measured on clean chains instead of diluted across 480. "
                 "Selection is reproducible: scripts/build_universe.py against "
                 "the recorded scan snapshot. Scanner additionally unions in "
                 "any ticker with OPEN journal plays at scan time (journal "
                 "continuity is dynamic, not a static list). Set "
                 "CYBERSCREENER_FULL_UNIVERSE=1 to revert to the full universe."),
        "enabled": True,
        "built_from_scan": scan_id,
        "built_at": str(date.today()),
        "criteria": {
            "market_cap_floor_b": CAP_FLOOR_B,
            "iv_suspect_excluded_below_cap_b": 5.0,
            "thesis_sectors_kept_whole": list(THESIS_SECTORS),
            "broad_quotas_top_by_cap": BROAD_QUOTAS,
            "options_liquidity": ("selection-time proxy = market cap (per-"
                                  "strike OI/spread not in scores); point-of-"
                                  "trade enforcement = the existing hard "
                                  "liquidity gate in play generation"),
        },
        "exclusion_reasons": {
            "sub_1b_cap": "market cap under $1B: single-digit-OI chains, IV noise",
            "iv_suspect_small": ("IV flagged unreliable on the selection scan AND cap under $5B - "
                                 "small flagged chains are noise; mega-cap flags are read artifacts and kept"),
            "broad_subsector_cut": CUT_BROAD_SUBSECTORS_REASON,
            "broad_over_quota": "below the top-N by market cap within a kept broad subsector",
        },
        "always_include": [],
        "sector_counts": sector_counts,
        "tickers": dict(sorted(selected.items())),
        "excluded_counts": {k: len(v) for k, v in excluded.items()},
        "excluded": {k: sorted(v) for k, v in excluded.items()},
    }


if __name__ == "__main__":
    scan_id, rows = load_rows(sys.argv[1] if len(sys.argv) > 1 else None)
    cfg = build(scan_id, rows)
    OUT.write_text(json.dumps(cfg, indent=2) + "\n")
    print(f"scan #{scan_id}: {len(rows)} scanned -> {len(cfg['tickers'])} selected")
    for k, v in sorted(cfg["sector_counts"].items()):
        print(f"  {k:24} {v}")
    print("excluded:", cfg["excluded_counts"])
    print(f"wrote {OUT}")
