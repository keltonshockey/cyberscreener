"""
Forward-test play closure — settlement_v2.

Implements api/core/FORWARD_TEST_SEMANTICS.md (pre-registered 2026-06-09).
Pure outcome math is separated from DB access so tests can cover every payoff
branch without a database.

Replaces the legacy directional heuristic in scheduler._check_play_outcomes
(pct underlying move x direction x 4), which mis-scored non-directional
strategies (the 11 AAPL iron condors closed 2026-06-06 were recorded as
losses while settling inside their short strikes) and silently closed
plays with no price data as NULL-P&L 'closed' rows.
"""

import re
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)

CLOSE_METHOD = "settlement_v2"
SETTLEMENT_REACHBACK_DAYS = 3   # latest price in [expiry - 3d, expiry]
UNRESOLVABLE_GRACE_DAYS = 10    # past-expiry days to wait for price data


# ── Outcome result ────────────────────────────────────────────────────────────

@dataclass
class Outcome:
    status: str                              # 'closed' | 'unresolvable' | 'pending'
    outcome: Optional[str] = None            # 'win' | 'loss' | None
    win: Optional[int] = None                # 1 | 0 | None
    realized_pnl: Optional[float] = None     # $/share at settlement
    realized_return: Optional[float] = None  # fraction of cost (debit) or max risk (credit)
    settlement_price: Optional[float] = None
    settlement_date: Optional[str] = None
    reason: str = ""


# ── Parsing helpers (entry fields as filed — no reconstruction) ──────────────

def parse_strikes(strategy: str, strike) -> Optional[list]:
    """Parse the strike field into floats. Returns None if unparseable."""
    if strike is None:
        return None
    try:
        parts = [float(p) for p in str(strike).split("/")]
    except (ValueError, TypeError):
        return None
    s = (strategy or "").lower()
    if "condor" in s:
        ok = len(parts) == 4 and parts == sorted(parts) and parts[0] < parts[1] <= parts[2] < parts[3]
    elif "spread" in s:
        ok = len(parts) == 2 and parts[0] != parts[1]
    else:  # single-leg / straddle
        ok = len(parts) == 1 and parts[0] > 0
    return parts if ok else None


_CREDIT_RE = re.compile(r"Collect \$([0-9]+(?:\.[0-9]+)?)")


def extract_condor_credit(entry_price, notes: str, width: float) -> Optional[float]:
    """Credit c: entry_price if plausible (0 < c < width), else 'Collect $X' from notes."""
    if entry_price is not None and 0 < entry_price < width:
        return float(entry_price)
    m = _CREDIT_RE.search(notes or "")
    if m:
        c = float(m.group(1))
        if 0 < c < width:
            return c
    return None


def extract_debit(entry_price, notes: str, width: Optional[float]) -> Optional[float]:
    """Cost basis for debit strategies. Rejects rows that filed the underlying
    price in entry_price (early pre-fix rows): debit must be < spread width."""
    if entry_price is None or entry_price <= 0:
        return None
    if width is not None and entry_price >= width:
        return None
    return float(entry_price)


# ── Pure outcome computation ──────────────────────────────────────────────────

