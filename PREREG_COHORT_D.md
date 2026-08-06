# PRE-REGISTRATION — Cohort D: index-level defined-risk premium selling (PAPER)

**Registered:** 2026-08-06 · **Lane:** R4 / Lane 2 · **Status:** paper only, zero capital
**Authored and committed BEFORE any logger code existed.** Commit ordering is the proof:
the commit adding this file precedes the commit adding `research/cohortd/`. Everything
below — entry threshold, structure, settlement math, verdict rules, stopping rules — is
fixed at registration time and may not be tuned by the implementation or mid-cohort.

This document is the contract. `research/cohortd/` implements it; it does not get to
reinterpret it.

---

## 1. The hypothesis, stated narrowly

**H1 (what we are testing):** after paying defined-risk structure costs, a *residual*
index-level variance risk premium is harvestable on SPY when implied volatility exceeds a
genuine forecast of realized volatility.

**H0 (the null, and the expected outcome):** **zero alpha.** SPX short-option alpha has
been statistically indistinguishable from zero since August 2012.

> **The most likely honest outcome of this cohort is confirming H0.** That is written here
> deliberately, at registration, so that a null result is recorded as the anticipated
> finding rather than reframed later as a disappointment, a data problem, or a reason to
> adjust the rules. A confirmed H0 is a successful cohort.

## 2. Why the hypothesis is this narrow — the evidence base, stated honestly

From `RESEARCH_INVESTMENT_MODELS_2026-08-04.md` §3, which **downgraded** the original
cohort-D nomination. All of this is inherited as prior, not re-litigated:

| Finding | Source | Consequence for this cohort |
|---|---|---|
| Our 14/16 condor record was **luck-compatible**: P(≥13 of 15) under a fair 75%-POP condor ≈ **24%** | direct binomial, verified in-session | Win rate is disqualified as evidence. The tail pays for the win rate and 15 trades cannot sample the tail. |
| SPX ATM-straddle CAPM alpha **−0.74 annualized pre-Aug-2012, +0.12 and insignificant after**; mechanism is dealer-friction normalization | **Dew-Becker / Giglio** | **This is H0.** A retail seller starting in 2026 harvests mostly equity/crash beta, not the 1990s–2000s premium. |
| The ex-ante premium does **not** expand when risk rises | Cheng, RFS 2019 | "Sell when vol is high" is **not** a free timing rule. Our entry filter must be IV minus a *forecast*, not IV level or IV rank. |
| Significant mean variance premia in only **3 of 35** single stocks | Carr-Wu 2009 | Single names are the wrong venue. |
| Single-stock VRP statistically **zero** on average; index vol is the reliably rich thing (priced correlation risk) | Driessen-Maenhout-Vilkov, JF | Universe is index-only. |
| Cross-sectional single-name edge **dies at realistic spreads** | Cao-Han, JFE 2013 | — |
| Selling single-name premium into earnings is **negative** expectancy | Gao-Xing-Zhang, JFQA 2018 | No earnings-timed entries. |
| IV-rank entry filters have **no peer-reviewed support**; tastylive studies are methodologically weak | §3 | IV rank is explicitly **not** used. |

**Single-name condors are retired as a thesis.** This cohort is the surviving, narrower
question only.

## 3. Universe

**SPY only.** One instrument. No single names, no other ETFs, no breadth. Any expansion of
the universe is a *new* cohort with a new pre-registration, not a modification of this one.

## 4. Structure — fixed

| Parameter | Value |
|---|---|
| Instrument | SPY |
| Structure | Iron condor (defined risk, four legs) |
| Cadence | Monthly — one cycle per calendar month |
| Short strikes | Nearest **20-delta**, both sides |
| Long wings | Nearest **5-delta**, both sides (CNDR-style) |
| DTE at entry | **30–45 days**; if several expiries qualify, take the one nearest 37 DTE |
| Management | **NONE. Hold to expiry.** |
| Size | 1 nominal unit per entry |
| Defined risk | `max(put_width, call_width) − credit` |

**No management is a registered condition, not an omission.** Profit-taking, rolling and
stop rules are a *second cohort*, tested separately. Adding a management rule to this
cohort mid-flight converts it into an untested strategy with a contaminated history.

