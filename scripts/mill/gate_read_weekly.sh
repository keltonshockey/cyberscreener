#!/bin/sh
# Weekly forward-test gate read (SESSION-GATE-PREREG) - runs on mill, Sundays.
# STAGED: install with the launchd plist next to this file (operator action).
#
# Reads the nightly droplet DB pull READ-ONLY, writes GATE_READ_<date>.md to
# the mill landing zone for manual collection into the kb, and sends the
# one-line Pushover summary. Definitions: GATE_PREREG.md (repo root).
#
# Configuration (override via environment):
#   CS_REPO     - cyberscreener checkout on mill      (default ~/cyberscreener)
#   CS_DB       - the nightly DB pull location        (default ~/cs-nightly/cyberscreener.db)
#   GATE_OUT    - landing zone for GATE_READ files    (default ~/mill-local-edits/gate-reads)
#   Pushover keys come from ~/.config/grist/mill-secrets.env (PUSHOVER_TOKEN,
#   PUSHOVER_USER) - vault-backed, never inline here.
set -eu

CS_REPO="${CS_REPO:-$HOME/cyberscreener}"
CS_DB="${CS_DB:-$HOME/cs-nightly/cyberscreener.db}"
GATE_OUT="${GATE_OUT:-$HOME/mill-local-edits/gate-reads}"
SECRETS="$HOME/.config/grist/mill-secrets.env"

if [ ! -f "$CS_DB" ]; then
    echo "gate_read_weekly: DB not found at $CS_DB - set CS_DB to the nightly pull path" >&2
    exit 1
fi

if [ -f "$SECRETS" ]; then
    set -a
    . "$SECRETS"
    set +a
fi

cd "$CS_REPO/api"
exec python3 -m core.gate_report --db "$CS_DB" --out "$GATE_OUT" --pushover
