# RESULT — Narrative Sync (SESSION_NARRATIVE_SYNC, part 3)

**Date:** 2026-06-16
**Branch:** `feat/narrative-sync` (stacked on `feat/narrative-pipeline` / PR #20)
**Draft PR:** https://github.com/keltonshockey/cyberscreener/pull/21 (stacked on #20)
**Scope:** Phase 3 of NARRATIVE_LAYER_PLAN.md — deliver `narratives.db` from mill to the droplet so the public Ticker page serves it. **The only component that writes to prod**, and it writes exactly one regenerable file into one isolated directory — never code, never `cyberscreener.db`, no service. Out of scope: generation, scoring, any service restart, deploys.

## Boundary decision honored
`home-ai-lab/MEMORY.md` (2026-06-01): *mill never holds general production write access; restricted keys use an unprivileged user, never root.* The forced-command key here is **not** a prod key — it can only receive an rsync of `narratives.db` into `/opt/cyberscreener/data/narratives/`, under an unprivileged `narrative` user. The constraint is met cleanly, so the primary approach is used (the documented tailnet-pull alternative is offered for Kelton in the runbook, since it would be a network change).

## Files added
- `bin/narrative-rsync-only.sh` — droplet-side forced-command wrapper (the enforcer).
- `scripts/mill/push_narratives.sh` — mill delivery: consistent snapshot, hash-noop, atomic rsync, Pushover-on-fail.
- `scripts/mill/com.mill.cs-narrative-sync.plist` — launchd timer (every 15 min; STAGED, install after verify).
- `scripts/NARRATIVE_SYNC_RUNBOOK.md` — install / first delivery / verify / lockdown-proof / rollback.
- `api/tests/test_narrative_sync_wrapper.py` — 9 automated proof cases.

## The exact `authorized_keys` forced-command line
Installed under the unprivileged `narrative` user (`~narrative/.ssh/authorized_keys`):
```
command="/opt/cyberscreener/bin/narrative-rsync-only.sh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHWI28K4mXBVa+W2mZNAYE/z/KQ7SQK1n1DmF17JftSm narrative-sync
```
Keypair generated on **mill** 2026-06-16: private `~/.ssh/narrative_sync_ed25519` (never leaves mill, never printed); public key above. `nologin` shell + the four `no-*` options + the forced command = no shell, no forwarding, no PTY.

## The wrapper (how it can do nothing else)
With a forced command, sshd runs the wrapper for every connection on that key and exposes the attempted command in `$SSH_ORIGINAL_COMMAND`. The wrapper:
1. Rejects an empty command (interactive shell attempt).
2. Rejects any shell metacharacter (`; | & < > ` `` ` `` $ ( ) { }`) — and never shell-evaluates the string anyway (it tokenizes + re-execs), so chaining is inert.
3. Requires the command to be `rsync --server …` (not a shell, scp, sftp, or any other binary).
4. Rejects `--sender` (that mode would *read* a file off the droplet — exfil).
5. Rejects dangerous options (`--daemon`, `--remove-source-files`, `--inplace`, `-e`, `--*-dest`, `--files-from`, `--filter`, `--config`, …) as defense-in-depth.
6. Forwards **only** the negotiated short-flag token and **hard-pins the destination** to `/opt/cyberscreener/data/narratives/narratives.db` — the client's requested path is discarded, so bytes can land nowhere else.

## Proof the key can't do anything but drop that one file (tested)
- **Automated, in `make test`** (`test_narrative_sync_wrapper.py`, 9 cases, DRYRUN mode): accepts a normal push; accepts a no-flag push; **a client request for `…/cyberscreener.db` still resolves to the pinned `narratives.db`**; rejects empty/shell/scp/`--sender`/`--inplace`/`--daemon`/`--remove-source-files`/`-e`/command-chaining.
- **Real end-to-end loopback** (no sshd, no prod): drove the wrapper with an actual `rsync` client via an `-e` shim. (A) an allowed push landed `narratives.db`; (B) a push whose client destination was `/opt/cyberscreener/data/cyberscreener.db` **landed at `narratives.db` and created no `cyberscreener.db`**. The destination pin holds against an actively hostile path.

## Atomic-write approach
The mill side takes a consistent point-in-time snapshot via `sqlite3 .backup` (folds the WAL into one self-contained file — no torn db, no stray `-wal`/`-shm` shipped), then rsyncs it. rsync's default behavior writes a hidden temp in the dest dir and atomically renames, so the part-1 router never reads a half file. (`--inplace` is rejected by the wrapper, preserving this.)

## Cadence + failure handling
- `push_narratives.sh` no-ops via sha256 hash-compare when the snapshot is unchanged, so the 15-min launchd timer is cheap and idempotent. It can also be called by the part-2 pipeline right after it writes, with the timer as a backstop.
- On any failure it logs to `~/.local/state/narrative-sync/push.log` and sends a **Pushover** alert (token/user from `~/.config/grist/mill-secrets.env`) — watcher-on-the-watcher. A missing source db is a clean no-op, not an alert.
- **Delivery failure never breaks the site:** if the file is missing/locked the part-1 router returns 202 `{"status":"generating"}` and the Ticker page shows the quiet placeholder.

## Rollback (zero prod impact)
`rm -f /opt/cyberscreener/data/narratives/narratives.db` → router returns "generating" for every ticker; nothing else affected (no scoring/journal/service). To stop entirely: unload the launchd timer + remove `~narrative/.ssh/authorized_keys`.

## Network-safety (hard rule #6) — CONFIRMED CLEAN
Delivery is an **outbound** rsync from mill over the **existing** ssh path (port 22) + an outbound HTTPS Pushover on failure. **No new listener** on the droplet, **no bind-address / mDNS / firewall** change. The droplet gains one `authorized_keys` entry (a credential, not a network surface) under an unprivileged user. No inbound surface opened.

## What was NOT done autonomously (supervised, in the runbook)
Installing the `authorized_keys` line + `narrative` user on the **droplet** is a prod write to the box's SSH config — left as an operator step (runbook §1) per "draft PR only, never deploy" and the mill-never-holds-prod-write boundary (granting this key is a conscious trust decision for Kelton). Everything mill-side (keypair, scripts) is ready; the droplet-side install + the live lockdown proof (runbook §4) are the supervised steps.

## Known follow-up (not blocking)
The push replaces the whole `narratives.db`, which includes the part-1 `view_queue` the droplet router writes to as users browse. Overwriting it resets those view hints between deliveries (TTL-based staleness still drives regeneration). Clean fix for later: split `view_queue` into a separate file in the part-1 store, or have the pipeline pull the droplet's `view_queue` (read-only) before generating. Noted; out of scope for part 3.

## Tests
`make test`: **255 passed** (was 246 after part 2; +9 here). No scoring/golden change.

## Out of scope
Generation (part 2), scoring, any service restart, deploys.
