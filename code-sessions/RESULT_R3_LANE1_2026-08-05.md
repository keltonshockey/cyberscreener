# RESULT — R3 Lane 1: Long-horizon valuation program on the decade PIT corpus

**Date:** 2026-08-05
**Branch:** `feat/r3-lane1-pit` (local on mill; mill cannot push — bundle + laptop commands at the end)
**Base:** `e335637` — verified identical to canonical `github/main` (see premise check)
**Corpus:** `/Users/mill/lt-recon-data` (2.2 GB), opened READ-ONLY throughout
**Runtime:** Python 3.11.15 at `/Users/mill/.venvs/lane1` (uv-provisioned, user-space)
**Status:** IN PROGRESS — written incrementally, rsynced to NAS at each milestone

---

## HARD GATE — ark check (first action, before any corpus read)

The brief's exact command, run before anything else:

```
ssh kshockey@192.168.1.173 "ls -l /volume1/ai-stack/backups/ark/ark-lt-recon-20260804.tar.gz \
                               /volume1/ai-stack/backups/ark/ark-cs-20260804.db.gz"
```

```
-rw------- 1 kshockey users 171571108 Aug  4 16:11 .../ark-cs-20260804.db.gz
-rw-r--r-- 1 kshockey users 220563957 Aug  4 16:14 .../ark-lt-recon-20260804.tar.gz
```

**Both present → PROCEED.** (`ark-cs` size 171,571,108 also matches the laptop copy
byte-for-byte, an independent confirmation of the R0 record.)

---

## Premise checks before building

Four premises were checked against the machine rather than taken from the brief.
Two of them were wrong.

### ⚠️ 1. This session is NOT running on mill

The brief opens *"Run as: Claude Code ON MILL (the corpus lives there)"*. The session
actually started on the laptop (`Shockey1-2.local`, user `kshockey`); `/Users/mill` does
not exist there, so every path in the brief — corpus, venv, output dirs, kb-mirror — was
unreachable as written.

Escalated to Kelton with three options. **Decision: drive mill over SSH.** All corpus
reads, the venv, every output file, and the git branch therefore live on mill exactly as
briefed; only the agent process is remote. Verified before proceeding that mill's
`~/kb-mirror` copy of the brief is byte-identical to the laptop's
(sha256 `4b56aabf…5efd`), so no stale-mirror divergence is in play.

