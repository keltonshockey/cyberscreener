"""
Proof that the narrative-sync forced-command key can do NOTHING but drop the one
file (bin/narrative-rsync-only.sh). We drive the wrapper directly with the exact
$SSH_ORIGINAL_COMMAND values sshd would expose, in DRYRUN mode (writes nothing),
and assert accept/reject + that the destination is always hard-pinned to
narratives.db — never cyberscreener.db, never anywhere else.
"""
import os
import subprocess

WRAPPER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "bin", "narrative-rsync-only.sh")
)
PINNED = "/opt/cyberscreener/data/narratives/narratives.db"


def _run(orig_cmd):
    env = dict(os.environ)
    env["NARRATIVE_RSYNC_DRYRUN"] = "1"
    env["SSH_ORIGINAL_COMMAND"] = orig_cmd
    env["NARRATIVE_RSYNC_LOG"] = "/dev/null"
    return subprocess.run(
        ["/bin/bash", WRAPPER], env=env, capture_output=True, text=True
    )


# ── Accepts: only a well-formed rsync receive ─────────────────────────────────

def test_accepts_normal_rsync_push():
    r = _run("rsync --server -vlogDtpre.iLsfxC . narratives.db")
    assert r.returncode == 0
    assert r.stdout.strip() == f"rsync --server -vlogDtpre.iLsfxC . {PINNED}"


def test_accepts_rsync_push_without_flag_token():
    r = _run("rsync --server . narratives.db")
    assert r.returncode == 0
    # collapse whitespace (no flag token => an empty slot in the echoed line)
    assert " ".join(r.stdout.split()) == f"rsync --server . {PINNED}"


# ── The pin: client cannot choose the destination ─────────────────────────────

def test_destination_is_pinned_even_if_client_asks_for_prod_db():
    # client tries to land bytes on the production DB; wrapper overrides the dest
    r = _run("rsync --server -vlogDtpre.iLsfxC . /opt/cyberscreener/data/cyberscreener.db")
    assert r.returncode == 0
    assert PINNED in r.stdout
    assert "cyberscreener.db\n" not in r.stdout  # the prod db is never the target
    assert r.stdout.strip().endswith(PINNED)


# ── Rejects: everything that is not that one push ─────────────────────────────

def test_rejects_empty_command_shell_attempt():
    assert _run("").returncode != 0


def test_rejects_arbitrary_shell_command():
    r = _run("cat /opt/cyberscreener/data/cyberscreener.db")
    assert r.returncode != 0


def test_rejects_scp():
    assert _run("scp -t /opt/cyberscreener/data/narratives/narratives.db").returncode != 0


def test_rejects_sender_mode_exfil():
    # --sender would make the droplet READ a file out to the client
    r = _run("rsync --server --sender -vlogDtpre . /opt/cyberscreener/data/cyberscreener.db")
    assert r.returncode != 0


def test_rejects_dangerous_options():
    for opt in (
        "rsync --server --remove-source-files -vlog . narratives.db",
        "rsync --server -vlog --inplace . narratives.db",
        "rsync --server --daemon . narratives.db",
        "rsync --server -e ssh . narratives.db",
    ):
        assert _run(opt).returncode != 0, opt


def test_rejects_command_chaining():
    assert _run("rsync --server -vlog . narratives.db; rm -rf /").returncode != 0


# ── Delivery-consistency: store default == this wrapper's pinned destination ──

def test_store_default_path_matches_wrapper_pinned_destination():
    # The whole point of the narratives-ops reconcile: the router's default
    # narratives.db location and this wrapper's hard-pinned rsync destination are
    # ONE constant, so prod serves the delivered file with no systemd drop-in.
    from db.narratives import CANONICAL_NARRATIVES_DB
    assert CANONICAL_NARRATIVES_DB == PINNED
