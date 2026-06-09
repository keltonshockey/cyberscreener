#!/usr/bin/env python3
"""
qg_panel.py — enriched PIT panel for the quality-gate study.

Reuses the EXACT PIT discipline + score_long_term port from lt_reconstruct.py
(annual as-filed, filed<=D), and additionally records, per (ticker, snapshot D),
every input the candidate quality gates need:
  Tier A (hygiene/solvency): price, mktcap, 20d median dollar-volume, Altman-Z,
    interest coverage, net-debt/EBITDA, retained-earnings deficit.
  Tier B (conviction modifiers): M&A acquisition spend + goodwill step (organic
    normalization), multi-year organic revenue/margin trend (secular decline),
    perf_1y (interest-corroboration proxy).
Caches a flat list of records to ~/mill-local-edits/qg_panel.json so the analysis
step is fast and re-runnable. Faithful to the engine; no restated fundamentals.
"""
import json, os, math, datetime as dt, bisect, glob

ROOT = os.path.expanduser("~/lt-recon-data")
EDGAR = os.path.join(ROOT, "edgar")
PRICES = os.path.join(ROOT, "prices")
OUT = os.path.expanduser("~/mill-local-edits/qg_panel.json")
W = {"rule_of_40": 25, "valuation": 20, "fcf_margin": 15, "trend": 15, "earnings_quality": 10, "discount_momentum": 15}

def sc(raw, w):
    return round(max(0, min(1, raw)) * w, 1)

# ---- concept lists (engine + extensions) ----
REV = ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"]
OPINC = ["OperatingIncomeLoss"]
GROSS = ["GrossProfit"]
OCF = ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"]
CAPEX = ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"]
EPS = ["EarningsPerShareDiluted", "EarningsPerShareBasic"]
SHARES = ["EntityCommonStockSharesOutstanding"]            # dei
DEBT_LT = ["LongTermDebtNoncurrent", "LongTermDebt"]
DEBT_CUR = ["LongTermDebtCurrent", "DebtCurrent"]
CASH = ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"]
# extensions
ACQ = ["PaymentsToAcquireBusinessesNetOfCashAcquired", "PaymentsToAcquireBusinessesAndInterestInAffiliates",
       "PaymentsToAcquireBusinessesGross"]
GOODWILL = ["Goodwill"]
ASSETS = ["Assets"]
LIAB = ["Liabilities"]
ASSETS_CUR = ["AssetsCurrent"]
LIAB_CUR = ["LiabilitiesCurrent"]
RETEARN = ["RetainedEarningsAccumulatedDeficit"]
EQUITY = ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"]
INTEXP = ["InterestExpense", "InterestExpenseNonoperating", "InterestAndDebtExpense"]
DA = ["DepreciationDepletionAndAmortization", "DepreciationAmortizationAndAccretionNet",
      "DepreciationAndAmortization"]

def _d(s):
    return dt.date.fromisoformat(s[:10])

def annual_facts(g, concepts):
    for c in concepts:
        node = g.get(c)
        if not node:
            continue
        out = []
        for unit, arr in node.get("units", {}).items():
            for f in arr:
                if not (f.get("start") and f.get("end") and "filed" in f):
                    continue
                form = f.get("form", "")
                dur = (_d(f["end"]) - _d(f["start"])).days
                if f.get("fp") == "FY" and form.startswith("10-K") and dur > 300:
                    out.append((_d(f["end"]), _d(f["filed"]), f["val"]))
        if out:
            return out
    return []

def instant_facts(g, concepts):
    for c in concepts:
        node = g.get(c)
        if not node:
            continue
        out = []
        for unit, arr in node.get("units", {}).items():
            for f in arr:
                if f.get("end") and "filed" in f and "start" not in f:
                    out.append((_d(f["end"]), _d(f["filed"]), f["val"]))
        if out:
            return out
    return []

def as_of_annual(facts, D):
    cand = [(e, fl, v) for (e, fl, v) in facts if fl <= D]
    if not cand:
        return None
    best_end = max(e for (e, fl, v) in cand)
    same = sorted([(fl, v) for (e, fl, v) in cand if e == best_end])
    return best_end, same[0][1]