def compute_outcome(play: dict, settlement_price: float, settlement_date: str) -> Outcome:
    """Settlement-value outcome for one play. Never guesses: any missing or
    implausible input yields status='unresolvable' with a reason."""
    strategy = (play.get("strategy") or "").lower()
    strikes = parse_strikes(play.get("strategy"), play.get("strike"))
    s = settlement_price

    def closed(value: float, cost: float, risk: float) -> Outcome:
        pnl = value - cost
        ret = pnl / risk
        return Outcome(
            status="closed", outcome="win" if pnl > 0 else "loss",
            win=1 if pnl > 0 else 0,
            realized_pnl=round(pnl, 4), realized_return=round(ret, 4),
            settlement_price=s, settlement_date=settlement_date,
        )

    def unresolvable(reason: str) -> Outcome:
        return Outcome(status="unresolvable", reason=reason,
                       settlement_price=s, settlement_date=settlement_date)

    if strikes is None:
        return unresolvable(f"unparseable strike {play.get('strike')!r} for {play.get('strategy')!r}")

    entry_price = play.get("entry_price")
    notes = play.get("notes") or ""

    if "condor" in strategy:
        pl, ps, cs, cl = strikes
        width_put, width_call = ps - pl, cl - cs
        width = max(width_put, width_call)
        credit = extract_condor_credit(entry_price, notes, width)
        if ps < s < cs:  # inside the short strikes: keep full credit
            if credit is None:
                # win is determinate, magnitude is not — never fabricate it
                return Outcome(status="closed", outcome="win", win=1,
                               settlement_price=s, settlement_date=settlement_date,
                               reason="credit unknown; win by range, return not computable")
            return closed(value=credit, cost=0.0, risk=width - credit)
        loss_leg = min(max(ps - s, s - cs), width_put if s <= ps else width_call)
        if credit is not None:
            return closed(value=credit - loss_leg, cost=0.0, risk=width - credit)
        if (s <= pl and width_put == width) or (s >= cl and width_call == width):
            # beyond the max-width wing: return on risk = -(width-c)/(width-c) = -100% for any c
            return Outcome(status="closed", outcome="loss", win=0,
                           realized_return=-1.0,
                           settlement_price=s, settlement_date=settlement_date,
                           reason="credit unknown; full max-width wing breach is -100% of risk")
        return unresolvable("condor credit unknown and settlement between short strike and wing")

    if "spread" in strategy:
        k1, k2 = strikes
        if "put" in strategy or (play.get("direction") or "").lower().startswith("bear"):
            hi, lo = max(k1, k2), min(k1, k2)
            width = hi - lo
            value = min(max(hi - s, 0.0), width)
        else:  # bull call spread
            lo, hi = min(k1, k2), max(k1, k2)
            width = hi - lo
            value = min(max(s - lo, 0.0), width)
        debit = extract_debit(entry_price, notes, width)
        if debit is None:
            return unresolvable(f"invalid debit {entry_price!r} for width {width}")
        return closed(value=value, cost=debit, risk=debit)

    if "straddle" in strategy:
        (k,) = strikes
        cost = extract_debit(entry_price, notes, None)
        if cost is None:
            return unresolvable(f"invalid straddle premium {entry_price!r}")
        return closed(value=abs(s - k), cost=cost, risk=cost)

    if "call" in strategy or "put" in strategy:
        (k,) = strikes
        cost = extract_debit(entry_price, notes, None)
        if cost is None:
            return unresolvable(f"invalid premium {entry_price!r}")
        value = max(k - s, 0.0) if "put" in strategy else max(s - k, 0.0)
        return closed(value=value, cost=cost, risk=cost)

    return unresolvable(f"unknown strategy {play.get('strategy')!r}")


# ── Settlement lookup ─────────────────────────────────────────────────────────

def settlement_for(conn, ticker: str, expiry: str):
    """Latest close in [expiry - SETTLEMENT_REACHBACK_DAYS, expiry].
    Never a post-expiry price. Returns (price, date) or None."""
    start = (datetime.strptime(expiry, "%Y-%m-%d")
             - timedelta(days=SETTLEMENT_REACHBACK_DAYS)).strftime("%Y-%m-%d")
    row = conn.execute("""
        SELECT close_price, date FROM prices
        WHERE ticker = ? AND date BETWEEN ? AND ?
        ORDER BY date DESC LIMIT 1
    """, (ticker, start, expiry)).fetchone()
    return (row[0], row[1]) if row else None


# ── Closure job ───────────────────────────────────────────────────────────────

def _apply(conn, play_id: int, o: Outcome, today: str, close_method: str = CLOSE_METHOD):
    conn.execute("""
        UPDATE options_plays
        SET status = ?, outcome = ?, win = ?, realized_pnl = ?, realized_return = ?,
            settlement_price = ?, settlement_date = ?, closed_at = ?, close_method = ?,
            outcome_price = ?, outcome_date = ?,
            pnl_pct = ?
        WHERE id = ?
    """, (o.status, o.outcome, o.win, o.realized_pnl, o.realized_return,
          o.settlement_price, o.settlement_date, today, close_method,
          o.settlement_price, o.settlement_date or today,
          round(o.realized_return * 100, 2) if o.realized_return is not None else None,
          play_id))


