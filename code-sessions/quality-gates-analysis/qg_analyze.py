#!/usr/bin/env python3
"""
qg_analyze.py — Phase-1 validation of candidate quality gates on the enriched PIT panel.

For each gate, within the HIGH-LT bucket (top quintile of lt_score per snapshot),
report flag rate and the forward-return / left-tail difference between flagged and
unflagged names, in BOTH sub-periods independently (split 2021-04-01, the RESULT §7.3
regime/OOS boundary). Tier-B modifiers additionally test whether capping the flagged
names improves the realized High slice. Organic-normalization additionally measures
Rule-of-40 IC on the M&A cohort vs the organic cohort.

No restated fundamentals. Survivorship caveat (46 delisted excluded) reported.
"""
import json, os, math, statistics as st

P = json.load(open(os.path.expanduser("~/mill-local-edits/qg_panel.json")))
recs = P["records"]
SPLIT = "2021-04-01"
by_snap = {}
for r in recs:
    by_snap.setdefault(r["snap"], []).append(r)
snaps = sorted(by_snap)

def period(s):
    return "A(2014-21)" if s < SPLIT else "B(2021-25)"

# tag high-LT membership per snapshot (top quintile by lt_score)
for s in snaps:
    rows = sorted(by_snap[s], key=lambda r: r["lt_score"])
    n = len(rows); k = max(1, n // 5)
    cutoff = rows[-k]["lt_score"]
    for r in by_snap[s]:
        r["_hiLT"] = r["lt_score"] >= cutoff
        r["_period"] = period(s)

HI = [r for r in recs if r["_hiLT"] and r.get("fwd12") is not None]

def botdecile(xs):
    if not xs: return None
    xs = sorted(xs); k = max(1, len(xs)//10)
    return sum(xs[:k]) / k

def stats(rows, hz="fwd12"):
    v = [r[hz] for r in rows if r.get(hz) is not None]
    if not v: return None
    return dict(n=len(v), mean=sum(v)/len(v), bot10=botdecile(v),
                ndead=sum(1 for x in v if x <= -0.50))

def gate_report(name, flagfn, applic=None, tier="A"):
    print("\n=== [%s] %s ===" % (tier, name))
    # universe-wide + high-LT applicability/flag rates
    appl = [r for r in recs if (applic is None or applic(r))]
    flagged_all = [r for r in appl if flagfn(r)]
    print("  universe: applicable=%d (%.0f%%)  flagged=%d (%.1f%% of applicable, %.1f%% of all)" %
          (len(appl), 100*len(appl)/len(recs), len(flagged_all),
           100*len(flagged_all)/max(1,len(appl)), 100*len(flagged_all)/len(recs)))
    print("  within HIGH-LT bucket, fwd12 mean / bottom-decile / dead(<=-50%%) rate, by sub-period:")
    print("  %-12s | %-26s | %-26s | flag%%" % ("period", "UNFLAGGED (keep)", "FLAGGED (gate hits)"))
    earned = {}
    for per in ["A(2014-21)", "B(2021-25)"]:
        hp = [r for r in HI if r["_period"] == per and (applic is None or applic(r))]
        un = [r for r in hp if not flagfn(r)]
        fl = [r for r in hp if flagfn(r)]
        su, sf = stats(un), stats(fl)
        fr = 100*len(fl)/max(1,len(hp))
        def fmt(s):
            return "n=%-4d m=%+6.1f%% b10=%+6.1f%%" % (s["n"], 100*s["mean"], 100*s["bot10"]) if s else "n=0"
        print("  %-12s | %-26s | %-26s | %4.1f" % (per, fmt(su), fmt(sf), fr))
        if su and sf:
            earned[per] = dict(dmean=sf["mean"]-su["mean"], dbot=sf["bot10"]-su["bot10"],
                               deadf=sf["ndead"]/sf["n"], deadu=su["ndead"]/su["n"])
    # verdict: flagged worse (neg dmean AND/OR neg dbot) in BOTH periods
    if len(earned) == 2:
        worse_mean = all(earned[p]["dmean"] < 0 for p in earned)
        worse_tail = all(earned[p]["dbot"] < 0 for p in earned)
        verdict = "EARNS (flagged worse both periods)" if (worse_mean or worse_tail) else "no edge (not worse both periods)"
        print("  -> Δmean A=%+.1f%% B=%+.1f%% ; Δbot10 A=%+.1f%% B=%+.1f%% -> %s" %
              (100*earned["A(2014-21)"]["dmean"], 100*earned["B(2021-25)"]["dmean"],
               100*earned["A(2014-21)"]["dbot"], 100*earned["B(2021-25)"]["dbot"], verdict))
    return earned

# ---------------- TIER A — hard-exclude (hygiene/solvency) ----------------
print("#" * 70)
print("# TIER A — hard-exclude candidates (within high-LT bucket)")
print("#" * 70)
gate_report("A1 price floor < $5", lambda r: r["price"] < 5)
gate_report("A2 market-cap floor < $300M", lambda r: r.get("mktcap") is not None and r["mktcap"] < 300e6,
            applic=lambda r: r.get("mktcap") is not None)
gate_report("A3 dollar-volume floor < $2M/day", lambda r: r["dollar_vol"] < 2e6)
gate_report("A4 Altman-Z < 1.8 (distress)", lambda r: r.get("altman_z") is not None and r["altman_z"] < 1.8,
            applic=lambda r: r.get("altman_z") is not None)
gate_report("A5 interest coverage < 1.5x", lambda r: r.get("interest_coverage") is not None and r["interest_coverage"] < 1.5,
            applic=lambda r: r.get("interest_coverage") is not None)
gate_report("A6 net-debt/EBITDA > 5 (or neg EBITDA)",
            lambda r: r.get("net_debt_ebitda") is not None and (r["net_debt_ebitda"] > 5 or r["net_debt_ebitda"] < 0),
            applic=lambda r: r.get("net_debt_ebitda") is not None)
gate_report("A7 accumulated deficit (retained earnings < 0)",
            lambda r: r.get("retained_earnings") is not None and r["retained_earnings"] < 0,
            applic=lambda r: r.get("retained_earnings") is not None)

# ---------------- TIER B — conviction modifiers ----------------
print("\n" + "#" * 70)
print("# TIER B — conviction modifiers (within high-LT bucket)")
print("#" * 70)
gate_report("B2 interest corroboration: perf_1y <= 0 (no positive-trend corrob.)",
            lambda r: r["perf_1y"] <= 0, tier="B")
gate_report("B3 secular decline: rev_cagr_3y<2%% AND op_margin eroding",
            lambda r: (r.get("rev_cagr_3y") is not None and r["rev_cagr_3y"] < 2
                       and r.get("op_margin_delta_3y") is not None and r["op_margin_delta_3y"] < 0),
            applic=lambda r: r.get("rev_cagr_3y") is not None and r.get("op_margin_delta_3y") is not None,
            tier="B")
gate_report("B1 M&A inorganic flag (acq>5%%rev OR goodwill-step>10%%rev OR shares+8%%)",
            lambda r: ((r.get("acq_spend_pct_rev") or 0) > 5 or (r.get("goodwill_step_pct_rev") or 0) > 10
                       or (r.get("shares_growth_pct") or 0) > 8),
            tier="B")

# ---------------- B1 deep-dive: is gaudy Rule-of-40 NOISE on M&A names? ----------------
print("\n" + "#" * 70)
print("# B1 ORGANIC-NORMALIZATION EVIDENCE — Rule-of-40 IC: M&A cohort vs organic cohort")
print("#" * 70)
def rank(xs):
    order=sorted(range(len(xs)),key=lambda i:xs[i]); rr=[0.0]*len(xs); i=0
    while i<len(xs):
        j=i
        while j+1<len(xs) and xs[order[j+1]]==xs[order[i]]: j+=1
        avg=(i+j)/2.0+1
        for k in range(i,j+1): rr[order[k]]=avg
        i=j+1
    return rr
def pear(a,b):
    n=len(a); ma=sum(a)/n; mb=sum(b)/n
    num=sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    da=math.sqrt(sum((x-ma)**2 for x in a)); db=math.sqrt(sum((x-mb)**2 for x in b))
    return num/(da*db) if da>0 and db>0 else 0.0
def spear(a,b):
    return pear(rank(a),rank(b)) if len(a)>=8 else None

def is_ma(r):
    return ((r.get("acq_spend_pct_rev") or 0) > 5 or (r.get("goodwill_step_pct_rev") or 0) > 10
            or (r.get("shares_growth_pct") or 0) > 8)

# pooled cross-sectional IC of rule_of_40 component vs fwd12, M&A vs organic, both periods.
for per in ["A(2014-21)", "B(2021-25)"]:
    for label, cohort in [("M&A names", lambda r: is_ma(r)), ("organic names", lambda r: not is_ma(r))]:
        ics=[]
        for s in snaps:
            if period(s) != per: continue
            rows=[r for r in by_snap[s] if cohort(r) and r.get("fwd12") is not None
                  and r.get("acq_spend_pct_rev") is not None]  # require M&A-measurable to keep cohorts comparable
            if len(rows)>=8:
                ic=spear([x["c_rule_of_40"] for x in rows],[x["fwd12"] for x in rows])
                if ic is not None: ics.append(ic)
        if ics:
            print("  %-12s %-14s rule_of_40 IC@12 = %+.4f  (snaps=%d)" % (per, label, sum(ics)/len(ics), len(ics)))
print("  (if R40 IC ~0/neg on M&A but + on organic, the gaudy M&A R40 is noise -> normalization justified)")

# ---------------- B2 deep-dive: does capping no-corroboration improve the High slice? ----------------
print("\n" + "#" * 70)
print("# B2 CONVICTION-CAP EVIDENCE — High slice with vs without corroboration cap")
print("#" * 70)
for per in ["A(2014-21)", "B(2021-25)"]:
    hp=[r for r in HI if r["_period"]==per]
    base=stats(hp)
    capped=stats([r for r in hp if r["perf_1y"]>0])   # keep only corroborated as 'High'
    print("  %-12s High(all top-q): n=%d mean=%+.1f%% bot10=%+.1f%% | High(corroborated only): n=%d mean=%+.1f%% bot10=%+.1f%%" %
          (per, base["n"],100*base["mean"],100*base["bot10"],
           capped["n"],100*capped["mean"],100*capped["bot10"]))

print("\nNOTE: panel excludes 46 delisted names (no yfinance prices) -> Tier-A delisting/left-tail")
print("benefit is UNDERSTATED here (worst real outcomes are already absent). dead(<=-50%) is a survivor proxy.")
