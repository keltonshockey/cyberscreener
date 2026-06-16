#!/bin/sh
# push_narratives.sh — deliver narratives.db from mill to the droplet.
#
# This is the ONLY component that writes to the production box, and it writes
# exactly ONE regenerable file (narratives.db) into ONE isolated directory via a
# restricted forced-command key. It touches no code, no service, no
# cyberscreener.db; it never runs systemctl and never restarts anything. The
# delivery is an OUTBOUND rsync over the existing ssh path — no new listener, no
# bind/firewall change on the droplet (hard rule #6 clean).
#
# Safe to run on a timer: it takes a consistent point-in-time snapshot, no-ops
# when the content is unchanged (hash compare), and Pushovers on failure. A
# delivery failure never breaks the site — the droplet router degrades to
# "generating" when the file is missing/stale.
#
# Configuration (override via environment):
#   CS_NARRATIVES_DB   source narratives.db on mill   (default ~/cs-narratives/narratives.db)
#   NARRATIVE_SYNC_KEY restricted private key         (default ~/.ssh/narrative_sync_ed25519)
#   NARRATIVE_DROPLET  user@host for the sync user    (default narrative@cyber.keltonshockey.com)
#   NARRATIVE_DROPLET_PORT  ssh port                  (default 22)
#   NARRATIVE_SYNC_STATE    state/log dir on mill     (default ~/.local/state/narrative-sync)
#   Pushover keys come from ~/.config/grist/mill-secrets.env (PUSHOVER_TOKEN,
#   PUSHOVER_USER) — vault-backed, never inline here.
set -eu

SRC="${CS_NARRATIVES_DB:-$HOME/cs-narratives/narratives.db}"
KEY="${NARRATIVE_SYNC_KEY:-$HOME/.ssh/narrative_sync_ed25519}"
DROPLET="${NARRATIVE_DROPLET:-narrative@cyber.keltonshockey.com}"
PORT="${NARRATIVE_DROPLET_PORT:-22}"
STATE_DIR="${NARRATIVE_SYNC_STATE:-$HOME/.local/state/narrative-sync}"
SECRETS="${MILL_SECRETS:-$HOME/.config/grist/mill-secrets.env}"

mkdir -p "$STATE_DIR"
LAST_HASH_FILE="$STATE_DIR/last_pushed.sha256"
LOG="$STATE_DIR/push.log"

log() { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" | tee -a "$LOG" >&2; }

notify_fail() {
  msg="$1"
  log "FAIL: $msg"
  # shellcheck disable=SC1090
  [ -f "$SECRETS" ] && . "$SECRETS" || true
  if [ -n "${PUSHOVER_TOKEN:-}" ] && [ -n "${PUSHOVER_USER:-}" ]; then
    curl -s --max-time 15 \
      --form-string "token=${PUSHOVER_TOKEN}" \
      --form-string "user=${PUSHOVER_USER}" \
      --form-string "title=narrative-sync FAILED" \
      --form-string "message=${msg}" \
      https://api.pushover.net/1/messages.json >/dev/null 2>&1 || true
  fi
}

# No source yet (pipeline never ran) is a clean no-op, not a failure.
[ -f "$SRC" ] || { log "no source db at $SRC — nothing to deliver"; exit 0; }
[ -f "$KEY" ] || { notify_fail "missing sync key $KEY"; exit 1; }

# Consistent point-in-time snapshot: .backup folds the WAL into one self-contained
# file, so we never ship a torn db or stray -wal/-shm.
TMP="$(mktemp "${TMPDIR:-/tmp}/narratives.snap.XXXXXX")"
trap 'rm -f "$TMP"' EXIT INT TERM
if command -v sqlite3 >/dev/null 2>&1; then
  if ! sqlite3 "$SRC" ".backup '$TMP'"; then
    notify_fail "sqlite .backup failed for $SRC"; exit 1
  fi
else
  cp "$SRC" "$TMP"
fi

# Hash-compare no-op so the timer is cheap and idempotent.
HASH="$(shasum -a 256 "$TMP" | awk '{print $1}')"
if [ -f "$LAST_HASH_FILE" ] && [ "$HASH" = "$(cat "$LAST_HASH_FILE")" ]; then
  log "unchanged ($HASH) — skip delivery"
  exit 0
fi

# Atomic delivery. rsync writes a hidden temp in the dest dir then renames, so
# the droplet router never reads a half file. The forced command pins the
# destination; the path below is advisory and is overridden server-side.
if rsync -q --timeout=60 \
    -e "ssh -i $KEY -p $PORT -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
    "$TMP" "$DROPLET:narratives.db"; then
  echo "$HASH" > "$LAST_HASH_FILE"
  log "delivered $HASH to $DROPLET"
else
  notify_fail "rsync delivery to $DROPLET failed"
  exit 1
fi