def close_due_plays(conn, today: str = None, dry_run: bool = False) -> dict:
    """Scan open plays strictly past expiry; close, hold, or mark unresolvable.

    Idempotent: only touches status='open' rows, so closed/unresolvable rows
    are never re-processed. Per-play errors are isolated (one bad row cannot
    abort the batch — the legacy job aborted wholesale on any exception).
    """
    today = today or datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT * FROM options_plays
        WHERE status = 'open' AND expiry IS NOT NULL AND expiry != '' AND expiry < ?
        ORDER BY expiry, id
    """, (today,)).fetchall()

    summary = {"due": len(rows), "closed": 0, "unresolvable": 0,
               "pending": 0, "errors": 0, "details": []}
    today_dt = datetime.strptime(today, "%Y-%m-%d")

    for row in rows:
        play = dict(row)
        try:
            settle = settlement_for(conn, play["ticker"], play["expiry"])
            if settle is None:
                days_past = (today_dt - datetime.strptime(play["expiry"], "%Y-%m-%d")).days
                if days_past <= UNRESOLVABLE_GRACE_DAYS:
                    summary["pending"] += 1  # price may still arrive; stays open
                    continue
                o = Outcome(status="unresolvable",
                            reason=f"no price in [{play['expiry']}-{SETTLEMENT_REACHBACK_DAYS}d, "
                                   f"{play['expiry']}] after {days_past}d grace")
            else:
                o = compute_outcome(play, settle[0], settle[1])
            if not dry_run:
                _apply(conn, play["id"], o, today)
            summary[o.status] += 1
            summary["details"].append(
                {"id": play["id"], "ticker": play["ticker"], "strategy": play["strategy"],
                 "expiry": play["expiry"], "status": o.status, "outcome": o.outcome,
                 "realized_return": o.realized_return, "reason": o.reason})
        except Exception as e:
            summary["errors"] += 1
            logger.error(f"Closure error on play {play.get('id')}: {e}")

    if not dry_run:
        conn.commit()
    return summary


def migrate_legacy_closures(conn, today: str = None, dry_run: bool = False) -> dict:
    """One-time supervised migration: recompute rows closed by the legacy
    directional x4 heuristic (close_method IS NULL) under settlement_v2.
    The legacy values are appended to notes for audit. Rows already carrying
    a close_method are never touched (idempotent)."""
    today = today or datetime.now().strftime("%Y-%m-%d")
    rows = conn.execute("""
        SELECT * FROM options_plays
        WHERE status = 'closed' AND close_method IS NULL
        ORDER BY id
    """).fetchall()
    summary = {"candidates": len(rows), "migrated": 0, "unresolvable": 0,
               "errors": 0, "details": []}
    for row in rows:
        play = dict(row)
        try:
            settle = settlement_for(conn, play["ticker"], play["expiry"])
            if settle is None:
                o = Outcome(status="unresolvable",
                            reason="no settlement price in v2 window")
            else:
                o = compute_outcome(play, settle[0], settle[1])
            if not dry_run:
                audit = (f"{play.get('notes') or ''} [legacy close: "
                         f"pnl_pct={play.get('pnl_pct')} "
                         f"outcome_price={play.get('outcome_price')} "
                         f"outcome_date={play.get('outcome_date')}]")
                conn.execute("UPDATE options_plays SET notes = ? WHERE id = ?",
                             (audit, play["id"]))
                _apply(conn, play["id"], o, today,
                       close_method=f"{CLOSE_METHOD}_migrated")
            summary["migrated" if o.status == "closed" else "unresolvable"] += 1
            summary["details"].append(
                {"id": play["id"], "ticker": play["ticker"], "strategy": play["strategy"],
                 "legacy_pnl_pct": play.get("pnl_pct"), "status": o.status,
                 "outcome": o.outcome, "realized_return": o.realized_return,
                 "reason": o.reason})
        except Exception as e:
            summary["errors"] += 1
            logger.error(f"Legacy migration error on play {play.get('id')}: {e}")
    if not dry_run:
        conn.commit()
    return summary


# ── Entry-conviction backfill (contemporaneous scores only — no look-ahead) ──

def conviction_asof(conn, ticker: str, generated_at: str):
    """lt/opt scores from the latest scan at or before the play's entry time."""
    row = conn.execute("""
        SELECT s.lt_score, s.opt_score FROM scores s
        JOIN scans sc ON sc.id = s.scan_id
        WHERE s.ticker = ? AND sc.timestamp <= ?
        ORDER BY sc.timestamp DESC LIMIT 1
    """, (ticker, generated_at)).fetchone()
    if row is None or row[0] is None or row[1] is None:
        return None
    return {"lt_score": row[0], "opt_score": row[1],
            "conviction": round(0.6 * row[1] + 0.4 * row[0], 2)}


