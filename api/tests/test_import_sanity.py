"""
Import-sanity canary: every backend module must be importable on the running
Python — no def-time NameErrors, no syntax errors, no missing hard deps.

Why this exists: core/schwab_client.py shipped with `pd` used in a function
*annotation* while pandas was imported lazily inside the body. On Python 3.11
(production) annotations evaluate at def time, so the module raised NameError
on import from day one — scanner.py caught it as "Schwab pre-fetch failed
(non-fatal)" and silently fell back to yfinance for every ticker. Python 3.14
(mill, where test suites were run) defers annotations, so the suite was green
while prod enrichment was dead. A one-line import test would have caught it.

This is also the cheapest possible guard against the codegen-artifact class of
breakage (stray shell text like `$c` written into a module).
"""
import importlib

import pytest

MODULES = [
    "core.augur_weights",
    "core.broad_universe",
    "core.play_closure",
    "core.scanner",
    "core.schwab_client",
    "core.sector_tags",
    "core.signals_meta",
    "core.text",
    "core.timing",
    "core.universe",
    "db.migrate_play_closure",
    "db.models",
    "deps",
    "main",
    "routers.auth",
    "routers.backtest",
    "routers.market",
    "routers.scores",
    "scheduler",
]


@pytest.mark.parametrize("module", MODULES)
def test_module_imports(module):
    importlib.import_module(module)
