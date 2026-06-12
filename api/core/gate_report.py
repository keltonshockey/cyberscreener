"""
Forward-test gate report (SESSION-GATE-PREREG).

Computes the pre-registered gate table (GATE_PREREG.md, repo root): distinct
closed plays per cohort per conviction bucket, win rate with Wilson 95% CI,
avg win/loss, payoff ratio, profit factor, expectancy — plus the mechanical
pass-bar and fail-rule evaluations. Cohorts are DERIVED from immutable entry
fields (generated_at, score_version); no journal row is ever written.

Read-only by construction: the CLI opens the DB via a `mode=ro` URI, so the
weekly automation physically cannot mutate the journal.

CLI (weekly, Sundays — see scripts/mill/):
    python -m core.gate_report --db /path/to/cyberscreener.db --out DIR [--pushover]
"""
import argparse
import json
import math
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from datetime import date

from core.play_closure import distinct_closed_plays

# Pre-registered cohort boundary (GATE_PREREG.md §1): PR #6 service restart.
COHORT_B_START = "2026-06-09 04:00:00"
BASELINE_SCORE_VERSION = "v2-baseline"

# Pre-registered buckets (GATE_PREREG.md §2). '<65' is context, never gates.
BUCKETS = [("<65", 0, 65), ("65-75", 65, 75), ("75-85", 75, 85), ("85+", 85, 10**9)]
GATE_AGG = ">=65"

# Pre-registered bars (GATE_PREREG.md §3-4).
PASS_WIN_RATE = 0.55
PASS_PAYOFF = 1.5
POWERED_N = 384
FAIL_WIN_RATE = 0.50
FAIL_MIN_N = 80


def cohort_of(play: dict) -> str:
    """A/B/C per GATE_PREREG.md §1 — deterministic, from entry fields only."""
    if play.get("score_version") == BASELINE_SCORE_VERSION:
        return "C"
    if (play.get("generated_at") or "") >= COHORT_B_START:
        return "B"
    return "A"


def wilson_ci(wins: int, n: int, z: float = 1.96):
    """Wilson score 95% interval for a binomial proportion."""
    if n == 0:
        return None
    p = wins / n
    denom = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (round(max(0.0, center - half), 4), round(min(1.0, center + half), 4))


def _metrics(plays: list) -> dict:
    decided = [p for p in plays if p["status"] == "closed" and p.get("win") is not None]
    unresolvable = sum(1 for p in plays if p["status"] == "unresolvable")
    wins = [p for p in decided if p["win"] == 1]
    losses = [p for p in decided if p["win"] == 0]
    win_rets = [p["realized_return"] for p in wins if p.get("realized_return") is not None]
    loss_rets = [p["realized_return"] for p in losses if p.get("realized_return") is not None]
    with_ret = win_rets + loss_rets

    n = len(decided)
    win_rate = round(len(wins) / n, 4) if n else None
    avg_win = round(sum(win_rets) / len(win_rets), 4) if win_rets else None
    avg_loss = round(sum(loss_rets) / len(loss_rets), 4) if loss_rets else None
    payoff = (round(avg_win / abs(avg_loss), 4)
              if avg_win is not None and avg_loss not in (None, 0) else None)
    gains = sum(r for r in with_ret if r > 0)
    pains = abs(sum(r for r in with_ret if r < 0))
    return {
        "n_decided": n,
        "n_unresolvable": unresolvable,
        "n_wins": len(wins),
        "n_losses": len(losses),
        "win_rate": win_rate,
        "wilson_95ci": wilson_ci(len(wins), n),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff,
        "profit_factor": (round(gains / pains, 4) if pains > 0
                          else (None if not with_ret else
                                float("inf") if gains > 0 else None)),
        "expectancy": (round(sum(with_ret) / len(with_ret), 4) if with_ret else None),
        "powered": n >= POWERED_N,
        "significance": ("POWERED" if n >= POWERED_N
                         else "DIRECTIONAL, NOT SIGNIFICANT"),
    }


def gate_table(conn) -> dict:
    """{cohort: {bucket: metrics}} over distinct closed plays. Never pooled
    across cohorts (GATE_PREREG.md §1)."""
    plays = distinct_closed_plays(conn)
    by_cohort = {"A": [], "B": [], "C": []}
    for p in plays:
        by_cohort[cohort_of(p)].append(p)

    table = {}
    for cohort, members in by_cohort.items():
        rows = {}
        for name, lo, hi in BUCKETS:
            rows[name] = _metrics([
                p for p in members
                if p.get("entry_conviction") is not None
                and lo <= p["entry_conviction"] < hi])
        rows[GATE_AGG] = _metrics([
            p for p in members
            if p.get("entry_conviction") is not None and p["entry_conviction"] >= 65])
        rows["no_conviction"] = _metrics(
            [p for p in members if p.get("entry_conviction") is None])
        table[cohort] = rows
    return table


def evaluate(table: dict) -> dict:
    """Mechanical pass-bar + fail-rule evaluation on cohort C's gate
    aggregate (GATE_PREREG.md §3-4). No judgment calls in code."""
    gate = table["C"][GATE_AGG]
    n, wr, payoff = gate["n_decided"], gate["win_rate"], gate["payoff_ratio"]
    passes = (wr is not None and wr >= PASS_WIN_RATE
              and payoff is not None and payoff >= PASS_PAYOFF
              and n >= POWERED_N)
    fail_triggered = (n >= FAIL_MIN_N and wr is not None and wr < FAIL_WIN_RATE)
    return {
        "cohort_c_gate_n": n,
        "cohort_c_win_rate": wr,
        "cohort_c_payoff_ratio": payoff,
        "pass_bar_met": passes,
        "fail_rule_triggered": fail_triggered,
        "verdict": ("PASS BAR MET (powered)" if passes
                    else "FAIL RULE TRIGGERED: stop new feature work, re-architect signals"
                    if fail_triggered
                    else f"NO VERDICT - cohort C n={n} "
                         f"(pass needs n>={POWERED_N}; fail rule arms at n>={FAIL_MIN_N})"),
    }


