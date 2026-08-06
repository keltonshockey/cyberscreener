#!/bin/sh
# Cohort D paper logger (SESSION-R4) - runs on mill, daily.
# STAGED: install with the launchd plist next to this file (operator action).
#
# Safe to run every day. It acts only on the first trading day of a month
# (entry evaluation, PREREG section 5) and on dates when an open position's
# expiry has arrived (settlement, PREREG section 6). Every other day it exits
# after saying it did nothing.
#
# Isolation (PREREG section 11): never opens cyberscreener.db, imports nothing
# from api/, writes only ~/cs-research/cohortD.db. SPY data comes from yfinance.
# No listener is opened; the only outbound calls are yfinance and Pushover.
#
# Configuration (override via environment):
#   CS_REPO   - cyberscreener checkout on mill  (default ~/cyberscreener)
#   CD_DB     - cohort D database               (default ~/cs-research/cohortD.db)
#   CD_VENV   - python 3.11 venv                (default ~/.venvs/cohortd)
#   Pushover keys come from ~/.config/grist/mill-secrets.env (PUSHOVER_TOKEN,
#   PUSHOVER_USER) - vault-backed, never inline here.
set -eu

CS_REPO="${CS_REPO:-$HOME/cyberscreener}"
CD_DB="${CD_DB:-$HOME/cs-research/cohortD.db}"
CD_VENV="${CD_VENV:-$HOME/.venvs/cohortd}"
SECRETS="$HOME/.config/grist/mill-secrets.env"

if [ ! -x "$CD_VENV/bin/python" ]; then
    echo "cohortd_daily: no python at $CD_VENV/bin/python" >&2
    echo "  create it with: uv venv --python 3.11 $CD_VENV" >&2
    echo "  then: uv pip install --python $CD_VENV/bin/python yfinance numpy" >&2
    echo "  (system python3 on mill is 3.9 and brew python3 is 3.14; neither is used)" >&2
    exit 1
fi

if [ -f "$SECRETS" ]; then
    set -a
    . "$SECRETS"
    set +a
fi

cd "$CS_REPO"
exec "$CD_VENV/bin/python" -m research.cohortd.logger --db "$CD_DB"
