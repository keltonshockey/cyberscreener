"""
Valuation Watchlist copy -- the ONE config source for the horizon and caveat
strings served by GET /watchlist/valuation.

The caveat is registered language: it states the evidence base (the +1.3% to
+5.9% survivorship-bounded range from the decade point-in-time backtest, R3
Lane 1) exactly as the research record supports it. The API serves it and the
frontend renders it verbatim; neither side hard-codes its own version, so the
words cannot drift from the evidence. test_watchlist_router.py pins the text
byte-for-byte -- edit here only with a matching test update and a reason.
"""

HORIZON = (
    "Monthly snapshot. The underlying signal operates on a 6-12 month "
    "horizon; intraday movement is deliberately not shown here."
)

CAVEAT = (
    "Survivorship caveat: the 12-month out-of-sample Valuation quintile "
    "premium is +1.3% to +5.9% under defensible assumptions; 9.7% of the "
    "historical universe exited the sample and their prices are unrecoverable "
    "from free sources. This range, not the point estimate, is the evidence "
    "base. Horizon: 6-12 months. This is an experimental research surface, "
    "not investment advice."
)


def copy_payload() -> dict:
    """The `copy` object embedded in the /watchlist/valuation response."""
    return {"horizon": HORIZON, "caveat": CAVEAT}
