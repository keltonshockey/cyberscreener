"""
CyberScreener Universe v2 — Multi-sector stock universe.
Includes curated cyber/energy/defense sectors plus broad S&P 500 + Nasdaq 100.
"""
from core.broad_universe import BROAD_UNIVERSE

CYBER_UNIVERSE = {
    "Platform Giants": ["CRWD", "PANW", "FTNT", "ZS", "CSCO"],
    "Identity & Access": ["OKTA", "CYBR", "SAIL"],
    "Cloud & Network Security": ["NET", "AKAM", "CHKP", "QLYS", "TENB", "RPD", "FFIV"],
    "AI-Powered / Next-Gen": ["S", "DDOG", "MSFT", "GOOGL"],
    "Endpoint Detection": ["GEN"],
    "Threat Intel / IR": ["OTEX", "RDWR"],
    "Enterprise GRC": ["IBM"],
    "Network Hardware": ["NTCT", "ATEN"],
    "Data Security": ["VRNS", "VRNT"],
    "Gov / Defense Cyber": ["CACI", "LDOS", "SAIC", "BAH", "BBAI", "PLTR"],
    "Mid/Small Cap": ["TLS", "OSPN", "JAMF", "DT", "ESTC", "RBBN"],
    "ETF Benchmarks": ["HACK"],  # CIBR and BUG removed — no fundamentals/options data in yfinance
}

ENERGY_UNIVERSE = {
    "Nuclear Power": ["CCJ", "CEG", "VST", "NRG", "ETR"],
    "Power Generation": ["GEV"],
    "Solar / Clean Energy": ["FSLR", "AES", "NEE"],
    "Data Center REITs": ["EQIX", "DLR", "AMT"],
    # URA and URNM removed — ETFs have no options chains or fundamentals data in yfinance
}

DEFENSE_UNIVERSE = {
    "Drones / Autonomy": ["AVAV", "KTOS"],
    "Prime Defense": ["LHX", "NOC", "RTX", "GD", "LMT"],
    "Gov IT / Cyber": ["BAH", "SAIC", "CACI", "LDOS"],
    "Space": ["LUNR", "RDW"],
}

_TICKER_META = {}

for subsector, tickers in CYBER_UNIVERSE.items():
    for t in tickers:
        _TICKER_META[t] = {"sector": "cyber", "subsector": subsector, "scoring_profile": "saas"}

for subsector, tickers in ENERGY_UNIVERSE.items():
    for t in tickers:
        profile = "reit" if subsector == "Data Center REITs" else "energy"
        _TICKER_META[t] = {"sector": "energy", "subsector": subsector, "scoring_profile": profile}

for subsector, tickers in DEFENSE_UNIVERSE.items():
    for t in tickers:
        if t not in _TICKER_META:
            _TICKER_META[t] = {"sector": "defense", "subsector": subsector, "scoring_profile": "defense"}

_SECTOR_TO_PROFILE = {
    "Technology": "saas", "Communication": "saas", "Consumer Disc": "saas",
    "Health Care": "saas", "Financials": "financial", "Industrials": "defense",
    "Consumer Staples": "energy", "Materials": "defense",
    "Energy Broad": "energy", "Utilities": "energy", "Real Estate": "reit",
}
for _subsector, _tickers in BROAD_UNIVERSE.items():
    _profile = _SECTOR_TO_PROFILE.get(_subsector, "saas")
    for _t in _tickers:
        if _t not in _TICKER_META:
            _TICKER_META[_t] = {"sector": "broad", "subsector": _subsector, "scoring_profile": _profile}

SCORING_PROFILES = {
    "saas":      {"rule_of_40": 28, "valuation": 18, "fcf_margin": 18, "trend": 15, "earnings_quality": 11, "discount_momentum": 10},
    "energy":    {"rule_of_40": 10, "valuation": 22, "fcf_margin": 30, "trend": 15, "earnings_quality": 15, "discount_momentum":  8},
    "reit":      {"rule_of_40":  8, "valuation": 20, "fcf_margin": 35, "trend": 15, "earnings_quality": 15, "discount_momentum":  7},
    "defense":   {"rule_of_40": 12, "valuation": 20, "fcf_margin": 22, "trend": 15, "earnings_quality": 20, "discount_momentum": 11},
    "financial": {"rule_of_40":  5, "valuation": 30, "fcf_margin": 20, "trend": 15, "earnings_quality": 20, "discount_momentum": 10},
}

DEFAULT_PROFILE = "saas"

def get_all_tickers(sectors=None):
    if sectors is None:
        return sorted(list(_TICKER_META.keys()))
    return sorted([t for t, m in _TICKER_META.items() if m["sector"] in sectors])

def get_ticker_meta(ticker):
    return _TICKER_META.get(ticker.upper(), {"sector": "cyber", "subsector": "Unknown", "scoring_profile": DEFAULT_PROFILE})

def get_scoring_weights(ticker):
    meta = get_ticker_meta(ticker)
    profile = meta.get("scoring_profile", DEFAULT_PROFILE)
    return dict(SCORING_PROFILES.get(profile, SCORING_PROFILES[DEFAULT_PROFILE]))

def get_universe_by_sector():
    return {"cyber": CYBER_UNIVERSE, "energy": ENERGY_UNIVERSE, "defense": DEFENSE_UNIVERSE, "broad": BROAD_UNIVERSE}

def get_sector_summary():
    counts = {}
    for meta in _TICKER_META.values():
        s = meta["sector"]
        counts[s] = counts.get(s, 0) + 1
    return counts

ALL_TICKERS = get_all_tickers()
ALL_CYBER_TICKERS = get_all_tickers(["cyber"])
ALL_ENERGY_TICKERS = get_all_tickers(["energy"])
ALL_DEFENSE_TICKERS = get_all_tickers(["defense"])
ALL_BROAD_TICKERS = get_all_tickers(["broad"])