def backfill_entry_conviction(conn, dry_run: bool = False) -> dict:
    """Fill entry_conviction for rows missing it. The journal filed
    lt_score=opt_score=0 on every row (log_play read scores from a dict that
    never contained them); as-filed zeros are left in place for audit."""
    rows = conn.execute("""
        SELECT id, ticker, generated_at FROM options_plays
        WHERE entry_conviction IS NULL
    """).fetchall()
    filled = missing = 0
    for pid, ticker, generated_at in rows:
        c = conviction_asof(conn, ticker, generated_at)
        if c is None:
            missing += 1
            continue
        if not dry_run:
            conn.execute("UPDATE options_plays SET entry_conviction = ? WHERE id = ?",
                         (c["conviction"], pid))
        filled += 1
    if not dry_run:
        conn.commit()
    return {"candidates": len(rows), "filled": filled, "no_scores_found": missing}


# ── Gate metrics (definitions pre-registered in FORWARD_TEST_SEMANTICS.md) ───

CONVICTION_BUCKETS = [("<55", 0, 55), ("55-65", 55, 65), ("65-75", 65, 75), (">=75", 75, 10**9)]


def distinct_closed_plays(conn) -> list:
    """One row per (ticker, strategy, strike, expiry): the EARLIEST logged
    instance. Duplicates (pre-warm re-logs each scan) are excluded from
    metrics; 216 journal rows currently collapse to 83 distinct plays."""
    rows = conn.execute("""
        SELECT * FROM options_plays p
        WHERE p.status IN ('closed', 'unresolvable')
          AND p.id = (SELECT MIN(p2.id) FROM options_plays p2
                      WHERE p2.ticker = p.ticker
                        AND COALESCE(p2.strategy,'') = COALESCE(p.strategy,'')
                        AND COALESCE(CAST(p2.strike AS TEXT),'') = COALESCE(CAST(p.strike AS TEXT),'')
                        AND COALESCE(p2.expiry,'') = COALESCE(p.expiry,''))
    """).fetchall()
    return [dict(r) for r in rows]


def gate_metrics(conn) -> dict:
    """Win rate and EV (profit factor) by conviction bucket over distinct
    closed plays. Unresolvable and unknown-magnitude wins are counted
    explicitly, never silently dropped from the denominator."""
    plays = distinct_closed_plays(conn)
    out = {"overall": _bucket_metrics(plays), "buckets": {}}
    for name, lo, hi in CONVICTION_BUCKETS:
        subset = [p for p in plays
                  if p.get("entry_conviction") is not None and lo <= p["entry_conviction"] < hi]
        out["buckets"][name] = _bucket_metrics(subset)
    out["no_conviction"] = _bucket_metrics(
        [p for p in plays if p.get("entry_conviction") is None])
    return out


def _bucket_metrics(plays: list) -> dict:
    decided = [p for p in plays if p["status"] == "closed" and p.get("win") is not None]
    unresolvable = sum(1 for p in plays if p["status"] == "unresolvable")
    wins = [p for p in decided if p["win"] == 1]
    losses = [p for p in decided if p["win"] == 0]
    with_ret = [p for p in decided if p.get("realized_return") is not None]
    gains = sum(p["realized_return"] for p in with_ret if p["realized_return"] > 0)
    pains = abs(sum(p["realized_return"] for p in with_ret if p["realized_return"] < 0))
    return {
        "n_decided": len(decided),
        "n_unresolvable": unresolvable,
        "n_wins": len(wins),
        "n_losses": len(losses),
        "win_rate": round(len(wins) / len(decided), 4) if decided else None,
        "n_with_return": len(with_ret),
        "profit_factor": (round(gains / pains, 4) if pains > 0
                          else (None if not with_ret else float("inf") if gains > 0 else None)),
        "expectancy": (round(sum(p["realized_return"] for p in with_ret) / len(with_ret), 4)
                       if with_ret else None),
    }
