#!/usr/bin/env python3
"""Coverage + faithfulness sanity check on the enriched panel."""
import json, os, math, datetime as dt

P = json.load(open(os.path.expanduser("~/mill-local-edits/qg_panel.json")))
recs = P["records"]; meta = P["meta"]
print("records=%d names=%d delisted_no_price=%d" % (meta["n_records"], meta["n_names"], meta["n_delisted_no_price"]))

def cov(field):
    n = sum(1 for r in recs if r.get(field) is not None)
    return "%5.1f%%" % (100 * n / len(recs))

for f in ["lt_score","ev_revenue","revenue_growth_pct","mktcap","dollar_vol","perf_1y",
          "altman_z","interest_coverage","net_debt_ebitda","retained_earnings",
          "acq_spend_pct_rev","goodwill_step_pct_rev","shares_growth_pct",
          "rev_cagr_3y","op_margin_delta_3y","fwd6","fwd12"]:
    print("  %-22s %s" % (f, cov(f)))

# --- faithfulness: cross-sectional Spearman IC of valuation vs fwd12, both halves ---
snaps = sorted(set(r["snap"] for r in recs))
mid = snaps[len(snaps)//2]
by_snap = {}
for r in recs:
    by_snap.setdefault(r["snap"], []).append(r)

def rank(xs):
    order = sorted(range(len(xs)), key=lambda i: xs[i]); rr=[0.0]*len(xs); i=0
    while i < len(xs):
        j=i
        while j+1<len(xs) and xs[order[j+1]]==xs[order[i]]: j+=1
        avg=(i+j)/2.0+1
        for k in range(i,j+1): rr[order[k]]=avg
        i=j+1
    return rr
def pearson(a,b):
    n=len(a); ma=sum(a)/n; mb=sum(b)/n
    num=sum((a[i]-ma)*(b[i]-mb) for i in range(n))
    da=math.sqrt(sum((x-ma)**2 for x in a)); db=math.sqrt(sum((x-mb)**2 for x in b))
    return num/(da*db) if da>0 and db>0 else 0.0
def spear(a,b):
    if len(a)<3: return None
    return pearson(rank(a),rank(b))

def ic(field, hz="fwd12", half=None):
    out=[]
    for s in snaps:
        if half=="1" and s>mid: continue
        if half=="2" and s<=mid: continue
        rows=[(r["c_"+field] if field!="lt_score" else r["lt_score"], r[hz]) for r in by_snap[s] if r.get(hz) is not None]
        if len(rows)>=30:
            out.append(spear([x[0] for x in rows],[x[1] for x in rows]))
    out=[x for x in out if x is not None]
    return sum(out)/len(out) if out else None

for field in ["valuation","rule_of_40","lt_score"]:
    print("IC@12 %-12s full=%+.4f  h1=%+.4f  h2=%+.4f" %
          (field, ic(field), ic(field,half="1"), ic(field,half="2")))
print("(expect: valuation +, sign-consistent; rule_of_40 flips; matches RESULT §7.2)")