def prior_annual(facts, D, cur_end):
    cand = [(e, fl, v) for (e, fl, v) in facts if fl <= D and e < cur_end and (cur_end - e).days >= 300]
    if not cand:
        return None
    best_end = max(e for (e, fl, v) in cand)
    same = sorted([(fl, v) for (e, fl, v) in cand if e == best_end])
    return best_end, same[0][1]

def annual_series(facts, D, n=4):
    """Up to n most-recent distinct-FY as-filed annual values (end_date, val) with filed<=D, newest first."""
    cand = [(e, fl, v) for (e, fl, v) in facts if fl <= D]
    if not cand:
        return []
    by_end = {}
    for (e, fl, v) in cand:
        if e not in by_end or fl < by_end[e][0]:   # earliest filed for that period (as-filed)
            by_end[e] = (fl, v)
    ends = sorted(by_end, reverse=True)[:n]
    return [(e, by_end[e][1]) for e in ends]

def as_of_instant(facts, D):
    cand = [(e, fl, v) for (e, fl, v) in facts if fl <= D]
    if not cand:
        return None
    best_end = max(e for (e, fl, v) in cand)
    same = sorted([(fl, v) for (e, fl, v) in cand if e == best_end])
    return same[0][1]

def instant_prior(facts, D, ref_end, min_gap=300):
    cand = [(e, fl, v) for (e, fl, v) in facts if fl <= D and e < ref_end and (ref_end - e).days >= min_gap]
    if not cand:
        return None
    best_end = max(e for (e, fl, v) in cand)
    same = sorted([(fl, v) for (e, fl, v) in cand if e == best_end])
    return best_end, same[0][1]

# ---------- prices ----------
def load_prices(path):
    dates, adj, dollar = [], [], []
    with open(path) as f:
        next(f)
        for line in f:
            p = line.split(",")
            if len(p) < 7:
                continue
            try:
                d = _d(p[0]); a = float(p[5]); close = float(p[4]); vol = float(p[6])
            except Exception:
                continue
            if a > 0:
                dates.append(d); adj.append(a); dollar.append(close * vol)
    return dates, adj, dollar

