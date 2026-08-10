#!/bin/bash
# evidence-rsync-only.sh - droplet-side forced-command wrapper (evidence lane).
#
# Cloned from bin/narrative-rsync-only.sh, the precedent that passed the
# adversarial DRYRUN suite. This is the ONLY thing the evidence-sync SSH key is
# permitted to do: receive an rsync push of the weekly evidence artifacts
# (GATE_READ_*.md, ic-report-*.md/.csv) into ONE directory. It cannot open a
# shell, cannot run any other command, cannot read/exfil any file, and cannot
# redirect where bytes land - the destination DIRECTORY is HARD-PINNED here,
# ignoring whatever path the client requested.
#
# Install (droplet, as the unprivileged `evidence` user - NEVER root):
#   ~evidence/.ssh/authorized_keys:
#     command="/opt/cyberscreener/bin/evidence-rsync-only.sh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAA... evidence-sync
#
# How it works: with a forced command, sshd runs THIS script for every
# connection on that key and exposes the command the client tried to run in
# $SSH_ORIGINAL_COMMAND. We accept only an `rsync --server` RECEIVE, strip the
# client's destination, and re-exec rsync into our own pinned directory.
# rsync's default temp-file + atomic rename means the reader never sees a
# half-written artifact.
#
# Differences from the narrative wrapper, both restrictive:
#   - any '..' anywhere in the client line is rejected outright (the narrative
#     wrapper merely ignored the client path; this one refuses to proceed);
#   - the short-flag token must not smuggle R (--relative) or a long option,
#     so a client cannot re-introduce sender-side paths into the receiver.
#
# Test without writing (used by the test suite + the runbook loopback check):
#   SSH_ORIGINAL_COMMAND='rsync --server -vlogDtpre.iLsfxC . evidence/' \
#     EVIDENCE_RSYNC_DRYRUN=1 bin/evidence-rsync-only.sh

set -euo pipefail

DEST_DIR="${EVIDENCE_DEST_DIR:-/opt/cyberscreener/data/evidence}"
LOG="${EVIDENCE_RSYNC_LOG:-$DEST_DIR/sync.log}"

log()  { printf '%s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" >> "$LOG" 2>/dev/null || true; }
deny() { log "DENY: $* | orig=[${SSH_ORIGINAL_COMMAND:-}]"; echo "evidence-sync: rejected ($*)" >&2; exit 1; }

cmd="${SSH_ORIGINAL_COMMAND:-}"

# 1) No command => an interactive shell attempt. Refuse.
[ -n "$cmd" ] || deny "empty command (shell attempt)"

# 1a) Refuse any shell metacharacter. A legitimate `rsync --server` line never
#     contains these. We never shell-evaluate $SSH_ORIGINAL_COMMAND (we tokenize
#     and re-exec), so chaining is already inert - this just makes that obvious.
case "$cmd" in
  *';'*|*'|'*|*'&'*|*'<'*|*'>'*|*'`'*|*'$'*|*'('*|*')'*|*'{'*|*'}'*)
    deny "shell metacharacter forbidden" ;;
esac

# 1b) Refuse any '..' anywhere in the line. The client's destination is
#     discarded below regardless, but a traversal-shaped request is hostile on
#     its face and gets a hard NO plus a log line, not a silent redirect.
case "$cmd" in
  *'..'*) deny "path traversal ('..') forbidden" ;;
esac

# 2) Must be an rsync server invocation - not a shell, scp, sftp, or anything else.
case "$cmd" in
  "rsync --server "*) : ;;
  *) deny "not an rsync --server invocation" ;;
esac

# 3) Never allow the sender mode (that is a READ off the droplet - exfil).
case "$cmd" in
  *" --sender"*) deny "rsync --sender (read/exfil) forbidden" ;;
esac

# 4) Defense-in-depth: refuse known-dangerous long options anywhere in the
#    line. Superset of the narrative wrapper's list: adds --log-file (write an
#    attacker-named file), --backup-dir/--partial-dir/--temp-dir (bytes outside
#    the pin), --chmod/--chown/--perms-writable knobs, and --mkpath.
for bad in " --daemon" " --remove-source-files" " --remove-sent-files" \
           " --rsh=" " -e " " --copy-dest" " --link-dest" " --compare-dest" \
           " --inplace" " --files-from" " --include-from" " --filter" " --config" \
           " --log-file" " --backup-dir" " --partial-dir" " --temp-dir" \
           " --chmod" " --chown" " --mkpath" " --relative"; do
  case " $cmd " in *"$bad"*) deny "option not allowed:${bad}" ;; esac
done

# 5) Extract ONLY the negotiated short-flag token rsync places right after
#    --server (e.g. -vlogDtpre.iLsfxC). Everything the client sent after that -
#    including its chosen destination path - is discarded. The pre-dot flag
#    letters must not include R: -R/--relative would let the sender's paths
#    (including directories) re-enter the receive.
read -r -a parts <<< "$cmd"          # parts[0]=rsync parts[1]=--server parts[2]=<flags|.>
flags=""
tok="${parts[2]:-}"
if [ "$tok" != "." ] && [ -n "$tok" ]; then
  case "$tok" in
    -*R*.*|-*R) deny "relative-paths flag (R) forbidden in flag token" ;;
  esac
  case "$tok" in
    -[A-Za-z0-9.]*) flags="$tok" ;;   # a short-flag token only (no long options)
    *) deny "unexpected token after --server: $tok" ;;
  esac
fi

# 6) Re-exec rsync as a RECEIVER into our pinned directory. The client cannot
#    change DEST_DIR - that is the whole point. Trailing slash: receive INTO
#    the directory; delivered basenames land beside each other, and the
#    droplet router only ever serves names matching its strict whitelist.
if [ "${EVIDENCE_RSYNC_DRYRUN:-0}" = "1" ]; then
  # Test mode: print exactly what we would run, write nothing.
  echo "rsync --server ${flags} . ${DEST_DIR}/"
  exit 0
fi

mkdir -p "$DEST_DIR"
log "ACCEPT: rsync --server ${flags} . ${DEST_DIR}/"
# shellcheck disable=SC2086  # $flags is a single validated token, intentional split
exec rsync --server ${flags} . "$DEST_DIR/"