Deltas and prices are taken from the yfinance option chain at entry. Where the chain
supplies no delta, delta is computed Black-Scholes from the chain's implied volatility.
Credit is computed at the **mid** of bid/ask per leg. Mid-pricing is optimistic relative
to real fills; it is registered as a **known upward bias** and stated on every read.

## 5. Entry rule — the threshold is fixed NOW and never tuned

Enter on the **first trading day of each calendar month**, and only if:

```
ATM_IV30  −  HAR_RV_21d_forecast  >=  2.0 volatility points
```

- `ATM_IV30` — implied volatility of the at-the-money option nearest 30 DTE, in annualized
  vol points (e.g. `18.5`).
- `HAR_RV_21d_forecast` — HAR-RV forecast of annualized realized volatility over the next
  21 trading days, per **Corsi (2009)**.
- **2.0 volatility points.** Fixed at registration. **This threshold is never tuned, never
  optimized, and never re-fit mid-cohort.** If it proves wrong, that is a finding reported
  at the end, not a parameter adjusted along the way.

If the condition fails, **no entry that month** and the miss is logged with its computed
values. Logged misses are part of the record: a filter that never rejects anything is not a
filter, and the rejection rate is itself a reported statistic.

### HAR-RV specification (fixed)

Corsi's heterogeneous autoregressive model on daily realized variance:

```
RV_{t+1:t+21}  =  b0  +  bd*RV_d  +  bw*RV_w  +  bm*RV_m  +  e
```

where `RV_d` is the latest daily realized variance, `RV_w` the mean of the last 5, `RV_m`
the mean of the last 22. Fitted by OLS on an **expanding window** of SPY history using only
data available at the entry date (no lookahead). Daily realized variance uses **close-to-close
log returns**: `RV_t = r_t^2`, annualized as `sqrt(252 * mean(RV)) * 100`.

**Documented approximation:** close-to-close is a noisier RV proxy than intraday realized
variance. It is accepted here because the decision is a coarse 2.0-vol-point threshold, not
a precise variance estimate, and because intraday SPY data is not available to this lane.
This choice is registered, not discovered later.

**Optional second model:** if the `arch` package is available, a GARCH(1,1) forecast is
computed and **logged alongside** for comparison. **The entry rule uses HAR only.** GARCH
never gates an entry; it exists so that a future analysis can ask whether the forecast
choice mattered. If `arch` is absent the run proceeds and logs the reason.

## 6. Settlement — fixed, mechanical, at expiry

Settlement uses the **SPY close on the expiry date**. No early assignment modelling, no
intra-cycle marks. With short/long put strikes `Ps > Pl`, short/long call strikes
`Cs < Cl`, credit `C`, and settlement price `S`:

```
put_side   =  max(0, Ps - S)  -  max(0, Pl - S)
call_side  =  max(0, S - Cs)  -  max(0, S - Cl)
pnl        =  C  -  (put_side + call_side)
```

Outcomes this must produce, and which the tests sweep:

| Settlement region | Expected |
|---|---|
| `S` between the short strikes | both sides zero → `pnl = C` (maximum win) |
| `S` below the long put wing | put side capped at `Ps − Pl` → `pnl = C − put_width` (max loss) |
| `S` above the long call wing | call side capped at `Cl − Cs` → `pnl = C − call_width` (max loss) |
| `S` between short and long put | partial loss, `0 < loss < put_width` |
| `S` between short and long call | partial loss, `0 < loss < call_width` |

**Win** is `pnl > 0`. Per-cycle return is expressed as an **R-multiple**:
`pnl / defined_risk`, so cycles are comparable regardless of width.

## 7. Metrics — reported every read

- **Win rate** with **Wilson 95% CI** (never a bare proportion).
- **Expectancy**: mean R-multiple per cycle, with a **bootstrap 95% CI** (10,000 percentile
  resamples). Bootstrap rather than a t-interval because short-premium P&L is strongly
  left-skewed and the normal approximation understates tail risk at small n.
- **Profit factor**: gross wins ÷ gross losses.
- **Max drawdown** on the cumulative R curve.
- **Filter rejection rate**: entries taken ÷ months evaluated.
- **SPY-beta baseline** (see §9).

