"""
LT score distribution guard.

Regression test for the "everything scores in a narrow band" failure mode.
Scores a deterministic mock universe spanning weak -> elite fundamentals and
asserts the full 0-100 range is exercised: at least 10% of tickers below 50
AND at least 10% above 75. A reintroduced floor or a collapsed/compressed
distribution would break this.
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from core.scanner import score_long_term


def _row(**kw):
    """A scored-ticker row; defaults are neutral, override per archetype."""
    base = dict(
        price=100.0,
        revenue_growth_pct=10.0,
        operating_margin_pct=10.0,
        gross_margin_pct=50.0,
        ev_revenue=15.0,
        fcf_margin_pct=8.0,
        eps=4.0,
        pe_ratio=25.0,
        sma_20=98.0, sma_50=95.0, sma_200=90.0,   # mild uptrend
        pct_from_52w_high=-8.0,
        perf_3m=4.0, perf_1m=1.0,
    )
    base.update(kw)
    return base


def _mock_universe():
    rows = []

    # ── Elite (should land >75): high Rule-of-40, cheap-for-growth, FCF-rich,
    #    clean uptrend, profitable, near highs with momentum ──
    for i in range(12):
        rows.append(_row(
            revenue_growth_pct=35 + i, operating_margin_pct=28,
            gross_margin_pct=82, ev_revenue=6.0, fcf_margin_pct=30,
            eps=6.0, pe_ratio=28,
            sma_20=99, sma_50=96, sma_200=85, price=110,
            pct_from_52w_high=-2.0, perf_3m=18, perf_1m=5,
        ))

    # ── Mid (40-65): ordinary large-caps, fair valuation, modest growth ──
    for i in range(11):
        rows.append(_row(
            revenue_growth_pct=8, operating_margin_pct=12,
            gross_margin_pct=45, ev_revenue=14, fcf_margin_pct=9,
            eps=4.0, pe_ratio=22,
            sma_20=99, sma_50=98, sma_200=96, price=100,
            pct_from_52w_high=-10.0, perf_3m=2, perf_1m=0,
        ))

    # ── Weak / bad (should land <50): shrinking, cash-burning, expensive,
    #    in a downtrend, unprofitable ──
    for i in range(12):
        rows.append(_row(
            revenue_growth_pct=-8 - i, operating_margin_pct=-6,
            gross_margin_pct=22, ev_revenue=38, fcf_margin_pct=-15,
            eps=-1.5, pe_ratio=None,
            sma_20=96, sma_50=100, sma_200=108, price=90,  # below all SMAs
            pct_from_52w_high=-45.0, perf_3m=-20, perf_1m=-8,
        ))

    return rows


def test_lt_distribution_spans_full_range():
    scores = [score_long_term(r)[0] for r in _mock_universe()]
    n = len(scores)

    below_50 = sum(1 for s in scores if s < 50)
    above_75 = sum(1 for s in scores if s > 75)

    assert below_50 / n >= 0.10, (
        f"expected >=10% of tickers below 50, got {below_50}/{n} "
        f"({100*below_50/n:.0f}%). Distribution: min={min(scores):.1f} "
        f"max={max(scores):.1f}"
    )
    assert above_75 / n >= 0.10, (
        f"expected >=10% of tickers above 75, got {above_75}/{n} "
        f"({100*above_75/n:.0f}%). Distribution: min={min(scores):.1f} "
        f"max={max(scores):.1f}"
    )


def test_lt_has_no_floor():
    """A genuinely bad company must be able to score well below 60."""
    bad = _row(
        revenue_growth_pct=-15, operating_margin_pct=-10, gross_margin_pct=18,
        ev_revenue=45, fcf_margin_pct=-20, eps=-2.0, pe_ratio=None,
        sma_20=95, sma_50=101, sma_200=110, price=88,
        pct_from_52w_high=-50.0, perf_3m=-25, perf_1m=-10,
    )
    score = score_long_term(bad)[0]
    assert score < 40, f"bad company scored {score}; a 60-floor may have returned"
