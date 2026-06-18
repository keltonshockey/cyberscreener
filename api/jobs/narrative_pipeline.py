"""
Narrative pipeline (mill-side, Grist) — drafts the per-ticker LT + ST story with
a LOCAL model (gemma3), grounds + fact-checks it, and writes `narratives.db`.

  * No Claude tokens by default. A claude-* model is refused unless `--escalate`
    is passed for exactly ONE ticker (the moat rule + token budget).
  * Reads the live system READ-ONLY via `GET /scores/latest` (the endpoint the
    part-1 result file names) + light cited SEC/news facts. NEVER writes to
    `cyberscreener.db`, never calls scoring/weight/journal code.
  * Output is explanation only — it cannot feed back into a score, weight, or
    journal row, so it cannot contaminate the v2-baseline gate cohort.
  * stdlib + the single LiteLLM HTTP call. Every source is isolated and
    defensive: a failure logs and the rest proceed.

Run on mill:
    cd api && python -m jobs.narrative_pipeline                # lazy: view_queue + stale
    cd api && python -m jobs.narrative_pipeline --ticker HPE   # one ticker
    cd api && python -m jobs.narrative_pipeline --ticker HPE --escalate --model claude-sonnet
    cd api && python -m jobs.narrative_pipeline --dry-run      # don't write / clear queue
"""

import os
import sys
import json
import time
import hashlib
import logging
import argparse
import urllib.request
from datetime import datetime, timedelta

# Allow `python jobs/narrative_pipeline.py` as well as `python -m jobs...`.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from db.narratives import (
    get_narratives_db, upsert_narrative, init_narratives_db,
    ST_TTL_HOURS, LT_TTL_DAYS,
)
from jobs.narrative_grist import call_grist, resolve_model, DEFAULT_MODEL
from jobs.narrative_facts import assemble_facts, peers_for
from jobs.narrative_verify import verify

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("narrative_pipeline")

DEFAULT_API_BASE = os.environ.get("CYBERSCREENER_API_BASE", "https://quaest.tech")

# Snapshot fields pulled from a /scores/latest row (the signal spine the model
# explains). Names match the `scores` table columns surfaced by the endpoint.
_LT_COMPONENTS = [
    "lt_valuation", "lt_rule_of_40", "lt_fcf_margin", "lt_trend",
    "lt_earnings_quality", "lt_discount_momentum",
]
_OPT_COMPONENTS = [
    "opt_asymmetry", "opt_iv_context", "opt_directional",
    "opt_technical", "opt_liquidity", "opt_earnings_catalyst",
]
_EXTRA_SIGNALS = [
    "lt_score", "opt_score", "rc_score", "whale_score", "sentiment_score",
    "sentiment_bull_pct", "rsi", "iv_30d", "iv_rank", "pc_ratio", "beta",
    "vol_ratio", "price", "market_cap", "sector", "days_to_earnings",
]


# ── Input assembly (read-only) ────────────────────────────────────────────────

def fetch_latest_scores(api_base: str = DEFAULT_API_BASE, limit: int = 600) -> dict:
    """One read-only GET /scores/latest. Returns {TICKER: row}. [] on failure."""
    url = f"{api_base.rstrip('/')}/scores/latest?limit={limit}"
    try:
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except Exception as e:  # noqa: BLE001
        logger.warning("fetch /scores/latest failed: %s", e)
        return {}
    return {r.get("ticker", "").upper(): r for r in body.get("results", []) if r.get("ticker")}


def _num(v):
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float)):
        return v
    return v


def build_signal_snapshot(row: dict) -> dict:
    """Extract the signal spine the narrative must explain from a scores row."""
    snap = {"lt": {}, "opt": {}}
    for k in _LT_COMPONENTS:
        if row.get(k) is not None:
            snap["lt"][k] = _num(row[k])
    for k in _OPT_COMPONENTS:
        if row.get(k) is not None:
            snap["opt"][k] = _num(row[k])
    for k in _EXTRA_SIGNALS:
        if row.get(k) is not None:
            snap[k] = _num(row[k])
    # combined conviction = the killer-plays / Pactum sort (CLAUDE.md)
    if row.get("opt_score") is not None and row.get("lt_score") is not None:
        snap["combined_conviction"] = round(row["opt_score"] * 0.6 + row["lt_score"] * 0.4, 1)
    snap["peers"] = peers_for(row.get("sector"))
    return snap


