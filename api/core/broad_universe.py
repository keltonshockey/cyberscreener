"""
Broad Market Universe — S&P 500 + Nasdaq 100 tickers organized by GICS sector.
Imported by universe.py and merged into the global ticker registry.
Tickers already in CYBER/ENERGY/DEFENSE universes are silently skipped.
"""

BROAD_UNIVERSE = {
    "Technology": [
        "AAPL", "MSFT", "NVDA", "AVGO", "ORCL", "AMD", "QCOM", "TXN", "INTC", "MU",
        "AMAT", "LRCX", "KLAC", "ADI", "MCHP", "SNPS", "CDNS", "ANSS", "HPQ", "HPE",
        "ACN", "CTSH", "IT", "EPAM", "GDDY", "JNPR", "NTAP", "STX", "WDC", "NXPI",
        "ON", "SWKS", "QRVO", "MPWR", "GLW", "KEYS", "TRMB", "COHR", "FLEX", "JDSU",
        "CDW", "PCTY", "PAYC", "ROP", "PTC", "TDY", "TER", "ZBRA", "ENPH",
    ],
    "Communication": [
        "META", "NFLX", "TMUS", "T", "VZ", "DIS", "CMCSA", "CHTR", "WBD", "EA",
        "TTWO", "MTCH", "FOXA", "FOX", "IPG", "OMC", "PARA", "LUMN", "DISH", "SIRI",
        "LYV", "IACI",
    ],
    "Consumer Disc": [
        "AMZN", "TSLA", "HD", "MCD", "NKE", "LOW", "SBUX", "TJX", "BKNG", "MAR",
        "HLT", "GM", "F", "ORLY", "AZO", "BBY", "DRI", "YUM", "CMG", "ABNB", "UBER",
        "LYFT", "DKNG", "ETSY", "W", "RCL", "CCL", "NCLH", "MGM", "CZR", "WYNN",
        "LVS", "HAS", "MAT", "RL", "TPR", "CPRI", "GPC", "AAP", "AN", "KMX", "CVNA",
        "CARVANA", "DHI", "LEN", "PHM", "TOL", "NVR", "MTH",
    ],
    "Health Care": [
        "UNH", "LLY", "JNJ", "ABT", "TMO", "DHR", "BMY", "AMGN", "ISRG", "SYK",
        "MDT", "EW", "BSX", "ZBH", "HOLX", "IDXX", "IQV", "VRTX", "REGN", "GILD",
        "BIIB", "HUM", "CVS", "CI", "CNC", "MOH", "HCA", "DGX", "LH", "A",
        "DXCM", "ILMN", "MRNA", "PFE", "MRK", "ABBV", "ZTS", "ALGN", "BAX",
        "BDX", "COO", "CTLT", "DVA", "HSIC", "INCY", "MCK", "MHK", "OGN",
        "PKI", "PODD", "RGEN", "RMD", "TECH", "TFX", "VAR", "VTRS", "WAT",
        "XRAY",
    ],
    "Financials": [
        "BRK-B", "JPM", "V", "MA", "BAC", "WFC", "GS", "MS", "BLK", "SCHW",
        "AXP", "C", "USB", "PNC", "TFC", "COF", "DFS", "SYF", "AIG", "MET",
        "PRU", "ALL", "CB", "MMC", "AON", "MCO", "SPGI", "ICE", "CME", "CBOE",
        "NDAQ", "FIS", "FI", "GPN", "PYPL", "SQ", "AFRM", "HOOD", "SOFI",
        "ALLY", "CMA", "FITB", "HBAN", "KEY", "MTB", "RF", "STT", "BK",
        "NTRS", "CFG", "SIVB", "WAL", "WRB", "HIG", "L", "LNC", "UNM",
        "AFL", "GL", "TMK", "RE", "RLI", "CINF",
    ],
    "Industrials": [
        "CAT", "DE", "UNP", "HON", "UPS", "FDX", "MMM", "GE", "ETN", "EMR",
        "PH", "ROK", "XYL", "VRSK", "CTAS", "RSG", "WM", "EXPD", "CHRW",
        "DAL", "UAL", "AAL", "LUV", "ALK", "JBLU", "SAVE", "SWAPA",
        "NSC", "CSX", "CP", "CNI", "WAB", "TRN", "GNRC", "CARR", "OTIS",
        "JCI", "AME", "FAST", "GWW", "MSA", "SWK", "SNA", "TXT", "HII",
        "TDG", "AXON", "LDOS",
    ],
    "Consumer Staples": [
        "WMT", "PG", "KO", "PEP", "COST", "PM", "MO", "MDLZ", "CL", "EL",
        "KMB", "GIS", "K", "CPB", "HRL", "MKC", "SJM", "CLX", "CHD",
        "CAG", "HSY", "TR", "MNST", "KDP", "STZ", "BF-B", "TAP", "SAM",
        "SYY", "USFD", "PFGC", "ADM", "BG", "INGR", "THS", "SMPL",
        "WBA", "CVS",
    ],
    "Materials": [
        "LIN", "APD", "SHW", "FCX", "NEM", "NUE", "STLD", "CF", "MOS", "ALB",
        "ECL", "PPG", "IFF", "CE", "DOW", "LYB", "EMN", "FMC", "IP", "PKG",
        "SEE", "SON", "WRK", "AVY", "BMS", "BALL", "CCK", "GEF", "ATI",
        "CSTM", "HWM", "AA", "CENX", "KALU", "CMC", "RS", "ZEUS",
    ],
    "Energy Broad": [
        "XOM", "CVX", "COP", "EOG", "SLB", "MPC", "PSX", "VLO", "OXY", "HAL",
        "DVN", "MRO", "APA", "BKR", "KMI", "OKE", "WMB", "ET", "EPD", "MMP",
        "TRGP", "HES", "PXD", "FANG", "CLR", "SM", "CPE", "MGY", "MTDR",
        "CIVI", "PR", "RRC", "SWN", "EQT", "AR", "CNX", "CHK",
    ],
    "Utilities": [
        "NEE", "SO", "DUK", "AEP", "XEL", "D", "PCG", "EIX", "PPL", "ES",
        "FE", "AEE", "CMS", "NI", "OGE", "POR", "SR", "WTRG", "AWK", "CWT",
        "SJW", "YORW", "LNT", "EVRG", "IDACORP", "PNW", "AVA", "NWE",
    ],
    "Real Estate": [
        "PLD", "CCI", "O", "SPG", "WELL", "AVB", "EQR", "PSA", "EXR", "VTR",
        "BXP", "SLG", "KIM", "REG", "FRT", "NNN", "GLPI", "VICI", "MPW",
        "PEAK", "HR", "DOC", "OHI", "SBRA", "LTC", "CTRE", "NHI",
        "IRM", "CONE", "QTS", "REXR", "TRNO", "EGP", "STAG", "COLD",
        "WPC", "STORE", "ADC", "EPRT", "GTY",
    ],
}
