# Narrative Sync — Runbook (SESSION-NARRATIVE-SYNC, part 3)

Delivers exactly one regenerable file, `narratives.db`, from mill to the droplet,
into one isolated directory, via a restricted forced-command SSH key. **This is
the only component that writes to the production box.** It touches no code, no
service, no `cyberscreener.db`; it never runs `systemctl` and never restarts
anything. A delivery failure can never break the site — the part-1 router degrades
to a "generating" state when the file is missing/locked.

Boundary honored (`home-ai-lab/MEMORY.md`, 2026-06-01): *mill never holds general
production write access.* The key here is **not** a prod key — its `authorized_keys`
entry has a forced command that can only receive an rsync of `narratives.db` into
`/opt/cyberscreener/data/narratives/`. It cannot open a shell, run any other
command, read/exfil any file, or redirect where bytes land. It is installed under
an **unprivileged `narrative` user, never root** (same model as the droplet
monitor's restricted `monitor` user).

Components:
- `bin/narrative-rsync-only.sh` — droplet-side forced-command wrapper (the enforcer).
- `scripts/mill/push_narratives.sh` — mill-side delivery (snapshot + hash-noop + atomic rsync + Pushover-on-fail).
- `scripts/mill/com.mill.cs-narrative-sync.plist` — launchd timer (every 15 min; STAGED).
- `api/tests/test_narrative_sync_wrapper.py` — automated proof the key can do nothing else.

---

## 0. Prereqs / facts

- Restricted keypair lives on **mill**: `~/.ssh/narrative_sync_ed25519` (private, never leaves mill) + `.pub`.
  Public key (generated 2026-06-16):
  ```
  ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHWI28K4mXBVa+W2mZNAYE/z/KQ7SQK1n1DmF17JftSm narrative-sync
  ```
- Droplet: `cyber.keltonshockey.com` (64.23.150.209). Narrative dir: `/opt/cyberscreener/data/narratives/`.
- Pushover keys come from mill's `~/.config/grist/mill-secrets.env` (`PUSHOVER_TOKEN`, `PUSHOVER_USER`).

---

## 1. Install the restricted key on the droplet (operator, runs ON the droplet as root once)

Creates the unprivileged user, the isolated dir, drops in the wrapper, and pins the
forced-command key. **Single paste-safe block:**

```
sudo useradd -m -s /usr/sbin/nologin narrative 2>/dev/null || true
sudo install -d -o narrative -g narrative -m 755 /opt/cyberscreener/data/narratives
sudo install -d -o root -g root -m 755 /opt/cyberscreener/bin
sudo cp /opt/cyberscreener/bin/narrative-rsync-only.sh /opt/cyberscreener/bin/narrative-rsync-only.sh
sudo chown root:root /opt/cyberscreener/bin/narrative-rsync-only.sh
sudo chmod 755 /opt/cyberscreener/bin/narrative-rsync-only.sh
sudo install -d -o narrative -g narrative -m 700 /home/narrative/.ssh
printf '%s %s\n' 'command="/opt/cyberscreener/bin/narrative-rsync-only.sh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty' 'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHWI28K4mXBVa+W2mZNAYE/z/KQ7SQK1n1DmF17JftSm narrative-sync' | sudo tee /home/narrative/.ssh/authorized_keys >/dev/null
sudo chown narrative:narrative /home/narrative/.ssh/authorized_keys
sudo chmod 600 /home/narrative/.ssh/authorized_keys
```

Notes:
- The wrapper file is shipped in the repo at `bin/narrative-rsync-only.sh`; copy it onto the droplet first (e.g. `git pull` in the droplet checkout, or `scp` it as root), then run the block above. The block assumes it is at `/opt/cyberscreener/bin/`.
- `nologin` shell + the four `no-*` options + the forced command = no shell, no forwarding, no PTY. The forced command is the only thing the key can trigger.

### The exact `authorized_keys` line
```
command="/opt/cyberscreener/bin/narrative-rsync-only.sh",no-port-forwarding,no-agent-forwarding,no-X11-forwarding,no-pty ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIHWI28K4mXBVa+W2mZNAYE/z/KQ7SQK1n1DmF17JftSm narrative-sync
```

---

## 2. First manual delivery (operator, runs ON mill)

```
cd ~/cyberscreener && git checkout feat/narrative-sync && git pull
CS_NARRATIVES_DB="$HOME/cs-narratives/narratives.db" ~/cyberscreener/scripts/mill/push_narratives.sh
```

Expected: `delivered <hash> to narrative@cyber.keltonshockey.com` (or `no source db … nothing to deliver` if the pipeline has not produced one yet — that is a clean no-op, not a failure). Re-running immediately prints `unchanged … skip` (hash-compare no-op).

(`CS_NARRATIVES_DB` defaults to `~/cs-narratives/narratives.db`; point it at wherever the part-2 pipeline writes on mill.)

---

## 3. Verify the droplet serves a fresh narrative

```
ssh root@cyber.keltonshockey.com 'ls -l /opt/cyberscreener/data/narratives/narratives.db && sqlite3 /opt/cyberscreener/data/narratives/narratives.db "SELECT ticker, confidence, lt_generated_at FROM narratives LIMIT 5;"'
curl -s https://quaest.tech/narrative/HPE | head -c 400
```

The `curl` should return the 200 story payload (not the 202 `generating` state) for a ticker that was generated. Open the Ticker page for that symbol and confirm the Story panel renders LT + ST with sources + the fresh dot.

---

## 4. Verify the key is locked down (proof — do this once after install)

From **mill**, confirm the key can do nothing but the one push:

```
ssh -i ~/.ssh/narrative_sync_ed25519 narrative@cyber.keltonshockey.com 'cat /etc/passwd'   # MUST fail: "rejected"
ssh -i ~/.ssh/narrative_sync_ed25519 narrative@cyber.keltonshockey.com                       # MUST fail: no shell
rsync -e "ssh -i ~/.ssh/narrative_sync_ed25519" /etc/hostname narrative@cyber.keltonshockey.com:/opt/cyberscreener/data/cyberscreener.db   # lands at narratives.db, NOT cyberscreener.db
ssh root@cyber.keltonshockey.com 'ls -l /opt/cyberscreener/data/cyberscreener.db'           # unchanged size/mtime
```

The same enforcement is proven offline + repeatably by `make test`
(`api/tests/test_narrative_sync_wrapper.py`, 9 cases) and was verified end-to-end
locally via a real rsync-through-wrapper loopback (a redirect to `cyberscreener.db`
landed at `narratives.db`; no other file was created). See the result file.

---

## 5. Schedule (only after steps 2–4 pass)

```
cp ~/cyberscreener/scripts/mill/com.mill.cs-narrative-sync.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.mill.cs-narrative-sync.plist
```

Runs every 15 min; the hash-compare makes it a cheap no-op when nothing changed.
Alternatively (or additionally) have the part-2 pipeline call
`push_narratives.sh` right after it writes, making this timer a backstop.

---

## 6. Rollback (zero prod impact)

The file is regenerable and the router degrades gracefully, so rollback is just a delete:

```
ssh root@cyber.keltonshockey.com 'rm -f /opt/cyberscreener/data/narratives/narratives.db'
```

The router then returns HTTP 202 `{"status":"generating"}` for every ticker and the
Ticker page shows the quiet "Generating narrative…" placeholder. Nothing else is
affected — no scoring, no journal, no other service. To stop deliveries entirely:

```
launchctl unload ~/Library/LaunchAgents/com.mill.cs-narrative-sync.plist   # stop the timer
ssh root@cyber.keltonshockey.com 'sudo rm -f /home/narrative/.ssh/authorized_keys'   # revoke the key
```

---

## Network-safety (hard rule #6) — clean

The delivery is an **outbound** rsync from mill over the **existing** ssh path
(port 22) to the droplet, plus an outbound HTTPS Pushover call on failure. It adds
**no new listener** on the droplet, and makes **no bind-address / mDNS / firewall**
change. The droplet gains one `authorized_keys` entry (a credential, not a network
surface) under an unprivileged user. No inbound surface is opened.

---

## Documented alternative (if the forced-command key is ever judged unclean)

Invert the trust: put the droplet on the tailnet and have a **droplet-side** cron
*pull* `narratives.db` from mill (mill serves it read-only over Tailscale, like
LiteLLM/n8n). Then mill never holds any prod write path at all — the droplet pulls.
Tradeoff: this is a **network change** (the droplet joins the tailnet), so it must
clear the hard-rule-#6 gate first (a new interface/listener consideration), and it
adds Tailscale as a dependency on the prod box. The forced-command key above is the
lighter-touch option (no network change, no new daemon on prod) and is verified
locked-down, so it is the recommended default; this pull model is the fallback if
the boundary review prefers zero mill-initiated prod writes. **Kelton picks.**
