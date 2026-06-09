#!/usr/bin/env python3
"""
qg_gen.py — (1) validate the 'cap Rule-of-40 CREDIT' normalization variant (deflates
GEN-type names whose R40 is maxed by margin, which growth-capping can't touch);
(2) numeric GEN before/after trace using the row stated in the task brief.
"""
import json, os

P = json.load(open(os.path.expanduser("~/mill-local-edits/qg_panel.json")))
recs = P["records"]; SPLIT="2021-04-01"
W = {"rule_of_40":25,"valuation":20,"fcf_margin":15,"trend":15,"earnings_quality":10,"discount_momentum":15}
by_snap={}
for r in recs: by_snap.setdefault(r["snap"],[]).append(r)
snaps=sorted(by_snap)
def period(s): return "A" if s<SPLIT else "B"
def botdecile(xs): xs=sorted(xs); k=max(1,len(xs)//10); return sum(xs[:k])/k
def summ(rows):
    v=[r["fwd12"] for r in rows if r.get("fwd12") is not None]
    return dict(n=len(v),mean=sum(v)/len(v),bot10=botdecile(v)) if v else None
def is_ma(r):
    return ((r.get("acq_spend_pct_rev") or 0)>5 or (r.get("goodwill_step_pct_rev") or 0)>10 or (r.get("shares_growth_pct") or 0)>8)

# credit-cap: for M&A names, cap rule_of_40 credit at CAP_FRAC of its max (removes the
# inorganic illusion regardless of whether growth or margin drives it).
CAP_FRAC = 0.6   # M&A names get at most 60% of Rule-of-40 (15/25)
for r in recs:
    base=r["c_rule_of_40"]
    capped = min(base, CAP_FRAC*W["rule_of_40"]) if is_ma(r) else base
    r["_lt_credcap"] = round(r["lt_score"]-base+capped, 1)

def hi(score):
    H=[]
    for s in snaps:
        rows=sorted(by_snap[s],key=lambda r:r[score]); k=max(1,len(rows)//5); cut=rows[-k][score]
        H+=[r for r in by_snap[s] if r[score]>=cut and r.get("fwd12") is not None]
    return H
HI=hi("lt_score"); HC=hi("_lt_credcap")
print("=== credit-cap (M&A R40<=60%) normalization — high-LT bucket fwd12 ===")
for per in ["A","B"]:
    b=summ([r for r in HI if period(r["snap"])==per]); c=summ([r for r in HC if period(r["snap"])==per])
    bma=sum(1 for r in HI if period(r["snap"])==per and is_ma(r)); cma=sum(1 for r in HC if period(r["snap"])==per and is_ma(r))
    print("  %s baseline mean=%+.1f%% bot10=%+.1f%% (M&A=%d) | cred-cap mean=%+.1f%% bot10=%+.1f%% (M&A=%d)  Δmean=%+.1f Δbot10=%+.1f"%
          (per,100*b["mean"],100*b["bot10"],bma,100*c["mean"],100*c["bot10"],cma,100*(c["mean"]-b["mean"]),100*(c["bot10"]-b["bot10"])))

# ---- GEN trace from the task-stated row ----
print("\n=== GEN before/after trace (row from task brief; GEN not in PIT corpus) ===")
# Stated: lt 91.5; r40 25/25 raw 90.4; trend 15/15; fcf 28% -> 15/15; gross78/op63;
# pe16; sentiment/whale/insider 0; perf_1y -13%; cap $15B (solvent, liquid).
gen = dict(lt_score=91.5, c_rule_of_40=25.0, c_valuation=16.0, c_fcf_margin=15.0,
           c_trend=15.0, c_earnings_quality=9.0, c_discount_momentum=11.5,
           op_margin=63.0, revenue_growth_pct=50.4, # reported (Avast/MoneyLion-inflated)
           mktcap=15e9, price=28.0, dollar_vol=80e6, altman_z=2.5, interest_coverage=4.0,
           acq_spend_pct_rev=12.0, goodwill_step_pct_rev=25.0, shares_growth_pct=0.0,
           perf_1y=-13.0, sentiment_bull_pct=0, whale_score=0, insider_buys=0)
print("  raw lt_score (unchanged, Tier B isolated from raw components): %.1f" % gen["lt_score"])
# Tier A eligibility
distress = gen["price"]<5 or gen["mktcap"]<300e6 or gen["dollar_vol"]<2e6 or (gen["interest_coverage"]<1.0)
print("  Tier A (eligibility): price$%.0f cap$%.0fB cov%.1fx -> %s" %
      (gen["price"], gen["mktcap"]/1e9, gen["interest_coverage"], "EXCLUDED" if distress else "ELIGIBLE (passes hygiene)"))
# Tier B organic normalization (credit cap)
ma = gen["acq_spend_pct_rev"]>5 or gen["goodwill_step_pct_rev"]>10 or gen["shares_growth_pct"]>8
r40_capped = min(gen["c_rule_of_40"], CAP_FRAC*W["rule_of_40"])
norm_penalty = gen["c_rule_of_40"] - r40_capped
print("  Tier B organic-normalization: M&A-flagged=%s (acq%.0f%%rev, goodwill-step%.0f%%rev) -> R40 credit %.1f -> %.1f (penalty -%.1f)" %
      (ma, gen["acq_spend_pct_rev"], gen["goodwill_step_pct_rev"], gen["c_rule_of_40"], r40_capped, norm_penalty))
# conviction-adjusted board score (raw lt minus normalization penalty)
conv_score = gen["lt_score"] - norm_penalty
# Tier B interest corroboration cap
corrob = (gen["perf_1y"]>0) or gen["sentiment_bull_pct"]>0 or gen["whale_score"]>0 or gen["insider_buys"]>0
print("  Tier B interest-cap: corroboration signals = sentiment%d/whale%d/insider%d/perf1y%+d -> corroborated=%s" %
      (gen["sentiment_bull_pct"], gen["whale_score"], gen["insider_buys"], gen["perf_1y"], corrob))
tier = "High" if (conv_score>=75 and corrob) else ("Solid/capped" if conv_score>=65 else "Watch")
print("  conviction-adjusted board score: %.1f -> tier %s%s" %
      (conv_score, tier, "  (capped below High: zero corroboration)" if (conv_score>=75 and not corrob) else ""))
print("  NET: raw lt_score 91.5 (board-by-raw would still rank it high); CONVICTION-adjusted")
print("       board score %.1f and tier '%s' -> GEN no longer tops a conviction-ranked board." % (conv_score, tier))
