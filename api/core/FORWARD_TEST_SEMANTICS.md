# Forward-Test Closure Semantics (pre-registered 2026-06-09)

These definitions were written and committed BEFORE computing any new play
outcomes or gate metrics, to prevent fitting the rules to the results.

**Disclosure:** during read-only diagnosis on 2026-06-09 the 11 legacy-closed
AAPL iron-condor rows (settled at 310.26, the 2026-06-04 close) were visible,
including the fact that 310.26 lies inside their short strikes. The payoff
formulas below are standard option-settlement identities, not parameters, and
nothing else in this document was chosen after seeing an outcome. As of
2026-06-09 zero open plays are past expiry, so no new outcome was computable
when this was written.

## 1. When a play closes

- A play is **due** when `today (UTC date) > expiry`. Strictly after — never on
  expiry day (the old `expiry <= today` closed at 16:00 UTC on expiry day,
  before the expiry session's close existed).
- There are no exit signals in this system; every play is held to expiry.
  Outcome = settlement intrinsic value vs as-filed cost.

## 2. Settlement price

- `settlement = close_price` from the `prices` table for the play's ticker at
  the **latest date d with `expiry - 3 days <= d <= expiry`**.
- Prices dated **after** expiry are never used (no look-ahead past the
  contract's life). The 3-day reach-back covers holidays/scan gaps (e.g.
  2026-06-05 is absent from `prices`; a 06-05 expiry settles on the 06-04
  close, and `settlement_date` records that).
- If no such price exists:
  - due for **≤ 10 calendar days** → play stays `open` (data may still arrive;
    re-checked on every run).
  - due for **> 10 calendar days** → `status = 'unresolvable'`. Outcomes are
    never guessed.

## 3. Per-strategy realized outcome

Inputs come from the play row as filed at entry: `strategy`, `strike` (text:
`K`, `K1/K2`, or `Pl/Ps/Cs/Cl`), `entry_price`, `max_loss`, `notes`.
`S` = settlement price.

| Strategy | Cost basis | Settlement value | Return |
|---|---|---|---|
| Long Call | `entry_price` = premium/share | `max(S - K, 0)` | `(value - cost) / cost` |
| Long Put | `entry_price` = premium/share | `max(K - S, 0)` | `(value - cost) / cost` |
| Bull Call Spread `K1/K2` | `entry_price` = net debit | `clamp(S - K1, 0, K2 - K1)` | `(value - cost) / cost` |
| Bear Put Spread `K1/K2` (K1 > K2) | net debit | `clamp(K1 - S, 0, K1 - K2)` | `(value - cost) / cost` |
| Straddle `K` | `entry_price` = total premium | `abs(S - K)` | `(value - cost) / cost` |
| Iron Condor `Pl/Ps/Cs/Cl` | credit `c` (below); risk = `width - c`, `width = max(Ps-Pl, Cl-Cs)` | loss leg `L = min(max(0, Ps - S, S - Cs), width_breached)` | `(c - L) / (width - c)` — return on max risk |

- **Debit-strategy validity:** cost must satisfy `0 < cost` (and `cost <
  width` for spreads). Early rows that filed the underlying price in
  `entry_price` (pre-fix condors, and any spread where `entry_price >= K2-K1`)
  fail this check → rescue below or `unresolvable`.
- **Iron-condor credit `c`:** use `entry_price` if `0 < entry_price < width`;
  else parse `Collect $X.XX` from `notes`; else `c` is unknown.
- **Unknown-credit condors are still decidable in two regions:**
  - `Ps < S < Cs` → win, `realized_pnl = +c` unknown → `win=1, outcome='win'`,
    `realized_return = NULL`.
  - `S <= Pl` or `S >= Cl` (beyond a wing) → return on risk = `-(width-c)/(width-c)`
    = **-100 %** regardless of `c` → `win=0, realized_return = -1.0`.
  - Between a short strike and its wing → sign depends on `c` → `unresolvable`
    if `c` unknown.
- Unparseable strikes, or a missing/invalid cost basis with no notes rescue →
  `status='unresolvable'`, with the reason recorded. Never a fabricated number.

## 4. Win / EV / conviction (gate metrics)

- **Win** := `realized_return > 0` strictly. As-filed mid prices; no
  commission or slippage modeled (stated, not hidden).
- **Unit of analysis** := distinct `(ticker, strategy, strike, expiry)`,
  keeping the **earliest** logged row. The journal currently holds 216 rows
  but only 83 distinct plays (the pre-warm loop re-logs each play every scan).
  Duplicates are closed in the DB identically but excluded from metrics.
- **Win rate** = wins / (wins + losses) over distinct closed plays with a
  decided outcome. Unresolvable plays are reported as their own count, never
  in the denominator silently.
- **EV (the ≥ 1.5× gate)** = profit factor = `sum(positive realized_return) /
  |sum(negative realized_return)|` over distinct closed plays. Expectancy
  (mean realized_return) is reported alongside.
- **Conviction** = `0.6 * opt_score + 0.4 * lt_score` **as of entry**. The
  journal filed 0 for both scores on every row (logging bug); conviction is
  backfilled from the `scores` table using the latest scan at or before
  `generated_at` for the ticker — contemporaneous data only, no look-ahead.
  Gate bucket: conviction ≥ 65. Reported buckets: <55, 55–65, 65–75, ≥75.

## 5. Look-ahead discipline

- Entry fields: from the entry row, plus `scores` rows at scan time ≤
  `generated_at` (conviction backfill only).
- Outcome fields: only `prices` rows in `[expiry - 3d, expiry]`.
- Closure runs strictly after expiry day.

## 6. Idempotency / statuses

- `status` ∈ `open` → (`closed` | `unresolvable`). The closure job only ever
  touches `status='open'` rows; closed and unresolvable rows are never
  re-closed.
- `close_method` records the rule version (`settlement_v2`). The 11 rows
  closed by the legacy directional ×4 heuristic (`close_method IS NULL`) are
  recomputed once by the supervised backfill with
  `close_method='settlement_v2_migrated'`; their legacy `pnl_pct` is preserved
  in `notes` for audit.