def _fmt(v):
    if v is None:
        return "-"
    if isinstance(v, float):
        if math.isinf(v):
            return "inf"
        return f"{v:.3f}"
    if isinstance(v, tuple):
        return f"[{v[0]:.3f}, {v[1]:.3f}]"
    return str(v)


def render_markdown(table: dict, evaluation: dict, db_path: str, as_of: str) -> str:
    cohort_blurb = {
        "A": "legacy IV + legacy directional (entered before 2026-06-09 04:00 UTC) - context only",
        "B": "fixed IV/directional, legacy weights - context only",
        "C": "baseline weights (score_version v2-baseline) - THE GATING COHORT",
    }
    lines = [
        f"# Gate read - {as_of}",
        "",
        f"Pre-registered definitions: GATE_PREREG.md (committed 2026-06-11). "
        f"DB: {db_path} (opened read-only). Cohorts are never pooled.",
        "",
    ]
    cols = ["n_decided", "n_unresolvable", "win_rate", "wilson_95ci",
            "avg_win", "avg_loss", "payoff_ratio", "profit_factor",
            "expectancy", "significance"]
    for cohort in ("C", "B", "A"):
        lines.append(f"## Cohort {cohort} - {cohort_blurb[cohort]}")
        lines.append("")
        lines.append("| bucket | " + " | ".join(cols) + " |")
        lines.append("|" + "---|" * (len(cols) + 1))
        for bucket in ("<65", "65-75", "75-85", "85+", GATE_AGG, "no_conviction"):
            m = table[cohort][bucket]
            lines.append("| " + bucket + " | "
                         + " | ".join(_fmt(m[c]) for c in cols) + " |")
        lines.append("")
    lines += [
        "## Rule evaluation (cohort C, conviction >= 65)",
        "",
        f"- n_decided: {evaluation['cohort_c_gate_n']}",
        f"- win_rate: {_fmt(evaluation['cohort_c_win_rate'])}",
        f"- payoff_ratio: {_fmt(evaluation['cohort_c_payoff_ratio'])}",
        f"- pass bar (win>= {PASS_WIN_RATE}, payoff>= {PASS_PAYOFF}, n>= {POWERED_N}): "
        f"{'MET' if evaluation['pass_bar_met'] else 'not met'}",
        f"- fail rule (win< {FAIL_WIN_RATE} at n>= {FAIL_MIN_N}): "
        f"{'TRIGGERED' if evaluation['fail_rule_triggered'] else 'not triggered'}",
        "",
        f"**{evaluation['verdict']}**",
        "",
    ]
    return "\n".join(lines)


def summary_line(table: dict, evaluation: dict, as_of: str) -> str:
    """One Pushover-sized line. Prefers cohort C; falls back to B while C is
    empty (clearly labeled)."""
    c = table["C"][GATE_AGG]
    if c["n_decided"] > 0:
        m, label = c, "C"
    elif table["B"][GATE_AGG]["n_decided"] > 0:
        m, label = table["B"][GATE_AGG], "B (context - no C plays yet)"
    else:
        m, label = table["A"][GATE_AGG], "A (context - no B/C plays yet)"
    wr = _fmt(m["win_rate"])
    return (f"Gate {as_of} cohort {label}: n={m['n_decided']} win={wr} "
            f"payoff={_fmt(m['payoff_ratio'])} [{m['significance']}] - "
            f"{evaluation['verdict']}")


def open_ro(db_path: str) -> sqlite3.Connection:
    """Read-only connection — the report physically cannot write the journal."""
    uri = f"file:{urllib.parse.quote(os.path.abspath(db_path))}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    return conn


def send_pushover(message: str) -> bool:
    """Send via env-provided keys (vault-backed; never inline). No keys = skip."""
    token = os.environ.get("PUSHOVER_TOKEN")
    user = os.environ.get("PUSHOVER_USER")
    if not token or not user:
        print("pushover: PUSHOVER_TOKEN/PUSHOVER_USER not set - skipped", file=sys.stderr)
        return False
    data = urllib.parse.urlencode(
        {"token": token, "user": user, "message": message}).encode()
    req = urllib.request.Request("https://api.pushover.net/1/messages.json", data=data)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.status == 200


def main(argv=None):
    ap = argparse.ArgumentParser(description="Pre-registered forward-test gate read")
    ap.add_argument("--db", required=True, help="path to cyberscreener.db (opened read-only)")
    ap.add_argument("--out", help="directory for GATE_READ_<date>.md (default: stdout only)")
    ap.add_argument("--pushover", action="store_true", help="send the summary line via Pushover")
    ap.add_argument("--json", action="store_true", help="also print the raw table as JSON")
    args = ap.parse_args(argv)

    as_of = str(date.today())
    conn = open_ro(args.db)
    try:
        table = gate_table(conn)
    finally:
        conn.close()
    evaluation = evaluate(table)
    md = render_markdown(table, evaluation, args.db, as_of)

    if args.out:
        os.makedirs(args.out, exist_ok=True)
        out_path = os.path.join(args.out, f"GATE_READ_{as_of}.md")
        with open(out_path, "w") as f:
            f.write(md)
        print(f"wrote {out_path}")
    else:
        print(md)

    line = summary_line(table, evaluation, as_of)
    print(line)
    if args.json:
        print(json.dumps({"table": table, "evaluation": evaluation}, default=str))
    if args.pushover:
        send_pushover(line)


if __name__ == "__main__":
    main()