def snapshot_hash(snapshot: dict) -> str:
    return hashlib.sha256(
        json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:16]


# ── Work selection (lazy on-demand) ───────────────────────────────────────────

def _is_past_ttl(generated_at, max_age) -> bool:
    if not generated_at:
        return True
    try:
        return (datetime.utcnow() - datetime.fromisoformat(generated_at)) > max_age
    except (ValueError, TypeError):
        return True


def select_work(explicit=None) -> list:
    """Tickers to process: explicit arg, else the lazy view_queue + stale rows
    (past ST/LT TTL). Snapshot-drift staleness is decided at write time."""
    if explicit:
        return [t.upper() for t in explicit]
    conn = get_narratives_db()
    try:
        queued = [r["ticker"] for r in conn.execute(
            "SELECT ticker FROM view_queue WHERE requested = 1"
        ).fetchall()]
        rows = conn.execute(
            "SELECT ticker, st_generated_at, lt_generated_at FROM narratives"
        ).fetchall()
    finally:
        conn.close()
    stale = [
        r["ticker"] for r in rows
        if _is_past_ttl(r["st_generated_at"], timedelta(hours=ST_TTL_HOURS))
        or _is_past_ttl(r["lt_generated_at"], timedelta(days=LT_TTL_DAYS))
    ]
    # dedupe, preserve order (queued first — those are actively looked at)
    seen, out = set(), []
    for t in queued + stale:
        u = t.upper()
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def clear_view_queue(tickers: list) -> None:
    if not tickers:
        return
    conn = get_narratives_db()
    try:
        conn.executemany(
            "DELETE FROM view_queue WHERE ticker = ?", [(t.upper(),) for t in tickers]
        )
        conn.commit()
    finally:
        conn.close()


# ── Generation ────────────────────────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "You explain why a quantitative signal looks the way it does for ONE stock "
    "ticker. Use ONLY the provided signal values and the provided facts. Do NOT "
    "recall the company from memory or invent figures. No generic boilerplate "
    "(never write phrases like 'leading provider of' or 'world-class'). Every "
    "claim must trace to a provided signal value or a provided source id. "
    "Cite a source by its id (e.g. 'sec1', 'news2'); use the id 'signal' for a "
    "claim grounded directly on a signal value. Do NOT put citation markers "
    "inside the story prose — keep lt_story and st_story clean readable text; "
    "citations belong only in the claims array. Output STRICT JSON only, no "
    "prose around it, with keys: lt_story, st_story, claims, used_sources. "
    "'claims' is a list of at most 8 {text, source_id} objects covering the key "
    "points. 'used_sources' is a list of the source ids you cited."
)


def build_generation_messages(ticker: str, snapshot: dict, facts: list) -> list:
    facts_view = [
        {"id": f["id"], "kind": f["kind"], "title": f["title"], "url": f["url"], "date": f.get("date")}
        for f in facts
    ]
    user = {
        "ticker": ticker,
        "instruction": (
            "Write two grounded sections. "
            "long-term story (<=120 words): business + economics + competition + the "
            "LT-score logic — name the driving LT components and their values and say "
            "why LT is high or low. "
            "short-term story (<=100 words): the play logic — momentum, whale/flow, "
            "sentiment, IV and directional context — why a play fires now, or why no "
            "play. Reference the opt components and their values."
        ),
        "signal_snapshot": snapshot,
        "facts": facts_view,
    }
    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(user)},
    ]


def parse_generation(raw: str) -> dict | None:
    """Tolerant JSON parse: handles ```json fences and leading/trailing prose by
    extracting the outermost {...} object."""
    if not raw:
        return None
    s = raw.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s.lower().startswith("json"):
            s = s[4:]
    try:
        return json.loads(s)
    except (ValueError, TypeError):
        pass
    a, b = s.find("{"), s.rfind("}")
    if a != -1 and b != -1 and b > a:
        try:
            return json.loads(s[a:b + 1])
        except (ValueError, TypeError):
            return None
    return None


