"""
SPY market data via yfinance — the only module in this lane that touches the network.

PREREG §11 (isolation): SPY data comes from yfinance DIRECTLY. This lane never
opens `cyberscreener.db`, not even read-only, and imports nothing from `api/`.
yfinance is a third-party library, not an application module, so using it does
not breach that isolation.

Outbound only. No listener is opened anywhere in this lane.
"""

from __future__ import annotations

import datetime as dt

SYMBOL = "SPY"


def _yf():
    import yfinance as yf
    return yf


def fetch_closes(symbol: str = SYMBOL, period: str = "5y") -> dict:
    """
    Daily closes for the HAR-RV fit.

    Content is validated before it is used: an empty frame or a non-numeric
    close is reported as a failure rather than passed downstream. The June
    gather post-mortem (RESULT_LT_RECONSTRUCTION §1.1) is the standing reason —
    every silent failure there was an unvalidated response body treated as data.
    """
    try:
        hist = _yf().Ticker(symbol).history(period=period, auto_adjust=False)
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    if hist is None or hist.empty or "Close" not in hist.columns:
        return {"ok": False, "reason": "empty history"}
    closes = [float(c) for c in hist["Close"].tolist() if c == c and c > 0]
    if len(closes) < 100:
        return {"ok": False, "reason": f"only {len(closes)} usable closes"}
    return {"ok": True, "closes": closes,
            "last_date": str(hist.index[-1].date()), "spot": closes[-1]}


def fetch_chain(symbol: str = SYMBOL, asof: dt.date | None = None) -> dict:
    """
    Option chain grouped by expiry, with DTE, for condor construction.

    Returns plain dicts so the selection logic in `condor.py` stays testable
    against fixtures and never needs pandas or a live network.
    """
    asof = asof or dt.date.today()
    try:
        tk = _yf().Ticker(symbol)
        expiries = list(tk.options or [])
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    if not expiries:
        return {"ok": False, "reason": "no expiries returned"}

    dte = {}
    for e in expiries:
        try:
            d = (dt.date.fromisoformat(e) - asof).days
        except ValueError:
            continue
        if 0 < d <= 90:
            dte[e] = d
    if not dte:
        return {"ok": False, "reason": "no expiries within 90 days"}
    return {"ok": True, "expiries_dte": dte, "ticker": tk}


def fetch_expiry_legs(ticker, expiry: str) -> dict:
    """Puts and calls for one expiry, as row dicts."""
    try:
        oc = ticker.option_chain(expiry)
    except Exception as exc:
        return {"ok": False, "reason": f"{type(exc).__name__}: {exc}"}
    keep = ["strike", "bid", "ask", "lastPrice", "impliedVolatility", "delta"]

    def rows(frame):
        out = []
        for rec in frame.to_dict("records"):
            out.append({k: rec.get(k) for k in keep if k in rec or k == "delta"})
        return out

    return {"ok": True, "puts": rows(oc.puts), "calls": rows(oc.calls)}


def atm_iv30(ticker, expiries_dte: dict, spot: float) -> dict:
    """
    ATM implied volatility at the expiry nearest 30 DTE, in vol points.

    This is the IV leg of the registered entry rule, so it is taken from the
    expiry nearest 30 DTE regardless of which expiry the condor uses — the rule
    compares a 30-day IV against a 21-day forecast, as registered.
    """
    if not expiries_dte:
        return {"ok": False, "reason": "no expiries"}
    expiry = min(expiries_dte, key=lambda e: abs(expiries_dte[e] - 30))
    legs = fetch_expiry_legs(ticker, expiry)
    if not legs["ok"]:
        return legs
    ivs = []
    for side in ("puts", "calls"):
        best = None
        for r in legs[side]:
            iv = r.get("impliedVolatility")
            if iv is None or not (0 < float(iv) < 3):
                continue
            gap = abs(float(r["strike"]) - spot)
            if best is None or gap < best[0]:
                best = (gap, float(iv))
        if best:
            ivs.append(best[1])
    if not ivs:
        return {"ok": False, "reason": "no usable ATM implied vol"}
    return {"ok": True, "iv30_vol_points": sum(ivs) / len(ivs) * 100.0,
            "expiry": expiry, "dte": expiries_dte[expiry]}