def price_row(dates, adj, dollar, D):
    i = bisect.bisect_right(dates, D) - 1
    if i < 252:
        return None
    price = adj[i]
    sma20 = sum(adj[i-19:i+1]) / 20
    sma50 = sum(adj[i-49:i+1]) / 50
    sma200 = sum(adj[i-199:i+1]) / 200
    hi52 = max(adj[i-251:i+1])
    pct_from_high = (price / hi52 - 1) * 100
    perf_1m = (price / adj[i-21] - 1) * 100
    perf_3m = (price / adj[i-63] - 1) * 100
    perf_1y = (price / adj[i-251] - 1) * 100
    dv = sorted(dollar[i-19:i+1])
    dvmed = dv[len(dv)//2] if dv else 0.0
    return dict(price=price, sma_20=sma20, sma_50=sma50, sma_200=sma200,
                pct_from_52w_high=pct_from_high, perf_1m=perf_1m, perf_3m=perf_3m,
                perf_1y=perf_1y, dollar_vol=dvmed, _idx=i)

def fwd_return(dates, adj, D, months):
    target = D + dt.timedelta(days=int(round(months * 30.44)))
    j = bisect.bisect_left(dates, target)
    if j >= len(dates):
        return None
    i = bisect.bisect_right(dates, D) - 1
    if i < 0:
        return None
    return adj[j] / adj[i] - 1

# ---------- score_long_term (faithful port from lt_reconstruct.py) ----------
def score_lt(row):
    bd = {}
    rg = row.get("revenue_growth_pct") or 0
    om = row.get("operating_margin_pct") or 0
    gm = row.get("gross_margin_pct") or 0
    margin = om if om != 0 else (gm * 0.5)
    r40 = rg + margin
    if r40 >= 60: raw = 1.0
    elif r40 >= 40: raw = 0.7 + 0.3 * ((r40 - 40) / 20)
    elif r40 >= 25: raw = 0.3 + 0.4 * ((r40 - 25) / 15)
    elif r40 >= 0: raw = 0.1 + 0.2 * (r40 / 25)
    else: raw = 0
    bd["rule_of_40"] = sc(raw, W["rule_of_40"])

    ev_rev = row.get("ev_revenue") or row.get("ps_ratio") or 999
    g4v = max(rg, 1)
    vr = ev_rev / g4v if g4v > 0 else 999
    if ev_rev < 3 and rg > 10: raw = 1.0
    elif vr < 0.3 and ev_rev < 15: raw = 0.85
    elif vr < 0.5 and ev_rev < 20: raw = 0.75
    elif vr < 0.8 and ev_rev < 25: raw = 0.6
    elif ev_rev < 10: raw = 0.5
    elif ev_rev < 20: raw = 0.35
    else: raw = max(0, 0.15 - (ev_rev - 20) / 100)
    bd["valuation"] = sc(raw, W["valuation"])

    fm = row.get("fcf_margin_pct")
    if fm is not None:
        if fm >= 25: raw = 1.0
        elif fm >= 15: raw = 0.7 + 0.3 * ((fm - 15) / 10)
        elif fm >= 5: raw = 0.3 + 0.4 * ((fm - 5) / 10)
        elif fm >= 0: raw = 0.15
        else: raw = 0
    else:
        raw = 0
    bd["fcf_margin"] = sc(raw, W["fcf_margin"])

    price = row.get("price", 0); s20 = row.get("sma_20"); s50 = row.get("sma_50"); s200 = row.get("sma_200")
    ts = tmax = 0
    if s200 is not None:
        tmax += 2
        if price > s200: ts += 2
    if s50 is not None:
        tmax += 1.5
        if price > s50: ts += 1.5
    if s20 is not None:
        tmax += 1
        if price > s20: ts += 1
    if s50 and s200 and s50 > s200:
        ts += 0.5; tmax += 0.5
    raw = ts / tmax if tmax > 0 else 0.5
    bd["trend"] = sc(raw, W["trend"])

    eps = row.get("eps"); pe = row.get("pe_ratio"); q = 0
    if eps is not None and eps > 0:
        q += 0.4
        if pe and 10 < pe < 40: q += 0.2
        elif pe and pe > 0: q += 0.1
    elif rg > 30: q += 0.2
    if gm > 75: q += 0.3
    elif gm > 60: q += 0.2
    elif gm > 40: q += 0.1
    elif gm > 0: q += 0.05
    bd["earnings_quality"] = sc(min(1.0, q), W["earnings_quality"])

    disc = row.get("pct_from_52w_high") or 0; p3 = row.get("perf_3m") or 0; p1 = row.get("perf_1m") or 0
    dr = 0
    if disc < -30:
        dr = 1.0 if p1 > 0 else 0.6
    elif disc < -15:
        dr = 0.7 if p1 > 0 else 0.4
    elif disc < -5:
        dr = 0.65 if p3 > 0 else 0.5
    else:
        dr = 1.0 if p3 > 10 else (0.65 if p3 > 0 else 0.3)
    bd["discount_momentum"] = sc(min(1.0, dr), W["discount_momentum"])
    bd["lt_score"] = round(sum(bd[k] for k in W), 1)
    return bd

def altman_z(mktcap, assets, liab, assets_cur, liab_cur, retearn, ebit, revenue):
    if not assets or assets <= 0:
        return None
    try:
        wc = (assets_cur - liab_cur) if (assets_cur is not None and liab_cur is not None) else None
        terms = 0.0; have = 0
        if wc is not None: terms += 1.2 * (wc / assets); have += 1
        if retearn is not None: terms += 1.4 * (retearn / assets); have += 1
        if ebit is not None: terms += 3.3 * (ebit / assets); have += 1
        if mktcap is not None and liab: terms += 0.6 * (mktcap / liab); have += 1
        if revenue is not None: terms += 1.0 * (revenue / assets); have += 1
        if have < 4:   # need most of the formula to make a Z meaningful
            return None
        return round(terms, 2)
    except Exception:
        return None

def main():
    man = json.load(open(os.path.join(ROOT, "universe", "manifest.json")))
    tickers = man["tickers"]
    snaps = []
    y, m = 2014, 12
    while (y, m) <= (2025, 6):
        snaps.append(dt.date(y, m, 1)); m += 1
        if m > 12: m = 1; y += 1

    records = []
    n_names = 0
    delisted_no_price = []

    for t in tickers:
        ppath = os.path.join(PRICES, "%s.csv" % t)
        if not os.path.exists(ppath) or os.path.getsize(ppath) < 200:
            delisted_no_price.append(t); continue
        dates, adj, dollar = load_prices(ppath)
        if len(dates) < 300:
            continue
        fpath = os.path.join(EDGAR, "%s.facts.json" % t)
        g = {}; gdei = {}
        if os.path.exists(fpath):
            try:
                fj = json.load(open(fpath))
                g = fj.get("facts", {}).get("us-gaap", {})
                gdei = fj.get("facts", {}).get("dei", {})
            except Exception:
                g = {}; gdei = {}
        rev_a = annual_facts(g, REV); op_a = annual_facts(g, OPINC); gp_a = annual_facts(g, GROSS)
        ocf_a = annual_facts(g, OCF); cap_a = annual_facts(g, CAPEX); eps_a = annual_facts(g, EPS)
        acq_a = annual_facts(g, ACQ); intexp_a = annual_facts(g, INTEXP); da_a = annual_facts(g, DA)
        sh_i = instant_facts(gdei, SHARES); dltf = instant_facts(g, DEBT_LT)
        dcurf = instant_facts(g, DEBT_CUR); cashf = instant_facts(g, CASH)
        gw_i = instant_facts(g, GOODWILL); assets_i = instant_facts(g, ASSETS)
        liab_i = instant_facts(g, LIAB); ac_i = instant_facts(g, ASSETS_CUR)
        lc_i = instant_facts(g, LIAB_CUR); re_i = instant_facts(g, RETEARN)
        n_names += 1

        for D in snaps:
            pr = price_row(dates, adj, dollar, D)
            if pr is None:
                continue
            f6 = fwd_return(dates, adj, D, 6); f12 = fwd_return(dates, adj, D, 12)
            if f6 is None and f12 is None:
                continue
            row = dict(pr)
            rec = dict(ticker=t, snap=D.isoformat(), fwd6=f6, fwd12=f12,
                       price=pr["price"], perf_1y=pr["perf_1y"], perf_3m=pr["perf_3m"],
                       perf_1m=pr["perf_1m"], pct_from_high=pr["pct_from_52w_high"],
                       dollar_vol=pr["dollar_vol"])
            rev_series = annual_series(rev_a, D, 4)
            rev = as_of_annual(rev_a, D)
            mktcap = None
            if rev:
                rev_end, rev_val = rev
                pri = prior_annual(rev_a, D, rev_end)
                if pri and pri[1] and rev_val:
                    row["revenue_growth_pct"] = (rev_val / pri[1] - 1) * 100
                op = as_of_annual(op_a, D)
                op_val = op[1] if op else None
                if op and rev_val:
                    row["operating_margin_pct"] = op[1] / rev_val * 100
                gp = as_of_annual(gp_a, D)
                if gp and rev_val:
                    row["gross_margin_pct"] = gp[1] / rev_val * 100
                ocf = as_of_annual(ocf_a, D); cap = as_of_annual(cap_a, D)
                if ocf and rev_val:
                    capv = cap[1] if cap else 0
                    row["fcf_margin_pct"] = (ocf[1] - capv) / rev_val * 100
                sh = as_of_instant(sh_i, D)
                if sh and sh > 0 and rev_val:
                    mktcap = row["price"] * sh
                    debt = (as_of_instant(dltf, D) or 0) + (as_of_instant(dcurf, D) or 0)
                    cash = as_of_instant(cashf, D) or 0
                    row["ev_revenue"] = (mktcap + debt - cash) / rev_val
                eps = as_of_annual(eps_a, D)
                if eps:
                    row["eps"] = eps[1]
                    if eps[1] and eps[1] > 0:
                        row["pe_ratio"] = row["price"] / eps[1]
                # ---- gate inputs ----
                rec["revenue"] = rev_val
                rec["op_margin"] = row.get("operating_margin_pct")
                rec["gross_margin"] = row.get("gross_margin_pct")
                # multi-year organic revenue trend (CAGR over available <=4 FY)
                if len(rev_series) >= 3:
                    newest = rev_series[0][1]; oldest = rev_series[-1][1]; yrs = len(rev_series) - 1
                    if oldest and oldest > 0 and newest and newest > 0:
                        rec["rev_cagr_3y"] = ((newest / oldest) ** (1.0 / yrs) - 1) * 100
                    rec["rev_series"] = [v for (_, v) in rev_series]
                # margin trend: current op margin minus op margin ~3 FY ago
                op_series = annual_series(op_a, D, 4)
                if op_val is not None and rev_val and len(op_series) >= 3 and len(rev_series) >= 3:
                    old_op = op_series[-1][1]; old_rev = rev_series[-1][1]
                    if old_rev and old_rev > 0:
                        rec["op_margin_delta_3y"] = (op_val / rev_val - old_op / old_rev) * 100
                # M&A detection
                acq = as_of_annual(acq_a, D)
                rec["acq_spend"] = acq[1] if acq else None
                rec["acq_spend_pct_rev"] = (acq[1] / rev_val * 100) if (acq and rev_val) else None
                gw = as_of_instant(gw_i, D)
                rec["goodwill"] = gw
                if gw is not None and rev_val:
                    rec["goodwill_pct_rev"] = gw / rev_val * 100
                gw_end = None
                if gw is not None:
                    # find goodwill period end to anchor the prior
                    gcand = [(e, fl, v) for (e, fl, v) in gw_i if fl <= D]
                    if gcand:
                        gw_end = max(e for (e, fl, v) in gcand)
                        gwp = instant_prior(gw_i, D, gw_end)
                        if gwp and gwp[1] is not None and rev_val:
                            rec["goodwill_step_pct_rev"] = (gw - gwp[1]) / rev_val * 100
                # shares dilution step (acquisitions often issue stock)
                if sh and sh > 0:
                    shp = instant_prior(sh_i, D, max(e for (e, fl, v) in sh_i if fl <= D)) if any(fl <= D for (e, fl, v) in sh_i) else None
                    if shp and shp[1]:
                        rec["shares_growth_pct"] = (sh / shp[1] - 1) * 100
                # solvency
                rec["mktcap"] = mktcap
                assets = as_of_instant(assets_i, D); liab = as_of_instant(liab_i, D)
                ac = as_of_instant(ac_i, D); lc = as_of_instant(lc_i, D)
                re = as_of_instant(re_i, D)
                ie = as_of_annual(intexp_a, D); da = as_of_annual(da_a, D)
                rec["retained_earnings"] = re
                rec["interest_expense"] = ie[1] if ie else None
                if op_val is not None and ie and ie[1] and ie[1] > 0:
                    rec["interest_coverage"] = op_val / ie[1]
                ebitda = None
                if op_val is not None:
                    ebitda = op_val + (da[1] if da else 0)
                if ebitda is not None and ebitda > 0:
                    debt = (as_of_instant(dltf, D) or 0) + (as_of_instant(dcurf, D) or 0)
                    cash = as_of_instant(cashf, D) or 0
                    rec["net_debt_ebitda"] = (debt - cash) / ebitda
                rec["altman_z"] = altman_z(mktcap, assets, liab, ac, lc, re, op_val, rev_val)
            bd = score_lt(row)
            for k in W:
                rec["c_" + k] = bd[k]
            rec["lt_score"] = bd["lt_score"]
            rec["ev_revenue"] = row.get("ev_revenue")
            rec["revenue_growth_pct"] = row.get("revenue_growth_pct")
            records.append(rec)

    json.dump({"meta": {"n_names": n_names, "n_delisted_no_price": len(delisted_no_price),
                        "delisted": delisted_no_price, "n_records": len(records),
                        "snaps": [s.isoformat() for s in snaps]},
               "records": records}, open(OUT, "w"))
    print("wrote %d records, %d names, %d delisted-no-price -> %s" %
          (len(records), n_names, len(delisted_no_price), OUT))

if __name__ == "__main__":
    main()