# ── Signals-only floor ────────────────────────────────────────────────────────

def signals_only_narrative(ticker: str, snapshot: dict) -> dict:
    """Deterministic, numbers-only stories used when verification fails twice.
    Explains the figures, makes NO external claims, carries no sources."""
    lt = snapshot.get("lt_score")
    opt = snapshot.get("opt_score")
    lt_drivers = ", ".join(
        f"{k.replace('lt_', '').replace('_', ' ')} {v}"
        for k, v in (snapshot.get("lt") or {}).items()
    )
    opt_drivers = ", ".join(
        f"{k.replace('opt_', '').replace('_', ' ')} {v}"
        for k, v in (snapshot.get("opt") or {}).items()
    )
    lt_story = (
        f"{ticker} long-term score is {lt}. Component points: {lt_drivers}."
        if lt is not None else f"{ticker} long-term components: {lt_drivers}."
    )
    rsi = snapshot.get("rsi")
    iv = snapshot.get("iv_rank")
    st_story = (
        f"{ticker} options score is {opt}. Component points: {opt_drivers}."
        + (f" RSI {round(rsi)}." if isinstance(rsi, (int, float)) else "")
        + (f" IV rank {round(iv)}." if isinstance(iv, (int, float)) else "")
    )
    return {"lt_story": lt_story, "st_story": st_story, "claims": [], "used_sources": []}


# ── Build one record (network-free given snapshot + facts + injected llm) ──────

def build_narrative_record(
    ticker: str,
    snapshot: dict,
    facts: list,
    llm,
    model: str = DEFAULT_MODEL,
    escalate: bool = False,
    critic=None,
    max_attempts: int = 2,
) -> dict:
    """Generate -> verify -> (one regen) -> signals-only floor. Returns a record
    dict ready for upsert. `llm(messages, model)` and optional `critic(parsed,
    snapshot, facts)->reasons` are injected so this is fully testable offline."""
    now = datetime.utcnow().isoformat(timespec="seconds")
    last_reasons = []
    for attempt in range(1, max_attempts + 1):
        try:
            raw = llm(build_generation_messages(ticker, snapshot, facts), model)
        except Exception as e:  # noqa: BLE001 - a model error must not crash the run
            logger.warning("%s generation attempt %d failed: %s", ticker, attempt, e)
            break
        parsed = parse_generation(raw)
        if parsed is None:
            last_reasons = ["parse_error"]
            logger.info("%s attempt %d: unparseable JSON", ticker, attempt)
            continue
        ok, reasons = verify(parsed, snapshot, facts)
        if ok:
            # Rules gates (the hard guarantees) passed. The gemma3 critic is a
            # SOFT semantic check: if it flags the draft we keep the
            # rules-verified prose but downgrade confidence to "low" (the UI
            # surfaces a low-confidence note) — we do NOT discard grounded
            # content over a noisy local critic.
            confidence = "ok"
            if critic is not None:
                crit = critic(parsed, snapshot, facts) or []
                if crit:
                    confidence = "low"
                    logger.info("%s critic flagged -> confidence=low: %s", ticker, crit)
            used = set(parsed.get("used_sources") or [])
            sources = [
                {"title": f["title"], "url": f["url"]}
                for f in facts if f["id"] in used
            ]
            return {
                "ticker": ticker, "lt_story": parsed.get("lt_story"),
                "st_story": parsed.get("st_story"), "sources": sources,
                "signal_snapshot": snapshot, "snapshot_hash": snapshot_hash(snapshot),
                "confidence": confidence, "model": model,
                "lt_generated_at": now, "st_generated_at": now,
            }
        last_reasons = reasons
        logger.info("%s attempt %d failed verify: %s", ticker, attempt, reasons)

    # Floor — never ship unverified prose.
    logger.info("%s -> signals-only floor (last reasons: %s)", ticker, last_reasons)
    floor = signals_only_narrative(ticker, snapshot)
    return {
        "ticker": ticker, "lt_story": floor["lt_story"], "st_story": floor["st_story"],
        "sources": [], "signal_snapshot": snapshot, "snapshot_hash": snapshot_hash(snapshot),
        "confidence": "low", "model": f"{model}+floor",
        "lt_generated_at": now, "st_generated_at": now,
    }