Incidental finding worth fixing: `~/.ssh/config` on the laptop maps
`Host mill … 100.69.49.8` → `HostName mill`, which is circular — `ssh mill@100.69.49.8`
fails with *"Could not resolve hostname mill"*. The LAN path (`mill@192.168.1.197`) works
and was used. This is the OPERATIONS_PLAYBOOK §9 fifth-entry trap in its literal form: the
**tailnet path is unusable while the LAN path succeeds**, so any check written against the
LAN IP would report healthy regardless of tailnet state. Not fixed here (laptop config,
outside this session's scope) — flagged for Kelton.

### ⚠️ 2. mill has NO Python 3.11

The brief mandates a 3.11 venv and explicitly forbids system 3.9 and brew 3.14 as having
"caused false results here before". Neither `python3.11` nor
`/opt/homebrew/bin/python3.11` exists on mill; `python3` is **3.14.6** and `/usr/bin/python3`
is **3.9.6** — i.e. the only two interpreters present are the two that are forbidden.
Had this not been checked, the analysis would have silently run on 3.14.

`uv` is installed. **Decision (Kelton): `uv venv --python 3.11 ~/.venvs/lane1`**, which
fetches a standalone CPython 3.11.15 into `~/.local/share/uv/python` — user-space, no
sudo, no mutation of the shared `/opt/homebrew` prefix that the narrative and gate-read
jobs depend on, no daemon, and removable with `rm -rf` of two paths. Confirmed running
**Python 3.11.15**, pandas 3.0.5, numpy 2.4.6.

### 3. Repo base is current (checked, correct)

Mill's `~/r3-lane1` clone has only `origin` = the NAS git mirror; it has no `github`
remote, so the brief's *"branch off github/main and verify the base is current"* could not
be verified on mill itself. Verified from the laptop instead: mill's base `e335637` is
**identical to canonical `github/main`**. The NAS mirror is no longer stale — RESULT_R1's
correction 1 has since been resolved.

### 4. Corpus matches the June description (checked, correct)

| Artifact | June claim | Actual | |
|---|---|---|---|
| `prices/*.csv` | 427 | **427** | ✅ |
| `edgar/*.facts.json` | 422 | **422** | ✅ |
| `edgar/*.submissions.json` | — | 423 | — |
| `universe/manifest.json` tickers | 473 | **473** | ✅ |
| names with no price (survivorship gap) | 46 | **46** | ✅ |
| `cik_map.json` entries | >5000 (gate) | **10,400** | ✅ |

The 46 missing-price names are the same set June listed (ABMD, ANSS, ATVI, CARVANA, CHK,
CIVI, CLR, CMA, CONE, CPE, CTLT, DFS, DISH, FI, …). **No recalibration needed** — the
corpus is unchanged since 2026-06-09.

### Read-only compliance statement

No script in `research/lane1/` contains `rm`, `mv`, or an open-for-write against
`~/lt-recon-data`. This is **enforced by test**, not asserted: `test_lane1_pit.py::
test_lane1_never_opens_the_corpus_for_write` AST-parses every module in `research/lane1/`
and fails on any `open(mode=…)` that is not a read mode, or any call to
`remove/unlink/rmtree/rename/replace/rmdir`. Outputs go to `~/lt-recon-data-derived/` and
`~/mill-local-edits/lane1/` only.

---

## MILESTONE A — corpus audit + harness port + reproduction gate

### The port

The June engine (`~/mill-local-edits/lt_reconstruct.py`, 459 lines, single file) is now a
versioned package in the repo at `research/lane1/`:

| Module | Contents |
|---|---|
| `pit.py` | companyfacts as-filed extraction; the `filed <= D` discipline |
| `prices.py` | price series, PIT price row, forward returns |
| `scoring.py` | faithful port of June-era `score_long_term` + `DEFAULT_LT_WEIGHTS` |
| `stats.py` | rank/spearman/t-stat, within-snapshot quintile pooling |
| `panel.py` | monthly PIT panel construction, IC series, split points |
| `reproduce_june.py` | the Milestone A regression gate (CLI) |

Numerics are preserved exactly; the reorganisation is structural. Two deliberate
non-ports, both recorded because they look like drift and are not:

1. **`scoring.py` is a COPY of the June-era scorer, not an import of the live one.** The
   live scorer has since moved to the v2 baseline (LT = Valuation 100). Importing it would
   silently re-point the regression gate at different weights and June could never
   reproduce. It also drags in `core.scanner` → yfinance (RESULT_R2_IC_HARNESS correction
   3). This file is frozen June-era logic and must NOT be updated to track the live scorer.
2. **Split points are computed on the snapshot WINDOW**, matching June's
   `snaps[len(snaps)//2]` and `snaps[int(len(snaps)*0.6)]` — and matching
   RESULT_R2_IC_HARNESS correction 4, where splitting the observation list instead moved a
   boundary by a full horizon and flipped a component's verdict. Pinned by two tests,
   including one on a panel whose tail is deliberately empty (the shape that exposes the bug).

### Reproduction result — **PASSED**

```
panel: 427 names, 127 snapshots 2014-12-01..2025-06-01, median 413 names/snapshot
delisted without prices (survivorship gap): 46
sub-period midpoint: 2020-03-01   OOS split: 2021-04-01 (77 in / 50 out)
```

Full component table, reproduced (June §7.1 / §7.2 in parentheses where published):

| component | IC @6mo | t | IC @12mo | t | H1→H2 @12mo | consistent |
|---|---|---|---|---|---|---|
| rule_of_40 | +0.0066 | +0.54 | +0.0017 | +0.15 | +0.0745 → −0.0723 | no (flips) |
| **valuation** | **+0.0380** | **+6.85** | **+0.0551** | **+11.40** | **+0.0325 → +0.0780** | **yes** |
| fcf_margin | +0.0125 | +1.82 | +0.0046 | +0.80 | +0.0146 → −0.0057 | no |
| trend | +0.0099 | +0.74 | −0.0013 | −0.10 | +0.0172 → −0.0200 | no |
| earnings_quality | −0.0044 | −0.48 | −0.0143 | −1.66 | +0.0381 → −0.0675 | no |
| discount_momentum | +0.0078 | +0.77 | +0.0249 | +2.23 | +0.0128 → +0.0372 | borderline |
| lt_score | +0.0193 | +1.92 | +0.0151 | +1.63 | +0.0515 → −0.0219 | no |

Every value matches the June table exactly. The 12 gate assertions:

| check | got | want | tol | |
|---|---|---|---|---|
| panel n_names / n_snaps / delisted | 427 / 127 / 46 | 427 / 127 / 46 | exact | ✅ |
| valuation@6 mean_ic | +0.0380 | +0.0380 | 0.0005 | ✅ |
| valuation@6 t | +6.8456 | +6.85 | 0.02 | ✅ |
| valuation@6 H1 / H2 | +0.0153 / +0.0611 | +0.0153 / +0.0611 | 0.0005 | ✅ |
| valuation@12 mean_ic | +0.0551 | +0.0551 | 0.0005 | ✅ |
| valuation@12 t | +11.4013 | +11.40 | 0.02 | ✅ |
| valuation@12 H1 / H2 | +0.0325 / +0.0780 | +0.0325 / +0.0780 | 0.0005 | ✅ |
| valuation@6 Q5−Q1 IN / OOS | +1.6744% / +2.4792% | +1.67% / +2.48% | 0.05pp | ✅ |
| valuation@12 Q5−Q1 IN / OOS | +3.0702% / +5.9260% | +3.07% / +5.93% | 0.05pp | ✅ |

**REPRODUCTION PASSED — Milestone A gate is GREEN.** Downstream milestones may proceed.

Tolerances are tight on purpose: the port is meant to be numerically identical, so ICs are
held to 0.0005 — enough to catch a changed split point, a different tie rule, or a leaked
restatement, while absorbing float-summation ordering.

### Tests — 26 passing

`api/tests/test_lane1_pit.py`. The corpus-dependent gate is marked and skips where the
corpus is absent (it lives only on mill), so the suite stays runnable on the laptop and in
CI; the logic tests always run on synthetic facts.

The lookahead tests are the ones that matter. The canonical bug they pin: FY2020 revenue
of 100.0 filed 2021-02-15, restated to 175.0 filed 2022-03-01. A backtest standing at
2021-06-01 must see **100.0**. Both directions are asserted — the restated value must not
leak backwards, and even after the restatement is filed the as-filed number stays 100.0.
Also pinned: prior-year facts respect the same cutoff, quarterly/8-K facts never enter the
annual series, and the concept fallback order works when a preferred tag is empty.

### Anti-stranding

`~/mill-local-edits/lane1/` rsynced to NAS `.../ark/lane1-20260805/` — confirmation below.

---

## MILESTONE B — quarterly-TTM re-test — **KILL CONDITION MET**

### The stitcher, validated before it was trusted

June used ANNUAL figures "deliberately, to avoid XBRL quarter-stitching errors", so the
whole milestone rests on stitching quarters correctly. Two traps had to be handled:

1. **Q4 is usually never filed.** Most registrants file 10-Qs for Q1–Q3 and roll Q4 into
   the 10-K. Naively summing filed quarterly facts builds a **3-quarter TTM** for every
   fiscal year — understating revenue ~25% and inventing growth wherever the available
   mix changes.
2. **Many filers report cumulative YTD**, so the Q3 10-Q carries a 270-day period, not a
   90-day one. Summing those double-counts badly.

Both are handled by derivation-by-subtraction over exact `(start, end)` periods
(`Q4 = FY − 9mo`, `Q3 = 9mo − H1`), accepting a derivation only when the residual period
is itself quarter-length. Every input obeys `filed <= D`.

Because this module could be wrong in ways that still produce plausible numbers, it is
checked against the independently filed annual figure at fiscal year ends — the one place
the two routes must agree:

| check | value |
|---|---|
| fiscal-year cross-checks | 2,351 across 95 names |
| median \|TTM−annual\|/annual | **0.00000** |
| p95 | 0.03744 |
| within 1% | **91.2%** (gate: ≥90%) |

Gate passed → proceeded. Had it failed, the milestone would have aborted: a negative
result from an unvalidated stitcher is an artifact, not evidence.

### Results

Same universe, same snapshots, same forward returns, same window-based half split — so any
change is attributable to **resolution** and nothing else. 6 hypotheses (3 components × 2
horizons); bar = |t| ≥ 3 **and** same sign both halves **and** positive OOS quintile spread.

| component | horizon | annual IC | **qtr-TTM IC** | qtr t | H1 | H2 | OOS Q5−Q1 | verdict |
|---|---|---|---|---|---|---|---|---|
| rule_of_40 | 6mo | +0.0066 | −0.0038 | −0.33 | +0.0443 | −0.0526 | −1.54% | not supported |
| rule_of_40 | 12mo | +0.0017 | −0.0149 | −1.49 | +0.0396 | −0.0703 | −5.58% | not supported |
| fcf_margin | 6mo | +0.0125 | +0.0084 | +1.38 | +0.0154 | +0.0012 | −0.32% | not supported |
| fcf_margin | 12mo | +0.0046 | +0.0026 | +0.49 | +0.0096 | −0.0045 | −2.76% | not supported |
| earnings_quality | 6mo | −0.0044 | −0.0051 | −0.75 | +0.0155 | −0.0261 | −3.42% | not supported |
| earnings_quality | 12mo | −0.0143 | −0.0152 | −2.27 | +0.0189 | −0.0498 | −8.92% | not supported |
| **valuation** *(control)* | 6mo | +0.0380 | **+0.0234** | **+3.95** | +0.0064 | +0.0408 | **+1.31%** | control holds |
| **valuation** *(control)* | 12mo | +0.0551 | **+0.0357** | **+7.27** | +0.0100 | +0.0617 | **+2.95%** | control holds |

### Why the negative is trustworthy

Valuation was carried as a **control**, and it is the reason this result can be believed.
If the quarterly pipeline were broken, the control would have degraded into noise along
with everything else. Instead it clears the bar at both horizons (t +3.95 / +7.27, same
sign both halves, positive OOS spread). The plumbing works; the growth components have no
signal in it.

Note the control is *weaker* at quarterly resolution (+0.0380 → +0.0234 @6mo). That is
expected and is itself informative — quarterly EV/Revenue is noisier than the annual
figure — and it means the June annual Valuation number is not an artifact of coarseness
either.

**KILL CONDITION MET.** No growth component earns SUPPORTED. Per the brief,
`rule_of_40`, `fcf_margin` and `earnings_quality` are **dropped permanently from Lane 1
scope**. The June flatness was **not** a resolution artifact — giving these components 4×
the update frequency made them slightly *worse*, not better. June's gated follow-up #1 is
now closed with a clean negative.

---

## MILESTONE C — survivorship bounding — **KILL CONDITION MET (assumption-dependent; escalating)**

### ⚠️ Correction: the "46 delisted names" are not 46 delisted names

The brief states *"The June run excluded ~46 delisted names (~10 pct) for lack of prices"*,
and June's own report calls them "the delisted set". Checked against the manifest:

| | count | share of 473 |
|---|---|---|
| missing a price file | 46 | 9.7% |
| **of which flagged `delisted_seed`** | **19** | **4.0%** |
| unpriced but never flagged delisted | 27 | 5.7% |

The 27 include **WBA, K, MMC, IPG, JNPR, HES, MRO, DFS, PARA, SWN, THS, SJW, CMA** — names
that traded normally through most or all of the window. The set also contains plain ticker
artifacts: **`FISV`→`FI`** (the old Fiserv ticker HAS prices, the new one does not — a
rename counted twice), **`SQ`** (renamed XYZ), **`TMK`** (renamed GL), **`CARVANA`** (should
be CVNA), and **`SWAPA`** (not a ticker).

So roughly **half of the "survivorship gap" is a gather gap** — recoverable by re-running
the June gather with corrected ticker forms, no paid data required. The true survivorship
exposure is **4.0%, not 9.7%**.

Attempting to classify the 46 by exit type from the corpus was not possible: only **1 of 46**
has a `submissions.json`, so the corpus offers no evidence about how these names exited. I
therefore make **no claim** about acquisition-vs-bankruptcy composition — it is unknown
from the data at hand, and asserting it would be exactly the kind of confident-but-
unverified premise §9 exists to catch.

### Free-source probe (permitted by the brief; no bulk re-gather)

5 delisted names probed, 2s apart, real UA `Kelton Shockey keltonshockey@mac.com`. All
returned **HTTP 200 with an HTML anti-bot page** — June's finding still holds, and it is
the same "200-with-HTML counted as success" trap that produced the June garbage gather.
The content-validation gate flagged them correctly. **No bulk gather attempted** (brief's
escalation rule).

### The bracket

Phantom rows for the missing names are injected into each cross-section and quintiles
re-cut on the augmented set. Two assumptions must be made, and **both** are varied rather
than chosen — the return assumption the brief specified, and the *placement* assumption it
did not:

**A. True survivorship exposure (19 names, 4.0%)**

| scenario | 6mo OOS | 12mo OOS |
|---|---|---|
| (iii) exclusion as today — June baseline | +2.49% | **+5.95%** |
| (ii) median return, even across quintiles | +2.45% | +5.71% |
| (ii) median return, all in Q5 | +2.09% | +4.73% |
| (i) −100%, even across quintiles | +0.53% | **+3.71%** |
| (i) −100%, **all in Q5** — pessimistic bound | −17.88% | **−15.90%** |

**B. All missing prices (46, 9.7%) — bounds gather failure too**

| scenario | 6mo OOS | 12mo OOS |
|---|---|---|
| (i) −100%, even across quintiles | −1.72% | +1.29% |
| (i) −100%, all in Q5 — pessimistic bound | −43.99% | −43.79% |

### The kill condition fires on an assumption the brief did not specify

The brief's kill condition is *"if the pessimistic bound takes the 12mo quintile spread to
≤ 0"*. It specifies the **return** assumption (−100%) but is silent on **placement**, and
placement is what decides the answer:

- −100% with names spread evenly across quintiles → **+3.71%**, premium survives
- −100% with every name forced into Q5 → **−15.90%**, kill condition met

Forcing all delisted names into Q5 asserts that the strategy bought every one of them.
That is unknowable: we have no price for these names, therefore no `ev_revenue`, therefore
no Valuation score, therefore no basis to place them in any quintile. The adverse placement
is not a conservative reading of the data — it is an additional assumption stacked on top
of the one the brief specified, and it is the one doing all the work.

**Per the brief and the session instruction, I am STOPPING before Milestone D and
escalating rather than picking the assumption that suits the thesis.**

### Self-correction during this milestone

The first implementation spread phantoms evenly across the **score range** rather than
across **ranks**. Valuation scores round to 0.1 and cluster heavily, so evenly-spaced
score *values* landed disproportionately in the sparse low-score tail and concentrated the
phantoms in Q1 — which *inflated* the reported spread to **+15.34% @12mo** where the honest
figure is **+3.71%**. Caught by noticing that a "pessimistic" scenario had improved the
result, which should never happen. Fixed to distribute by rank; the table above is post-fix.

---

## ⚠️ CORRECTION to Milestone C — the "27 gather failures" claim was WRONG

Kelton authorised recovering prices for the 27 supposedly mis-flagged names. The attempt
was made and it **refuted the hypothesis that motivated it.** Recording this prominently
because the earlier section of this document argued the opposite, and the earlier argument
was mine, not the data's.

**What I claimed:** only 19 of the 46 were genuinely delisted; the other 27 (WBA, K, MMC,
IPG, JNPR, HES, MRO, DFS, CMA, SJW, ZEUS …) were gather failures for names that traded
normally, so the survivorship exposure was 4.0%, not 9.7%.

**What the machine says**, from three sources:

| source | result |
|---|---|
| Yahoo chart API | HTTP 404 *"No data found, symbol may be delisted"* for every probed name, across `query1`/`query2`, lowercase, and exchange-suffixed variants |
| Yahoo controls | **8/8** corpus names (AAPL, AAL, A, AA, JNJ, KO, PG, XOM) return HTTP 200 — so this is **not** an IP block, not rate limiting, and not transient (re-tested) |
| SEC `company_tickers` | **45 of the 46** are ABSENT from SEC's active-registrant ticker map, while **424 of 427 (99.3%)** priced names are PRESENT |

That separation is far too clean to be coincidence, and two independent authorities agree.
**The `delisted_seed` list was simply incomplete** — it flagged 20 of roughly 46 actual
exits. The names I asserted "traded normally" were an inference from my own recollection of
the tickers, not evidence, and the evidence contradicts it.

**Consequences:**

1. **The true survivorship exposure is the full 9.7%**, not 4.0%. Scenario **B** is the one
   to read; scenario A understates.
2. **Recovery is not possible** from any free source available here. This is not a fixable
   data gap, so my recommendation (2) — re-gather, shrink the unknown — is **withdrawn**.
   The only route to these prices is a paid archive (CRSP/Sharadar), which the brief
   excludes.
3. **The picture is worse than first reported, not better.** At the correct 9.7% denominator
   the −100%/even-placement 12mo bound falls to **+1.29%** (from +3.71% at 4.0%) and the
   6mo bound is **negative at −1.72%**.

Corrected bracket, at the SEC-confirmed 9.7% exposure:

| scenario | 6mo OOS | 12mo OOS |
|---|---|---|
| (iii) exclusion as today — June baseline | +2.49% | +5.95% |
| (ii) median return, even across quintiles | +2.33% | +5.45% |
| (ii) median return, all in Q5 | +1.57% | +3.29% |
| (i) −100%, even across quintiles | **−1.72%** | **+1.29%** |
| (i) −100%, all in Q5 — pessimistic bound | −43.99% | **−43.79%** |

The kill condition still turns on the placement assumption, but the margin under neutral
placement is now thin (+1.29% @12mo) and already negative at 6mo. June's caveat that
+5.9% is "likely an upper bound" is confirmed and quantified: the honest 12mo range is
roughly **+1.3% to +5.9%** under defensible assumptions, collapsing to −43.8% only under
the maximally adverse placement that the data cannot rule in or out.

**Revised recommendation:** treat Lane 1's Valuation premium as **real but materially
smaller than the June headline, and not established beyond survivorship doubt**. The
remaining ways to settle it are (a) a paid delisted-price archive, or (b) accepting the
neutral-placement reading and proceeding to Milestone D with the +1.3%–+5.9% bracket
stated as a standing caveat on anything Lane 1 produces. I do not recommend (b) silently.

---

## MILESTONE D — NOT RUN (blocked by Milestone C's kill condition)

Milestone C's kill condition fires under adverse placement, and the brief directs a stop
before D in that case. No Chen-Zimmermann predictor list has been pre-committed and **no
forward returns have been computed for any candidate predictor** — which preserves the
mini-pre-registration discipline intact for whenever D is authorised. Nothing has been
looked at that would contaminate it.

## Status of the Lane 1 thesis, stated honestly

- **Valuation survives every test run so far.** It reproduced June exactly, it clears the
  bar at quarterly-TTM as a control (t +3.95 / +7.27, positive OOS spreads), and it stays
  positive under survivorship bounds that use neutral placement (+3.71% @12mo at −100%).
- **The growth components are closed.** Milestone B's negative is clean, validated, and
  permanent per the brief.
- **The survivorship question is not settled**, and it is now clear that a meaningful part
  of it is a *fixable data gap* rather than an inferential limit. Recovering prices for the
  27 mis-flagged names — several of which are simple ticker renames — would shrink the
  unknown from 9.7% to ~4.0% of the universe and materially tighten the bracket.

## Verification summary

| Gate | Result |
|---|---|
| Ark check (hard gate, first action) | ✅ both files present on NAS |
| Corpus audit vs June | ✅ 427 / 422 / 473 / 46 / 10,400 — unchanged |
| Milestone A reproduction | ✅ all 12 assertions inside tolerance |
| Tests | ✅ 26 passed (`api/tests/test_lane1_pit.py`) |
| Corpus read-only | ✅ AST-enforced by test; no file under `~/lt-recon-data` modified today |
| Python version | ✅ 3.11.15 (not 3.9, not 3.14) |
| Outbound fetches | ✅ 5 requests total, 2s apart, real UA with contact email |
| Persistent changes to mill | ✅ none beyond `~/.venvs/lane1`, `~/.local/share/uv/python`, and files in the output dirs. No listener, no service, no launchd job, no sudo |

## Anti-stranding — NAS transfers confirmed

```
rsync -av --rsync-path=/usr/bin/rsync /Users/mill/mill-local-edits/lane1/ \
      kshockey@192.168.1.173:/volume1/ai-stack/backups/ark/lane1-20260805/
```

| when | files |
|---|---|
| after Milestone A | 3 (`RESULT…md`, `reproduce_june.json`, dir) — *"created directory …/lane1-20260805"* |
| after Milestones B + C | 5 (adds `milestone_b.json`, `milestone_c.json`, `feat-r3-lane1-pit.bundle`) |

Nothing produced in this session exists only on mill.

## Handoff — laptop-side commands for Kelton

mill cannot push. The branch is committed locally on mill (2 commits on `feat/r3-lane1-pit`
off `e335637`) and bundled. Run these **on the laptop**:

```
cd /Users/kshockey/cyberscreener
scp mill@192.168.1.197:/Users/mill/mill-local-edits/lane1/feat-r3-lane1-pit.bundle /tmp/
```

```
cd /Users/kshockey/cyberscreener
git bundle verify /tmp/feat-r3-lane1-pit.bundle
git fetch /tmp/feat-r3-lane1-pit.bundle feat/r3-lane1-pit:feat/r3-lane1-pit
git log --oneline e335637..feat/r3-lane1-pit
```

```
cd /Users/kshockey/cyberscreener
git push github feat/r3-lane1-pit
```

```
cd /Users/kshockey/cyberscreener
gh pr create --repo keltonshockey/cyberscreener --draft --base main \
  --head feat/r3-lane1-pit \
  --title "feat(r3-lane1): PIT reconstruction harness + quarterly-TTM and survivorship follow-ups"
```

Collect the RESULT doc into the kb:

```
scp mill@192.168.1.197:/Users/mill/mill-local-edits/lane1/RESULT_R3_LANE1_2026-08-05.md \
  "/Users/kshockey/Library/CloudStorage/SynologyDrive-Notes/projects-kb/projects/cyberscreener/code-sessions/results/"
```

Note: `ssh mill@100.69.49.8` currently fails (`~/.ssh/config` maps `Host mill … 100.69.49.8`
to `HostName mill`, which is circular). The LAN address above works. Worth fixing that
config entry — the tailnet path is the one that would matter off-LAN.

## Decision needed before Milestone D

Milestone C's kill fires **only** under the adverse-placement assumption. Three ways forward:

1. **Treat the kill as binding** — Lane 1 stops here; Valuation is not established beyond
   the June result and no composite is proposed.
2. **Re-run the gather for the 27 mis-flagged names** (free sources, corrected ticker
   forms), shrinking the unknown to ~4.0% and re-bounding. This is the only option that
   *reduces* the assumption rather than choosing between assumptions.
3. **Rule that neutral placement is the intended reading** of the brief's pessimistic bound
   (+3.71% @12mo, premium survives) and authorise Milestone D.

My recommendation is **(2)**, then re-evaluate. It is a bounded piece of work, it attacks
the actual source of uncertainty, and it avoids settling a live question with an assumption
chosen after seeing which way it points.

---

# MILESTONE D — PRE-REGISTRATION (committed BEFORE any predictor return was computed)

**This section was written, committed to git, and rsynced to the NAS before
`predictors.py` existed.** Commit ordering is the proof: the pre-registration commit
precedes the implementation commit. No forward return has been computed for any predictor
below at the time of writing.

Authorised by Kelton after Milestone C, under the standing caveat established there.

## LANE 1 STANDING CAVEAT (attaches to every Lane 1 output from here on)

> The 12-month OOS Valuation quintile premium is **+1.3% to +5.9%**, not the +5.9% June
> headline. 9.7% of the universe exited and their prices are unrecoverable from free
> sources (SEC- and Yahoo-confirmed), so the lower bound reflects an adverse but
> unfalsifiable survivorship assumption. Anything built on Lane 1 inherits this range.

## Source verification

`SignalDoc.csv` fetched from the Chen-Zimmermann Open Source Asset Pricing repository
(331 rows: 212 Predictors, 114 Placebos, 5 Drop). Every candidate below was checked to
exist in that corpus, and its **sign is taken from CZ's documentation, not chosen by me**.

## The pre-committed predictor list — 10 predictors, FINAL

Selection rule, applied before looking at any return: (a) computable from our companyfacts
+ prices alone, (b) fundamental in nature (`Cat.Data = Accounting`, `Cat.Form = continuous`),
(c) intended to be low-turnover — annual/quarterly accounting inputs, not price-reversal
signals. Turnover is **measured** (below), not assumed.

| # | CZ acronym | CZ sign | CZ evidence | Our PIT computation (all `filed <= D`) |
|---|---|---|---|---|
| 1 | `BM` | +1 | 1_clear | StockholdersEquity / market cap |
| 2 | `EP` | +1 | 1_clear | NetIncomeLoss / market cap |
| 3 | `CF` | +1 | 1_clear | Operating cash flow / market cap |
| 4 | `GP` | +1 | 1_clear | GrossProfit / Assets |
| 5 | `OperProf` | +1 | 2_likely | OperatingIncomeLoss / StockholdersEquity |
| 6 | `Accruals` | −1 | 1_clear | (NetIncomeLoss − OCF) / Assets |
| 7 | `NOA` | −1 | 1_clear | (Assets − Cash − (Liabilities − Debt)) / lagged Assets |
| 8 | `AssetGrowth` | −1 | 1_clear | Assets / lagged Assets − 1 |
| 9 | `ShareIss1Y` | −1 | 1_clear | Shares / lagged Shares − 1 |
| 10 | `Investment` | −1 | 1_clear | Capex / Revenue |

`OperProf` is CZ `2_likely` rather than `1_clear`; it is retained but flagged, and its
verdict will be read with that in mind.

## Pre-committed orientation

Every predictor is oriented so that **higher = expected higher forward return**, by
multiplying the raw value by CZ's documented sign. Predictors 6–10 therefore enter as
their negative. **This orientation is fixed now and will not be revisited after seeing
results** — flipping a sign post hoc is how a null becomes a finding.

## Pre-committed evaluation

- Same panel, universe, snapshots (127 monthly, 2014-12..2025-06) and forward returns
  (6mo / 12mo) as Milestone A. Same window-based half split and 60/40 walk-forward.
- **Hypothesis count: 20** (10 predictors × 2 horizons). Bonferroni applies across all 20.
- **SUPPORTED requires ALL THREE** (PROMOTION_CRITERIA.md):
  1. |t| ≥ 3 at the horizon,
  2. same sign of mean IC in BOTH PIT sub-periods,
  3. positive OOS quintile spread (Q5−Q1) for the predictor alone.
- **Turnover measured**, not assumed: mean monthly one-sided rank turnover. Any predictor
  exceeding **50%** one-sided monthly is reported and **excluded from the composite** even
  if it clears the statistical bar (Novy-Marx–Velikov low-turnover constraint, per brief).
- **Composite: EQUAL-WEIGHT rank average of survivors + Valuation.** No weight search, no
  optimiser, no IC-magnitude weighting — that is the documented June overfitting trap.
- **If zero predictors survive, the composite is Valuation alone, and that is the honest
  output.** This outcome is pre-accepted as a valid result, not a failure.

## Pre-committed falsifier

If the survivors' equal-weight composite does not beat Valuation alone on OOS quintile
spread at 12mo, the added predictors earn no place and the composite spec ships as
Valuation-only.


---

# MILESTONE D — RESULTS (executed against the pre-registration above)

Panel: 422 names with both prices and companyfacts, median 404 names/snapshot, same 127
monthly snapshots. **20 hypotheses** exactly as registered.

## Full sweep

| predictor | horizon | mean IC | t | H1 | H2 | OOS Q5−Q1 | turnover | verdict |
|---|---|---|---|---|---|---|---|---|
| BM | 6mo | −0.0057 | −0.41 | −0.0671 | +0.0568 | +2.72% | 3.6% | not supported |
| BM | 12mo | −0.0033 | −0.22 | −0.1010 | +0.0960 | +8.04% | 3.6% | not supported |
| EP | 6mo | +0.0026 | +0.25 | −0.0504 | +0.0565 | −0.73% | 5.6% | not supported |
| EP | 12mo | −0.0017 | −0.17 | −0.0539 | +0.0514 | −4.88% | 5.6% | not supported |
| CF | 6mo | +0.0107 | +0.73 | −0.0676 | +0.0902 | +4.11% | 5.2% | not supported |
| CF | 12mo | +0.0193 | +1.26 | −0.0902 | +0.1306 | +7.28% | 5.2% | not supported |
| GP | 6mo | +0.0147 | +1.23 | +0.0512 | −0.0223 | −3.19% | 2.5% | not supported |
| GP | 12mo | +0.0198 | +1.62 | +0.0767 | −0.0380 | −10.68% | 2.5% | not supported |
| OperProf | 6mo | +0.0106 | +1.12 | −0.0222 | +0.0439 | +0.62% | 3.0% | not supported |
| OperProf | 12mo | +0.0062 | +0.68 | −0.0172 | +0.0300 | −3.75% | 3.0% | not supported |
| Accruals | 6mo | −0.0025 | −0.34 | +0.0002 | −0.0053 | +0.93% | 4.3% | not supported |
| Accruals | 12mo | +0.0087 | +1.48 | +0.0051 | +0.0124 | +3.67% | 4.3% | not supported |
| **NOA** | 6mo | **+0.0433** | **+3.35** | +0.0183 | +0.0687 | **+2.06%** | 3.2% | **SUPPORTED** |
| **NOA** | 12mo | **+0.0621** | **+5.54** | +0.0419 | +0.0827 | **+3.54%** | 3.2% | **SUPPORTED** |
| AssetGrowth | 6mo | −0.0292 | −2.75 | −0.0725 | +0.0149 | +0.41% | 8.5% | not supported |
| AssetGrowth | 12mo | −0.0165 | −1.64 | −0.0723 | +0.0401 | +1.61% | 8.5% | not supported |
| ShareIss1Y | 6mo | +0.0045 | +0.40 | −0.0399 | +0.0495 | −1.19% | 5.2% | not supported |
| ShareIss1Y | 12mo | +0.0237 | +2.32 | −0.0191 | +0.0671 | −2.67% | 5.2% | not supported |
| **Investment** | 6mo | **+0.0540** | **+5.90** | +0.0582 | +0.0498 | **+1.60%** | 1.2% | **SUPPORTED** |
| **Investment** | 12mo | **+0.0602** | **+6.70** | +0.0737 | +0.0465 | **+0.90%** | 1.2% | **SUPPORTED** |

**Turnover: every predictor came in between 1.2% and 8.5% one-sided monthly**, far inside
the 50% cap. The low-turnover screen was therefore never binding — the selection rule
(annual/quarterly accounting inputs only) had already done that work. No predictor was
excluded on turnover grounds.

**8 of 10 fail, and mostly for the same reason as June's growth components:** BM, EP, CF,
OperProf and ShareIss1Y all flip sign between the two PIT sub-periods (H1 negative, H2
positive) — regime artifacts, exactly the pattern PROMOTION_CRITERIA.md's sign-consistency
rule exists to reject. Note BM@12mo would have looked like a **+8.04% OOS quintile spread**
if judged on spread alone; its sub-period signs are −0.1010 → +0.0960. That is the single
clearest illustration in this study of why the three-part bar is not redundant.

## The pre-committed falsifier fires

| horizon | Valuation alone | Composite (Investment + NOA + Valuation) | |
|---|---|---|---|
| 6mo | +2.48% | **+3.28%** | composite wins |
| **12mo** | **+5.93%** | +4.75% | **composite loses** |

The registration fixed the falsifier at **12mo**. The composite loses there, so:

> **THE LANE 1 COMPOSITE SPEC SHIPS AS VALUATION-ONLY.**

The 6mo win is recorded and is **not** grounds to override it. The horizon was fixed in
advance specifically so that this choice could not be made after seeing which way it went.
`Investment` and `NOA` are nominated for future work — both are sign-consistent, both clear
the Bonferroni-adjusted bar, both are very low turnover — but they do not enter the
composite on this evidence.

An implementation note worth recording: the first cut of `milestone_d.py` declared victory
whenever the composite won at *any* horizon, which would have shipped the composite on the
6mo result. That is a misreading of the registration, and it was corrected to test 12mo
specifically before the verdict was accepted.

## Deliverable

`LANE1_COMPOSITE_SPEC.md` — candidate spec, Valuation-only, carrying the Milestone C
standing caveat. Promotion still runs through `PROMOTION_CRITERIA.md`.

Note this **confirms the current live configuration rather than changing it**: LT baseline
membership is already Valuation-100 (`weights_baseline.json`, v2-baseline). Lane 1's decade
PIT programme has now tested 6 LT components at two resolutions and 10 CZ predictors — 26
component-horizon hypotheses in total — and has not found anything that earns a place
alongside Valuation.

---

# SESSION SUMMARY

| Milestone | Outcome |
|---|---|
| **Ark gate** | ✅ both files present on NAS — proceeded |
| **A** — corpus audit + port + reproduction | ✅ **PASSED**, all 12 assertions inside tolerance |
| **B** — quarterly-TTM re-test | ⛔ **KILL MET** — growth components dropped permanently |
| **C** — survivorship bounding | ⛔ **KILL MET** under adverse placement; escalated; ran under caveat |
| **D** — CZ predictor sweep | ✅ ran; **pre-committed falsifier fired** → Valuation-only |

**Net scientific content: three negatives and one confirmation.** The growth components are
closed. The survivorship premium is materially smaller than the June headline and cannot be
resolved without paid data. Eight of ten CZ predictors fail on sub-period sign consistency.
Valuation survives everything, which is what the live baseline already assumes.

## Corrections made during this session

1. Session was not on mill (brief said it was) — escalated, drove mill over SSH.
2. mill had **no Python 3.11** — the only two interpreters present were the two the brief
   forbids. Provisioned 3.11.15 via `uv`, user-space.
3. `~/.ssh/config` tailnet alias for mill is circular; only the LAN path works.
4. **Self-correction:** claimed 27 of the 46 missing names were recoverable gather
   failures. Attempted the recovery Kelton authorised; SEC + Yahoo both refuted it. All 46
   are genuine exits, exposure is 9.7% not 4.0%, and the picture is worse than I first
   reported. Recommendation withdrawn.
5. **Self-correction:** Milestone C's phantom placement initially spread by score *value*
   rather than by *rank*, inflating a spread to +15.34% where the honest figure is +3.71%.
6. **Self-correction:** Milestone D's verdict logic initially accepted a win at any
   horizon; corrected to the pre-registered 12mo test, which reverses the outcome.