## 8. Read cadence, verdict labels, and the power math

**Read cadence: monthly.**

Verdict labels are capped by sample size and may not be upgraded by enthusiasm:

| n (settled cycles) | Maximum claim |
|---|---|
| n < 30 | **DIRECTIONAL** — no verdict, descriptive only |
| 30 ≤ n < 100 | **DIRECTIONAL**, fail-stop active (§10) |
| n ≥ 100 | Verdict permitted, subject to §9 |

### The power math, stated plainly

Monthly cadence means **at most 12 entries per year**, and the §5 filter will reject some
months. If the filter passes roughly half of months — a reasonable prior, not a
measurement — the realistic rate is **~6 entries/year**.

| milestone | months evaluated | at 12/yr | at ~6/yr |
|---|---|---|---|
| n = 30 (fail-stop arms) | 30–60 | ~2.5 yr | **~5 yr** |
| n = 100 (verdict permitted) | 100–200 | ~8.3 yr | **~17 yr** |

> **This cohort runs for years, and that is the design, not a defect.** It is a background
> lane. It will not produce a verdict this year, or next. Any pressure to read a verdict
> early is answered by the table above, not by lowering the bar.

**⚠️ Correction to the brief (recorded, not silently absorbed):** the session brief
estimates "~1-2 entries/month". Strict monthly cadence (§4) caps entries at **one per
month**, so 1–2 per month is unreachable and the implied 4–8 year horizon to n=100 is
optimistic. The honest figure is **8.3 years at best and ~17 years at a realistic filter
rate.** The cadence is kept as registered; the expectation is corrected.

## 9. What counts as a PASS — alpha, not win rate

A pass claim requires **all** of:

1. **n ≥ 100** settled cycles.
2. **Alpha against a SPY-beta baseline.** Regress per-cycle cohort R-multiples on
   contemporaneous SPY returns over the same holding window:
   `R_i = alpha + beta * SPY_i + e_i`. The claim requires **alpha > 0 with its 95% CI
   excluding zero**. A short-condor book is structurally short crash risk and therefore
   loaded on equity beta; an unadjusted return is mostly that beta, which is free.
3. **The result survives the mid-pricing bias** (§4): re-settled at a conservative fill
   assumption, alpha must remain positive.

**Explicitly NOT a pass:**

- A high raw win rate. Short premium is engineered to win often and lose big; win rate
  without the tail is not evidence. This is the exact error §2 documents in our own 14/16.
- Positive total return. That is likely beta.
- Any single good year, or any run of consecutive wins.

## 10. Fail-stop — fixed

**At n ≥ 30, if the 95% bootstrap CI for expectancy lies entirely below zero, the cohort
STOPS.** Not pauses, not re-parameterizes — stops, and the negative result is written up.

Additional stop conditions, registered now:

- Any change to the entry threshold, structure, or settlement math **ends this cohort** and
  starts a new one with a new registration and a fresh `cohort_version`. The old record is
  never rewritten or re-labelled.
- If SPY option chain data becomes unavailable such that entries cannot be evaluated for
  three consecutive months, the cohort is suspended and the gap recorded.

## 11. Discipline and isolation

- **Paper only. Zero capital.** Nothing here authorizes a trade.
- **Full isolation:** this lane never opens `cyberscreener.db`, not even read-only. It
  imports nothing from `api/`. SPY data comes from yfinance directly. Storage is a new
  database, `~/cs-research/cohortD.db`.
- **Append-only:** entries are deduplicated on cycle date; settlement fills only NULL
  fields. A re-run never modifies an existing row.
- Nothing in this cohort feeds the live scorer, the journal, or any weight. Promotion of
  anything learned here would run through `PROMOTION_CRITERIA.md` as a separate step.

## 12. What would make this cohort worth having, even if H0 holds

A clean, pre-registered null on index premium selling — measured with defined risk, an
honest forecast-based filter, and a beta-adjusted benchmark — closes a question that has
already cost this project one failed cohort of real conviction. Recording that the residual
premium is not harvestable at retail scale, with the arithmetic to show it, is a result
worth the years of background logging.