# ── Orchestration ─────────────────────────────────────────────────────────────

def run(
    explicit=None,
    escalate: bool = False,
    model: str | None = None,
    dry_run: bool = False,
    api_base: str = DEFAULT_API_BASE,
    use_critic: bool = True,
) -> dict:
    init_narratives_db()
    chosen_model = resolve_model(escalate=escalate, model=model)
    if escalate and (not explicit or len(explicit) != 1):
        raise SystemExit("--escalate requires exactly one --ticker")

    work = select_work(explicit)
    if not work:
        logger.info("no work (empty view_queue, nothing stale)")
        return {"processed": [], "model": chosen_model}

    scores = fetch_latest_scores(api_base)
    if not scores:
        logger.warning("no scores available — aborting this run (live system unreachable?)")
        return {"processed": [], "model": chosen_model, "error": "no_scores"}

    def _llm(messages, m):
        return call_grist(messages, model=m, escalate=escalate)

    def _critic(parsed, snapshot, facts):
        if not use_critic:
            return []
        return critic_pass(parsed, snapshot, facts, _llm, chosen_model)

    processed, handled = [], []
    for ticker in work:
        try:
            row = scores.get(ticker)
            if not row:
                logger.info("%s not in latest scores — skipping", ticker)
                continue
            snapshot = build_signal_snapshot(row)
            facts = assemble_facts(ticker, sector=row.get("sector"))
            rec = build_narrative_record(
                ticker, snapshot, facts, _llm, model=chosen_model,
                escalate=escalate, critic=(_critic if use_critic else None),
            )
            if not dry_run:
                upsert_narrative(**rec)
            processed.append({"ticker": ticker, "confidence": rec["confidence"], "sources": len(rec["sources"])})
            handled.append(ticker)
        except Exception as e:  # noqa: BLE001 - isolate per ticker
            logger.warning("%s failed, continuing: %s", ticker, e)
            continue

    if not dry_run:
        clear_view_queue(handled)
    return {"processed": processed, "model": chosen_model, "dry_run": dry_run}


def critic_pass(parsed: dict, snapshot: dict, facts: list, llm, model: str) -> list:
    """Optional second gemma3 pass: ask the model to flag any sentence not
    supported by the provided signals/facts. Returns reason codes ([] == clean).
    Defensive — a critic error never blocks the (already rules-verified) draft."""
    try:
        msg = [
            {"role": "system", "content": (
                "You are a strict fact-checker. Given a draft narrative, the signal "
                "snapshot, and the facts, answer STRICT JSON {\"unsupported\": bool, "
                "\"notes\": str}. unsupported=true if any sentence makes a claim or "
                "cites a figure not present in the snapshot or facts."
            )},
            {"role": "user", "content": json.dumps({
                "draft": {"lt_story": parsed.get("lt_story"), "st_story": parsed.get("st_story")},
                "signal_snapshot": snapshot,
                "facts": [{"id": f["id"], "title": f["title"]} for f in facts],
            })},
        ]
        verdict = parse_generation(llm(msg, model))
        if verdict and verdict.get("unsupported"):
            return ["critic_unsupported"]
    except Exception as e:  # noqa: BLE001
        logger.info("critic pass skipped (%s)", e)
    return []


def main(argv=None):
    ap = argparse.ArgumentParser(description="Narrative pipeline (mill-side, gemma3)")
    ap.add_argument("--ticker", action="append", help="process this ticker (repeatable)")
    ap.add_argument("--escalate", action="store_true", help="permit a claude-* model for ONE ticker")
    ap.add_argument("--model", help="model override (only honored with --escalate)")
    ap.add_argument("--dry-run", action="store_true", help="generate but do not write narratives.db")
    ap.add_argument("--api-base", default=DEFAULT_API_BASE, help="live system base URL (read-only)")
    ap.add_argument("--no-critic", action="store_true", help="skip the gemma3 critic pass")
    args = ap.parse_args(argv)

    result = run(
        explicit=args.ticker, escalate=args.escalate, model=args.model,
        dry_run=args.dry_run, api_base=args.api_base, use_critic=not args.no_critic,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
