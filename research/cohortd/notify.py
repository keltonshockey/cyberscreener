"""
Pushover notification for cohort D entries and settlements.

The RETURN VALUE MATTERS. OPERATIONS_PLAYBOOK §9b records three sibling scripts
that piped Pushover's reply to /dev/null and would therefore have logged "alert
sent" for an alert that went nowhere. RESULT_R2_IC_HARNESS inherited that lesson;
this module keeps it. Callers log `accepted` / `NOT ACCEPTED` from the boolean.

Outbound only, over the existing Pushover path. No listener.
"""

from __future__ import annotations

import os
import sys
import urllib.parse
import urllib.request

ENDPOINT = "https://api.pushover.net/1/messages.json"
MAX_BODY = 900          # Pushover truncates ~1024; keep the head, which carries the verdict


def send(message: str) -> bool:
    """
    Send `message`. Returns True only on a confirmed HTTP 200.

    Missing keys, a dead network and a non-200 all return False rather than
    raising: by the time a notification is attempted the cycle is already
    recorded in the database, and crashing here would obscure a completed run.
    """
    token, user = os.environ.get("PUSHOVER_TOKEN"), os.environ.get("PUSHOVER_USER")
    if not token or not user:
        print("pushover: PUSHOVER_TOKEN/PUSHOVER_USER not set — skipped", file=sys.stderr)
        return False
    data = urllib.parse.urlencode(
        {"token": token, "user": user, "message": message[:MAX_BODY]}).encode()
    try:
        with urllib.request.urlopen(urllib.request.Request(ENDPOINT, data=data),
                                    timeout=15) as resp:
            return resp.status == 200
    except Exception as exc:
        print(f"pushover: send failed ({type(exc).__name__}: {exc})", file=sys.stderr)
        return False


def notify_and_log(message: str, *, dry_run: bool = False) -> bool:
    """Send and print the accepted / NOT ACCEPTED line the runbook checks for."""
    if dry_run:
        print(f"pushover: DRY-RUN, not sent — would send: {message[:120]}")
        return False
    ok = send(message)
    print(f"pushover: {'accepted' if ok else 'NOT ACCEPTED'}")
    return ok
