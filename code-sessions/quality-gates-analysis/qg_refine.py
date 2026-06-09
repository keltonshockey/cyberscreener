#!/usr/bin/env python3
"""
qg_refine.py — Phase-1b: (1) re-threshold Tier-A solvency to clear-distress (sane flag
rate); (2) simulate B1 organic Rule-of-40 normalization and measure the high-LT bucket's
forward mean + left tail before/after; (3) build the combined EARNED-gate pipeline and
measure the high-LT bucket both periods vs baseline.
"""
import json, os, math

P = json.load(open(os.path.expanduser("~/mill-local-edits/qg_panel.json")))
recs = P["records"]
SPLIT = "2021-04-01"
W = {"rule_of_40": 25, "valuation": 20, "fcf_margin": 15, "trend": 15, "earnings_quality": 10, "discount_momentum": 15}
by_snap = {}
for r in recs:
    by_snap.setdefault(r["snap"], []).append(r)
snaps = sorted(by_snap)
def period(s): return "A" if s < SPLIT else "B"

def botdecile(xs):
    xs = sorted(xs); k = max(1, len(xs)//10); return sum(xs[:k])/k
def summ(rows, hz="fwd12"):
    v=[r[hz] for r in rows if r.get(hz) is not None]
    if not v: return None
    return dict(n=len(v), mean=sum(v)/len(v), bot10=botdecile(v))

# ---------- 1. clear-distress Tier-A re-thresholding ----------
print("="*70); print("1. TIER-A clear-distress thresholds — flag rate + high-LT left-tail effect")
print("="*70)
def hi_bucket(use_score="lt_score"):
    HI=[]
    for s in snaps:
        rows=sorted(by_snap[s], key=lambda r: r[use_score]); k=max(1,len(rows)//5)
        cut=rows[-k][use_score]
        for r in by_snap[s]:
            if r[use_score]>=cut and r.get("fwd12") is not None:
                HI.append(r)
    return HI
HI = hi_bucket()

def aflag(name, fn, applic=None):
    appl=[r for r in recs if applic is None or applic(r)]
    fr=100*sum(1 for r in appl if fn(r))/max(1,len(appl))
    line=[name, "flag=%.1f%% of applicable (%.0f%% cov)"%(fr,100*len(appl)/len(recs))]
    for per in ["A","B"]:
        hp=[r for r in HI if period(r["snap"])==per and (applic is None or applic(r))]
        un=summ([r for r in hp if not fn(r)]); fl=summ([r for r in hp if fn(r)])
        if un and fl:
            line.append("%s: keep m=%+.1f b10=%+.1f | excl m=%+.1f b10=%+.1f (n=%d) Δb10=%+.1f"%
                        (per,100*un["mean"],100*un["bot10"],100*fl["mean"],100*fl["bot10"],fl["n"],
                         100*(fl["bot10"]-un["bot10"])))
        else:
            line.append("%s: excl n<1"%per)
    print("  "+name); print("    "+line[1])
    for x in line[2:]: print("    "+x)

aflag("A4' Altman-Z < 1.0 (clear distress)", lambda r: r.get("altman_z") is not None and r["altman_z"]<1.0,
      applic=lambda r:r.get("altman_z") is not None)
aflag("A5' interest coverage < 1.0x", lambda r: r.get("interest_coverage") is not None and r["interest_coverage"]<1.0,
      applic=lambda r:r.get("interest_coverage") is not None)
aflag("A6' net-debt/EBITDA > 6 OR negative EBITDA", lambda r: r.get("net_debt_ebitda") is not None and (r["net_debt_ebitda"]>6 or r["net_debt_ebitda"]<0),
      applic=lambda r:r.get("net_debt_ebitda") is not None)
# composite clear-distress: any of Z<1.0, cov<1.0, (price<5 or mktcap<300M or dvol<2M)
def distress(r):
    z = r.get("altman_z"); ic=r.get("interest_coverage")
    return ((z is not None and z<1.0) or (ic is not None and ic<1.0)
            or r["price"]<5 or (r.get("mktcap") is not None and r["mktcap"]<300e6) or r["dollar_vol"]<2e6)
aflag("A* composite hard-exclude (Z<1 | cov<1 | price<5 | cap<300M | dvol<2M)", distress)

# ---------- 2. B1 organic Rule-of-40 normalization simulation ----------
print("\n"+"="*70); print("2. B1 organic normalization — cap M&A Rule-of-40 growth credit, re-rank high-LT")
print("="*70)
def is_ma(r):
    return ((r.get("acq_spend_pct_rev") or 0)>5 or (r.get("goodwill_step_pct_rev") or 0)>10 or (r.get("shares_growth_pct") or 0)>8)
def r40_raw(rg, om, gm):
    margin = om if om not in (None,0) else ((gm or 0)*0.5)
    r40 = (rg or 0)+margin
    if r40>=60: return 1.0
    if r40>=40: return 0.7+0.3*((r40-40)/20)
    if r40>=25: return 0.3+0.4*((r40-25)/15)
    if r40>=0: return 0.1+0.2*(r40/25)
    return 0.0
ORG_CAP = 10.0  # when M&A-flagged, trust at most ~10% growth (median organic) in Rule-of-40
for r in recs:
    rg = r.get("revenue_growth_pct"); om=r.get("op_margin"); gm=r.get("gross_margin")
    base_r40 = r["c_rule_of_40"]
    if is_ma(r) and rg is not None and rg>ORG_CAP:
        new_r40 = round(r40_raw(min(rg,ORG_CAP), om, gm)*W["rule_of_40"],1)
    else:
        new_r40 = base_r40
    r["_lt_norm"] = round(r["lt_score"] - base_r40 + new_r40, 1)

HInorm = hi_bucket("_lt_norm")
for per in ["A","B"]:
    base=summ([r for r in HI if period(r["snap"])==per])
    norm=summ([r for r in HInorm if period(r["snap"])==per])
    # how many M&A names dropped out of high-LT
    base_ma=sum(1 for r in HI if period(r["snap"])==per and is_ma(r))
    norm_ma=sum(1 for r in HInorm if period(r["snap"])==per and is_ma(r))
    print("  %s  baseline high-LT: mean=%+.1f%% bot10=%+.1f%% (M&A names=%d) | normalized: mean=%+.1f%% bot10=%+.1f%% (M&A names=%d)"%
          (per,100*base["mean"],100*base["bot10"],base_ma,100*norm["mean"],100*norm["bot10"],norm_ma))

# OOS quintile spread of composite, baseline vs normalized (full-panel Q5-Q1)
def quintile_spread(score, snap_filter):
    q1,q5=[],[]
    for s in snaps:
        if not snap_filter(s): continue
        rows=[(r[score], r["fwd12"]) for r in by_snap[s] if r.get("fwd12") is not None]
        if len(rows)<30: continue
        rows.sort(key=lambda x:x[0]); k=len(rows)//5
        q1+=[r for _,r in rows[:k]]; q5+=[r for _,r in rows[-k:]]
    return (sum(q5)/len(q5)-sum(q1)/len(q1)) if q1 and q5 else None
for per,filt in [("A",lambda s:period(s)=="A"),("B/OOS",lambda s:period(s)=="B")]:
    b=quintile_spread("lt_score",filt); n=quintile_spread("_lt_norm",filt)
    print("  %s Q5-Q1 composite: baseline=%+.2f%%  normalized=%+.2f%%"%(per,100*b,100*n))

# ---------- 3. combined EARNED-gate pipeline on high-LT bucket ----------
print("\n"+"="*70); print("3. EARNED-gate pipeline — high-LT bucket fwd12 mean + bot10, baseline vs gated")
print("="*70)
def secular(r):
    return (r.get("rev_cagr_3y") is not None and r["rev_cagr_3y"]<2
            and r.get("op_margin_delta_3y") is not None and r["op_margin_delta_3y"]<0)
# pipeline: stage1 exclude hard-distress; stage2 conviction down-weight = drop secular-decline from High;
# use normalized score for ranking.
HInorm_set = set(id(r) for r in HInorm)
for per in ["A","B"]:
    base=summ([r for r in HI if period(r["snap"])==per])
    # gated High = normalized-ranked high-LT, minus hard-distress, minus secular-decline
    gated=[r for r in HInorm if period(r["snap"])==per and not distress(r) and not secular(r)]
    g=summ(gated)
    print("  %s baseline High n=%d mean=%+.1f%% bot10=%+.1f%%  ->  gated High n=%d mean=%+.1f%% bot10=%+.1f%%  (Δmean=%+.1f Δbot10=%+.1f)"%
          (per,base["n"],100*base["mean"],100*base["bot10"],g["n"],100*g["mean"],100*g["bot10"],
           100*(g["mean"]-base["mean"]),100*(g["bot10"]-base["bot10"])))
