#!/bin/bash
# narrative-rsync-only.sh — droplet-side forced-command wrapper.
#
# This is the ONLY thing the narrative-sync SSH key is permitted to do: receive
# an rsync push of ONE file (narratives.db) into ONE directory. It cannot open a
# shell, cannot run any other command, cannot read/exfil any file, and cannot
# redirect where bytes land — the destination is HARD-PINNED here, ignoring
# whatever path the client requested.
#
# Install (droplet, as the unprivileged `narrative` user — NEVER root):
#   ~narrative/.ssh/authorized_keys:
#     command="/opt/cyberscreener/bin/narrative-rsync-only.sh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA... narrative-sync
#
# How it works: with a forced command, sshd runs THIS script for every connection
# on that key and exposes the command the client tried to run in
# $SSH_ORIGINAL_COMMAND. We accept only an `rsync --server` RECEIVE, strip the
# client's destination, and re-exec rsync against our own pinned file. rsync's
# default temp-file + atomic rename means the reader never sees a half file.
#
# Test without writing (used by the test suite + the runbook loopback check):
#   SSH_ORIGINAL_COMMAND='rsync --server -vlogDtpre.iLsfxC . narratives.db' \
#     NARRATIVE_RSYNC_DRYRUN=1 bin/narrative-rsync-only.sh

set -euo pipefail

DEST_DIR="${NARRATIVE_DEST_DIR:-/opt/cyberscreener/data/narratives}"
DEST_FILE="$DEST_DIR/narratives.db"
LOG="${NARRATIVE_RSYNC_LOG:-$DEST_DIR/sync.log}"

log()  { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG" 2>/dev/null || true; }
deny() { log "DENY: $* | orig=[${SSH_ORIGINAL_COMMAND:-}]"; echo "narrative-sync: rejected ($*)" >&2; exit 1; }

cmd="${SSH_ORIGINAL_COMMAND:-}"

# 1) No command => an interactive shell attempt. Refuse.
[ -n "$cmd" ] || deny "empty command (shell attempt)"

# 1a) Refuse any shell metacharacter. A legitimate `rsync --server` line never
#     contains these. We never shell-evaluate $SSH_ORIGINAL_COMMAND (we tokenize
#     and re-exec), so chaining is already inert — this just makes that obvious.
case "$cmd" in
  *';'*|*'|'*|*'&'*|*'<'*|*'>'*|*'`'*|*'$'*|*'('*|*')'*|*'{'*|*'}'*)
    deny "shell metacharacter forbidden" ;;
esac

# 2) Must be an rsync server invocation — not a shell, scp, sftp, or anything else.
case "$cmd" in
  "rsync --server "*) : ;;
  *) deny "not an rsync --server invocation" ;;
esac

# 3) Never allow the sender mode (that is a READ off the droplet — exfil).
case "$cmd" in
  *" --sender"*) deny "rsync --sender (read/exfil) forbidden" ;;
esac

# 4) Defense-in-depth: refuse known-dangerous long options anywhere in the line.
#    (We also do not forward them below — this is belt-and-suspenders + logging.)
for bad in " --daemon" " --remove-source-files" " --remove-sent-files" \
           " --rsh=" " -e " " --copy-dest" " --link-dest" " --compare-dest" \
           " --inplace" " --files-from" " --include-from" " --filter" " --config"; do
  case " $cmd " in *"$bad"*) deny "option not allowed:${bad}" ;; esac
done

# 5) Extract ONLY the negotiated short-flag token rsync places right after
#    --server (e.g. -vlogDtpre.iLsfxC). Everything the client sent after that —
#    including its chosen destination path — is discarded.
read -r -a parts <<< "$cmd"          # parts[0]=rsync parts[1]=--server parts[2]=<flags|.>
flags=""
tok="${parts[2]:-}"
if [ "$tok" != "." ] && [ -n "$tok" ]; then
  case "$tok" in
    -[A-Za-z0-9.]*) flags="$tok" ;;   # a short-flag token only (no long options)
    *) deny "unexpected token after --server: $tok" ;;
  esac
fi

# 6) Re-exec rsync as a RECEIVER into our pinned file. The client cannot change
#    DEST_FILE — that is the whole point.
if [ "${NARRATIVE_RSYNC_DRYRUN:-0}" = "1" ]; then
  # Test mode: print exactly what we would run, write nothing.
  echo "rsync --server ${flags} . ${DEST_FILE}"
  exit 0
fi

mkdir -p "$DEST_DIR"
log "ACCEPT: rsync --server ${flags} . ${DEST_FILE}"
# shellcheck disable=SC2086  # $flags is a single validated token, intentional split
exec rsync --server ${flags} . "$DEST_FILE"
