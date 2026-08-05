#!/bin/sh
# Weekly standing IC report (SESSION-R2-IC-HARNESS) - runs on mill, Sundays 18:30,
# after the 18:00 gate read.
# STAGED: install with the launchd plist next to this file (operator action).
#
# Reads the nightly droplet DB pull READ-ONLY (via api/db/ro.py connect_ro),
# writes a dated markdown + CSV pair into the mill landing zone APPEND-ONLY -
# it never overwrites or deletes a previous report - and sends the delta
# paragraph via Pushover, logging accepted / NOT ACCEPTED.
#
# Nothing here touches the droplet or any live service. No listener is opened;
# the only outbound connection is Pushover over the existing path.
#
# Configuration (override via environment):
#   CS_REPO   - cyberscreener checkout on mill   (default ~/cyberscreener)
#   CS_DB     - the nightly DB pull location     (default ~/cs-nightly/cyberscreener.db)
#   IC_OUT    - landing zone for IC reports      (default ~/mill-local-edits/ic-reports)
#   IC_VENV   - python 3.11 venv for the harness (default ~/.venvs/icharness)
#   IC_WINDOW - trailing calendar days           (default 180)
#   Pushover keys come from ~/.config/grist/mill-secrets.env (PUSHOVER_TOKEN,
#   PUSHOVER_USER) - vault-backed, never inline here.
set -eu

CS_REPO="${CS_REPO:-$HOME/cyberscreener}"
CS_DB="${CS_DB:-$HOME/cs-nightly/cyberscreener.db}"
IC_OUT="${IC_OUT:-$HOME/mill-local-edits/ic-reports}"
IC_VENV="${IC_VENV:-$HOME/.venvs/icharness}"
IC_WINDOW="${IC_WINDOW:-180}"
SECRETS="$HOME/.config/grist/mill-secrets.env"

# Fail loudly on a missing input rather than producing an empty analysis.
# connect_ro would also refuse to conjure the DB, but naming the path here makes
# the launchd log say which one was wrong.
if [ ! -f "$CS_DB" ]; then
    echo "ic_report_weekly: DB not found at $CS_DB - set CS_DB to the nightly pull path" >&2
    exit 1
fi

if [ ! -x "$IC_VENV/bin/python" ]; then
    echo "ic_report_weekly: no python at $IC_VENV/bin/python" >&2
    echo "  create it with: python3.11 -m venv $IC_VENV" >&2
    echo "  then: $IC_VENV/bin/pip install pandas numpy" >&2
    echo "  (system python3 on mill is 3.9 and will not run this harness)" >&2
    exit 1
fi

if [ -f "$SECRETS" ]; then
    set -a
    . "$SECRETS"
    set +a
fi

cd "$CS_REPO"
exec "$IC_VENV/bin/python" -m research.harness.ic_report \
    --db "$CS_DB" \
    --out-dir "$IC_OUT" \
    --window-days "$IC_WINDOW" \
    --pushover
