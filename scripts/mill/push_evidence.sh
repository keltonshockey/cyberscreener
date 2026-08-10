#!/bin/sh
# push_evidence.sh - deliver the weekly evidence artifacts from mill to the
# droplet (SESSION-V3B-EVIDENCE). Modeled on push_narratives.sh, the precedent.
#
# Ships exactly THREE regenerable files - the newest gate-read markdown and the
# newest IC-report markdown + CSV pair - into ONE isolated directory via a
# restricted forced-command key (bin/evidence-rsync-only.sh on the droplet).
# It touches no code, no service, no cyberscreener.db; it never runs systemctl
# and never restarts anything. The delivery is an OUTBOUND rsync over the
# existing ssh path - no new listener, no bind/firewall change on the droplet.
#
# Safe to run on a timer: it no-ops when the content is unchanged (hash
# compare) and Pushovers on failure WITH THE RESPONSE READ - the reply is
# captured and logged accepted / NOT ACCEPTED, never piped to /dev/null
# (OPERATIONS_PLAYBOOK 9b: a notifier whose reply is discarded reports "sent"
# for an alert that went nowhere). A delivery failure never breaks the site -
# the evidence router serves an honest empty/stale state when files are
# missing or old.
#
# Configuration (override via environment):
#   GATE_SRC            gate-read landing zone on mill (default ~/mill-local-edits/gate-reads)
#   IC_SRC              IC-report landing zone on mill  (default ~/mill-local-edits/ic-reports)
#   EVIDENCE_SYNC_KEY   restricted private key          (default ~/.ssh/evidence_sync_ed25519)
#   EVIDENCE_DROPLET    user@host for the sync user     (default evidence@cyber.keltonshockey.com)
#   EVIDENCE_DROPLET_PORT  ssh port                     (default 22)
#   EVIDENCE_SYNC_STATE state/log dir on mill           (default ~/.local/state/evidence-sync)
#   Pushover keys come from ~/.config/grist/mill-secrets.env (PUSHOVER_TOKEN,
#   PUSHOVER_USER) - vault-backed, never inline here.
set -eu

GATE_SRC="${GATE_SRC:-$HOME/mill-local-edits/gate-reads}"
IC_SRC="${IC_SRC:-$HOME/mill-local-edits/ic-reports}"
KEY="${EVIDENCE_SYNC_KEY:-$HOME/.ssh/evidence_sync_ed25519}"
DROPLET="${EVIDENCE_DROPLET:-evidence@cyber.keltonshockey.com}"
PORT="${EVIDENCE_DROPLET_PORT:-22}"
STATE_DIR="${EVIDENCE_SYNC_STATE:-$HOME/.local/state/evidence-sync}"
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
    # READ the response. Pushover answers {"status":1,...} on acceptance;
    # anything else (or an empty reply) is logged as NOT ACCEPTED so a dead
    # alert path is visible in the log instead of silently swallowed.
    resp="$(curl -s --max-time 15 \
      --form-string "token=${PUSHOVER_TOKEN}" \
      --form-string "user=${PUSHOVER_USER}" \
      --form-string "title=evidence-sync FAILED" \
      --form-string "message=${msg}" \
      https://api.pushover.net/1/messages.json 2>/dev/null || true)"
    case "$resp" in
      *'"status":1'*) log "pushover: accepted" ;;
      *) log "pushover: NOT ACCEPTED (response: ${resp:-<empty>})" ;;
    esac
  else
    log "pushover: PUSHOVER_TOKEN/PUSHOVER_USER not set - skipped"
  fi
}

newest() {
  # Newest by NAME (ISO dates + the generator's -02 counter sort correctly);
  # `ls` mtime order would lie after a restore or a re-rsync.
  dir="$1"; pat="$2"
  [ -d "$dir" ] || return 1
  # shellcheck disable=SC2012
  ls "$dir" 2>/dev/null | grep -E "$pat" | LC_ALL=C sort | tail -n 1
}

# No artifacts yet (generators never ran) is a clean no-op, not a failure.
GATE_MD_NAME="$(newest "$GATE_SRC" '^GATE_READ_[0-9]{4}-[0-9]{2}-[0-9]{2}\.md$' || true)"
IC_MD_NAME="$(newest "$IC_SRC" '^ic-report-[0-9]{4}-[0-9]{2}-[0-9]{2}(-[A-Za-z0-9_]+)*\.md$' || true)"
if [ -z "$GATE_MD_NAME" ] && [ -z "$IC_MD_NAME" ]; then
  log "no artifacts in $GATE_SRC or $IC_SRC - nothing to deliver"
  exit 0
fi
[ -f "$KEY" ] || { notify_fail "missing sync key $KEY"; exit 1; }

# The IC csv is the md's sibling by stem; a missing csv is delivered-around,
# not fatal - the router serves the md with a null table.
IC_CSV_NAME=""
if [ -n "$IC_MD_NAME" ]; then
  stem="${IC_MD_NAME%.md}"
  [ -f "$IC_SRC/$stem.csv" ] && IC_CSV_NAME="$stem.csv"
fi

# Stage a point-in-time snapshot so a generator writing mid-push cannot tear
# a file, and so one rsync invocation carries all artifacts atomically-enough
# (each file individually lands via rsync temp-file + rename).
TMP="$(mktemp -d "${TMPDIR:-/tmp}/evidence.push.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT INT TERM
set --
[ -n "$GATE_MD_NAME" ] && { cp "$GATE_SRC/$GATE_MD_NAME" "$TMP/"; set -- "$@" "$TMP/$GATE_MD_NAME"; }
[ -n "$IC_MD_NAME" ]   && { cp "$IC_SRC/$IC_MD_NAME" "$TMP/";   set -- "$@" "$TMP/$IC_MD_NAME"; }
[ -n "$IC_CSV_NAME" ]  && { cp "$IC_SRC/$IC_CSV_NAME" "$TMP/";  set -- "$@" "$TMP/$IC_CSV_NAME"; }

# Hash-compare no-op so a timer re-run is cheap and idempotent.
HASH="$(cat "$@" | shasum -a 256 | awk '{print $1}')"
if [ -f "$LAST_HASH_FILE" ] && [ "$HASH" = "$(cat "$LAST_HASH_FILE")" ]; then
  log "unchanged ($HASH) - skip delivery"
  exit 0
fi

# Atomic delivery through the restricted key. The forced command pins the
# destination directory; the path below is advisory and overridden server-side.
if rsync -q --timeout=60 \
    -e "ssh -i $KEY -p $PORT -o BatchMode=yes -o StrictHostKeyChecking=accept-new" \
    "$@" "$DROPLET:evidence/"; then
  echo "$HASH" > "$LAST_HASH_FILE"
  log "delivered $HASH to $DROPLET ($#: ${GATE_MD_NAME:-none} ${IC_MD_NAME:-none} ${IC_CSV_NAME:-none})"
else
  notify_fail "rsync delivery to $DROPLET failed (gate=${GATE_MD_NAME:-none} ic=${IC_MD_NAME:-none})"
  exit 1
fi
