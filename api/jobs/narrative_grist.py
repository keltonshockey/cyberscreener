"""
Grist LLM client for the narrative pipeline — the ONE outbound model call.

Local model only by default (`gemma3` via the mill LiteLLM gateway, an
OpenAI-compatible `/v1/chat/completions` endpoint). A `claude-*` model is refused
unless the caller explicitly opts in (the `--escalate` path, one ticker). This is
the moat rule (legal/finance stays on-box) + the token-budget guarantee.

stdlib only (urllib) — no third-party HTTP dependency.
"""

import os
import json
import ssl
import urllib.request
import urllib.error

DEFAULT_LITELLM_BASE = "https://mill.tail239400.ts.net:8443"
DEFAULT_MODEL = "gemma3"
DEFAULT_SECRETS_PATH = os.path.expanduser("~/.config/grist/mill-secrets.env")

# Key names we will accept out of mill-secrets.env, in priority order.
_KEY_CANDIDATES = (
    "MILL_LITELLM_KEY", "LITELLM_MASTER_KEY", "LITELLM_API_KEY",
    "LITELLM_KEY", "OPENAI_API_KEY",
)


def load_mill_secrets(path: str = DEFAULT_SECRETS_PATH) -> dict:
    """Parse a KEY=VALUE env file. Returns {} if absent/unreadable (defensive —
    the caller decides whether a missing key is fatal)."""
    out: dict = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                out[k.strip()] = v.strip().strip('"').strip("'")
    except OSError:
        return {}
    return out


def resolve_key(secrets: dict | None = None) -> str | None:
    """Find the LiteLLM key: explicit env var wins, then the secrets file."""
    for name in _KEY_CANDIDATES:
        if os.environ.get(name):
            return os.environ[name]
    secrets = secrets if secrets is not None else load_mill_secrets()
    for name in _KEY_CANDIDATES:
        if secrets.get(name):
            return secrets[name]
    return None


def resolve_model(escalate: bool = False, model: str | None = None) -> str:
    """The model to use. Without --escalate this is ALWAYS the local default;
    a claude-* model is only permitted on the explicit escalate path."""
    if not escalate:
        return DEFAULT_MODEL
    chosen = model or "claude-sonnet"
    return chosen


def _is_claude(model: str) -> bool:
    return model.lower().startswith("claude")


def call_grist(
    messages: list,
    model: str = DEFAULT_MODEL,
    *,
    escalate: bool = False,
    base: str | None = None,
    key: str | None = None,
    temperature: float = 0.2,
    max_tokens: int = 700,
    timeout: int = 90,
) -> str:
    """Single chat-completions call. Returns the assistant message content.

    REFUSES a claude-* model unless `escalate=True` — this guard is the moat /
    token rule and is enforced here so no code path can bypass it.
    """
    if _is_claude(model) and not escalate:
        raise PermissionError(
            f"refusing claude model {model!r} without --escalate (local-only by default)"
        )

    base = (base or os.environ.get("MILL_LITELLM_BASE") or DEFAULT_LITELLM_BASE).rstrip("/")
    key = key or resolve_key()
    if not key:
        raise RuntimeError(
            "no LiteLLM key — set MILL_LITELLM_KEY or populate ~/.config/grist/mill-secrets.env"
        )

    payload = json.dumps({
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    req = urllib.request.Request(
        f"{base}/v1/chat/completions",
        data=payload,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {key}",
        },
        method="POST",
    )
    # The mill gateway presents a tailnet cert; verify normally. Callers on the
    # tailnet trust it. (No verification downgrade — outbound-only, no secrets leak.)
    ctx = ssl.create_default_context()
    with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body["choices"][0]["message"]["content"]
