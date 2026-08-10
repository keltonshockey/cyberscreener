"""
Proof that the evidence-sync forced-command key can do NOTHING but drop the
weekly artifacts (bin/evidence-rsync-only.sh). Mirrors the narrative wrapper's
adversarial DRYRUN suite - we drive the wrapper directly with the exact
$SSH_ORIGINAL_COMMAND values sshd would expose, in DRYRUN mode (writes
nothing), and assert accept/reject + that the destination is always
hard-pinned to /opt/cyberscreener/data/evidence/ - never cyberscreener.db,
never anywhere else.

Beyond the narrative suite, this wrapper is stricter and the NEW cases prove
it: a traversal-shaped destination ('..' anywhere) is REJECTED outright rather
than silently redirected, an -R/--relative smuggle in the short-flag token is
rejected, and receiver-side write-redirect options (--log-file, --backup-dir,
--temp-dir, --partial-dir, --chmod/--chown, --mkpath) are refused. The
permitted plain push still passes - both directions are proven.
"""
import os
import subprocess

WRAPPER = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "bin", "evidence-rsync-only.sh")
)
PINNED_DIR = "/opt/cyberscreener/data/evidence/"


def _run(orig_cmd):
    env = dict(os.environ)
    env["EVIDENCE_RSYNC_DRYRUN"] = "1"
    env["SSH_ORIGINAL_COMMAND"] = orig_cmd
    env["EVIDENCE_RSYNC_LOG"] = "/dev/null"
    return subprocess.run(
        ["/bin/bash", WRAPPER], env=env, capture_output=True, text=True
    )


# -- Accepts: only a well-formed rsync receive --------------------------------

def test_accepts_normal_rsync_push():
    r = _run("rsync --server -vlogDtpre.iLsfxC . evidence/")
    assert r.returncode == 0
    assert r.stdout.strip() == f"rsync --server -vlogDtpre.iLsfxC . {PINNED_DIR}"


def test_accepts_rsync_push_without_flag_token():
    r = _run("rsync --server . evidence/")
    assert r.returncode == 0
    assert " ".join(r.stdout.split()) == f"rsync --server . {PINNED_DIR}"


# -- The pin: client cannot choose the destination ----------------------------

def test_destination_is_pinned_even_if_client_asks_for_prod_db():
    r = _run("rsync --server -vlogDtpre.iLsfxC . /opt/cyberscreener/data/cyberscreener.db")
    assert r.returncode == 0
    assert PINNED_DIR in r.stdout
    assert "cyberscreener.db" not in r.stdout
    assert r.stdout.strip().endswith(PINNED_DIR)


def test_destination_is_pinned_even_if_client_asks_for_narratives():
    # The evidence key must not be able to reach the narrative lane's file.
    r = _run("rsync --server -vlogDtpre.iLsfxC . /opt/cyberscreener/data/narratives/narratives.db")
    assert r.returncode == 0
    assert "narratives" not in r.stdout
    assert r.stdout.strip().endswith(PINNED_DIR)


# -- Rejects: everything that is not that one push ----------------------------

def test_rejects_empty_command_shell_attempt():
    assert _run("").returncode != 0


def test_rejects_arbitrary_shell_command():
    assert _run("cat /opt/cyberscreener/data/cyberscreener.db").returncode != 0


def test_rejects_scp():
    assert _run("scp -t /opt/cyberscreener/data/evidence/x.md").returncode != 0


def test_rejects_sender_mode_exfil():
    # --sender would make the droplet READ files out to the client
    r = _run("rsync --server --sender -vlogDtpre . /opt/cyberscreener/data/evidence/")
    assert r.returncode != 0


def test_rejects_dangerous_options():
    for opt in (
        "rsync --server --remove-source-files -vlog . evidence/",
        "rsync --server -vlog --inplace . evidence/",
        "rsync --server --daemon . evidence/",
        "rsync --server -e ssh . evidence/",
        "rsync --server --files-from=/etc/passwd -vlog . evidence/",
    ):
        assert _run(opt).returncode != 0, opt


def test_rejects_command_chaining():
    assert _run("rsync --server -vlog . evidence/; rm -rf /").returncode != 0


def test_rejects_unexpected_long_option_token():
    assert _run("rsync --server --verbose . evidence/").returncode != 0


# -- NEW adversarial cases (not in the narrative suite) -----------------------

def test_NEW_rejects_path_traversal_destination():
    """A '..'-shaped destination is refused outright, not silently redirected.

    The narrative wrapper would have accepted this line (discarding the path);
    this wrapper treats a traversal-shaped request as hostile and exits 1.
    """
    r = _run("rsync --server -vlogDtpre.iLsfxC . ../../etc")
    assert r.returncode != 0
    assert "rejected" in r.stderr
    assert PINNED_DIR not in r.stdout  # no accept line was printed


def test_NEW_rejects_dotdot_anywhere_in_line():
    for line in (
        "rsync --server -vlog . evidence/../../root/.ssh/authorized_keys",
        "rsync --server -vlog . /opt/cyberscreener/data/evidence/../db",
    ):
        assert _run(line).returncode != 0, line


def test_NEW_rejects_relative_flag_smuggled_in_short_token():
    """-R (--relative) inside the negotiated flag token would let sender-side
    paths re-enter the receive; the narrative wrapper forwarded the token
    unexamined beyond its shape, this one refuses R explicitly."""
    r = _run("rsync --server -vlogDtprRe.iLsfxC . evidence/")
    assert r.returncode != 0
    assert "rejected" in r.stderr


def test_NEW_rejects_write_redirect_option_smuggling():
    """Options that make the receiver write somewhere other than the pin
    (none of these appear in the narrative wrapper's deny list)."""
    for opt in (
        "rsync --server --log-file=/etc/cron.d/evil -vlog . evidence/",
        "rsync --server --backup-dir=/opt/cyberscreener -vlog . evidence/",
        "rsync --server --temp-dir=/tmp -vlog . evidence/",
        "rsync --server --partial-dir=/var/www -vlog . evidence/",
        "rsync --server --chmod=777 -vlog . evidence/",
        "rsync --server --chown=root:root -vlog . evidence/",
        "rsync --server --mkpath -vlog . evidence/",
        "rsync --server --relative -vlog . evidence/",
    ):
        assert _run(opt).returncode != 0, opt


def test_NEW_failing_direction_proof_plain_form_still_passes():
    """The rejections above are not a wrapper that rejects everything: the
    exact client line push_evidence.sh produces is still accepted, and lands
    in the pinned directory."""
    r = _run("rsync --server -vlogDtpre.iLsfxC . evidence/")
    assert r.returncode == 0
    assert r.stdout.strip().endswith(PINNED_DIR)


# -- Delivery-consistency: router default == wrapper's pinned destination -----

def test_router_default_dir_matches_wrapper_pinned_destination():
    from core.evidence_artifacts import DEFAULT_EVIDENCE_DIR
    assert DEFAULT_EVIDENCE_DIR.rstrip("/") == PINNED_DIR.rstrip("/")


def test_wrapper_dest_env_override_is_respected_for_tests():
    env = dict(os.environ)
    env.update({
        "EVIDENCE_RSYNC_DRYRUN": "1",
        "SSH_ORIGINAL_COMMAND": "rsync --server -vlog . evidence/",
        "EVIDENCE_RSYNC_LOG": "/dev/null",
        "EVIDENCE_DEST_DIR": "/tmp/ev-test",
    })
    r = subprocess.run(["/bin/bash", WRAPPER], env=env,
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert r.stdout.strip().endswith("/tmp/ev-test/")
