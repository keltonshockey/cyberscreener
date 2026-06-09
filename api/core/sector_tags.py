"""
Sector taxonomy — multi-tag, maintained in the data layer (UI_OVERHAUL_PLAN §4).

The scores row carries a single coarse ``sector`` (cyber/energy/defense/broad)
plus a free-text ``subsector``. The UI wants first-class, multi-tag chips
(NVDA = AI + Semis + Tech) over an expanded set. This module is the authoritative
source for those tags — the curated map previously lived client-side in
``frontend/src/utils/sectors.js`` and is promoted here so the chips are real, not
inferred per-request in the browser.

``tags_for(ticker, sector, subsector)`` is called at scan time; the result is
persisted as the ``sector_tags`` JSON column and flows out via /scores/latest.
"""

# Expanded taxonomy — order = chip display order. Keep in sync with the frontend
# SECTOR_TAGS list (the frontend now consumes server tags but still orders chips).
SECTOR_TAGS = [
    "AI", "Semis", "Cyber", "Energy", "Nuclear", "Defense",
    "Fintech", "Space", "Quantum", "Biotech",
    "Tech", "Health", "Financials", "Consumer", "Industrials", "REITs",
]

# Curated multi-tag overlay for well-known names (highest priority).
TICKER_TAGS = {
    "NVDA": ["AI", "Semis", "Tech"], "AMD": ["AI", "Semis", "Tech"], "AVGO": ["AI", "Semis", "Tech"],
    "TSM": ["Semis", "Tech"], "MU": ["Semis", "Tech"], "ASML": ["Semis", "Tech"], "INTC": ["Semis", "Tech"],
    "ARM": ["AI", "Semis", "Tech"], "MRVL": ["AI", "Semis", "Tech"], "SMCI": ["AI", "Semis", "Tech"],
    "PLTR": ["AI", "Defense", "Tech"], "MSFT": ["AI", "Tech"], "GOOGL": ["AI", "Tech"], "META": ["AI", "Tech"],
    "AMZN": ["AI", "Tech", "Consumer"], "CRWD": ["Cyber", "AI", "Tech"], "PANW": ["Cyber", "AI", "Tech"],
    "ZS": ["Cyber", "Tech"], "FTNT": ["Cyber", "Tech"], "OKTA": ["Cyber", "Tech"], "NET": ["Cyber", "Tech"],
    "S": ["Cyber", "AI", "Tech"], "CYBR": ["Cyber", "Tech"], "GEN": ["Cyber", "AI"], "DDOG": ["Cyber", "AI", "Tech"],
    "CEG": ["Nuclear", "Energy"], "CCJ": ["Nuclear", "Energy"], "VST": ["Nuclear", "Energy"], "NEE": ["Energy"],
    "FSLR": ["Energy"], "ENPH": ["Energy"], "EQIX": ["REITs", "Tech"], "DLR": ["REITs", "Tech"],
    "LMT": ["Defense"], "RTX": ["Defense"], "NOC": ["Defense"], "GD": ["Defense"], "AVAV": ["Defense", "Space"],
    "KTOS": ["Defense", "Space"], "RKLB": ["Space", "Defense"], "LUNR": ["Space"], "ASTS": ["Space"],
    "V": ["Fintech", "Financials"], "MA": ["Fintech", "Financials"], "PYPL": ["Fintech", "Tech"],
    "SQ": ["Fintech", "Tech"], "COIN": ["Fintech"], "HOOD": ["Fintech"], "SOFI": ["Fintech", "Financials"],
    "IONQ": ["Quantum", "Tech"], "RGTI": ["Quantum", "Tech"], "QBTS": ["Quantum", "Tech"],
    "LLY": ["Health", "Biotech"], "MRNA": ["Biotech", "Health"], "CRSP": ["Biotech", "Health"],
    "VRTX": ["Biotech", "Health"], "REGN": ["Biotech", "Health"],
}

# Fallback: coarse subsector → tag(s).
SUBSECTOR_TAGS = {
    "Technology": ["Tech"],
    "Health Care": ["Health"],
    "Financials": ["Financials"],
    "Consumer Disc": ["Consumer"],
    "Consumer Staples": ["Consumer"],
    "Industrials": ["Industrials"],
    "Real Estate": ["REITs"],
    "Energy": ["Energy"],
}


def tags_for(ticker, sector=None, subsector=None):
    """Return the de-duplicated, order-preserving tag list for a ticker.

    Curated overlay wins; otherwise derive from the coarse sector/subsector.
    Always returns at least one tag (defaults to ["Tech"]).
    """
    curated = TICKER_TAGS.get((ticker or "").upper())
    if curated:
        return list(curated)

    out = []
    if sector == "cyber":
        out += ["Cyber", "Tech"]
    elif sector == "defense":
        out += ["Defense"]
    elif sector == "energy":
        out += ["Energy"]
        if subsector and any(k in subsector.lower() for k in ("uran", "nuclear")):
            out += ["Nuclear"]
    elif sector == "broad":
        out += SUBSECTOR_TAGS.get(subsector, [])

    # de-dupe preserving order
    seen, deduped = set(), []
    for tag in out:
        if tag not in seen:
            seen.add(tag)
            deduped.append(tag)
    return deduped or ["Tech"]
