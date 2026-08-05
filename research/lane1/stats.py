"""
Cross-sectional statistics, ported verbatim from the June engine.

Pure stdlib on purpose: the numbers must be identical to June's, and swapping in
scipy/pandas ranking would change tie handling. The component scores are rounded
to 0.1 by `score_component`, so ties are COMMON and their treatment is not a
detail — `rank()` assigns average ranks to ties, which is what June did.

t-stat caveat carried forward from RESULT_LT_RECONSTRUCTION §7.6 caveat 4:
monthly snapshots with 6/12-month forward returns overlap heavily, so per-
snapshot ICs are strongly autocorrelated and the effective sample is far below
N. The raw t is OVERSTATED. Judge by IC magnitude + sign-consistency across the
two halves, not by the literal t.
"""

from __future__ import annotations

import math

# A cross-section thinner than this is not a cross-section.
MIN_CROSS_SECTION = 30


def rank(xs: list[float]) -> list[float]:
    """Average ranks, ties shared — matches June's tie handling exactly."""
    order = sorted(range(len(xs)), key=lambda i: xs[i])
    r = [0.0] * len(xs)
    i = 0
    while i < len(xs):
        j = i
        while j + 1 < len(xs) and xs[order[j + 1]] == xs[order[i]]:
            j += 1
        avg = (i + j) / 2.0 + 1
        for k in range(i, j + 1):
            r[order[k]] = avg
        i = j + 1
    return r


def pearson(a: list[float], b: list[float]) -> float:
    n = len(a)
    ma, mb = sum(a) / n, sum(b) / n
    num = sum((a[i] - ma) * (b[i] - mb) for i in range(n))
    da = math.sqrt(sum((x - ma) ** 2 for x in a))
    db = math.sqrt(sum((x - mb) ** 2 for x in b))
    return num / (da * db) if da > 0 and db > 0 else 0.0


def spearman(a: list[float], b: list[float]) -> float | None:
    if len(a) < 3:
        return None
    return pearson(rank(a), rank(b))


def tstat(ics: list[float | None]) -> tuple[float, float, int]:
    """(mean IC, t, n) over the non-None daily ICs."""
    vals = [x for x in ics if x is not None]
    n = len(vals)
    if n < 3:
        return 0, 0, n
    m = sum(vals) / n
    sd = math.sqrt(sum((x - m) ** 2 for x in vals) / (n - 1))
    return m, (m * math.sqrt(n) / sd if sd > 0 else 0), n


def pooled_quintiles(per_snapshot: list[list[tuple[float, float]]]):
    """
    Pool bottom/top quintile forward returns across snapshots.

    Quintiles are cut WITHIN each snapshot (cross-sectionally) and only then
    pooled — cutting on the pooled distribution would rank a 2014 name against
    a 2024 name and turn a market-wide drift into fake cross-sectional edge.
    """
    q1r, q5r = [], []
    for rows in per_snapshot:
        if len(rows) < MIN_CROSS_SECTION:
            continue
        ordered = sorted(rows, key=lambda x: x[0])
        k = len(ordered) // 5
        if k == 0:
            continue
        q1r += [r for (_s, r) in ordered[:k]]
        q5r += [r for (_s, r) in ordered[-k:]]
    if not q1r or not q5r:
        return None
    q1 = sum(q1r) / len(q1r)
    q5 = sum(q5r) / len(q5r)
    return q5 - q1, q1, q5
