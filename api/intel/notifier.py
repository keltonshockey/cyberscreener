"""
Augur Notifier — Email alerts for momentum events and high-RC plays.

Uses SendGrid's free HTTPS API (no SMTP — avoids VPS firewall blocks).
Free tier: 100 emails/day.

Setup (VPS systemd service env vars):
  ALERT_EMAIL_TO       = recipient address (e.g. you@gmail.com)
  ALERT_EMAIL_FROM     = verified sender address (e.g. augur.alerts@gmail.com)
  SENDGRID_API_KEY     = API key from app.sendgrid.com → Settings → API Keys

SendGrid setup:
  1. Sign up at https://sendgrid.com (free — 100 emails/day)
  2. Verify your sender email: Settings → Sender Authentication → Single Sender
  3. Create API key: Settings → API Keys → Create API Key (Mail Send permission)
  4. Add env vars to VPS systemd service

If any of the three env vars are missing, notifications are silently skipped
(no errors, no impact on scanning).

Dedup: each (ticker, alert_type) pair is only emailed once per calendar day.
"""

import os
import json
import logging
import requests
from datetime import datetime

logger = logging.getLogger(__name__)

_TO      = os.environ.get("ALERT_EMAIL_TO", "")
_FROM    = os.environ.get("ALERT_EMAIL_FROM", "")
_SG_KEY  = os.environ.get("SENDGRID_API_KEY", "")
_ENABLED = bool(_TO and _FROM and _SG_KEY)

_SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"

# In-process dedup: "CRWD_momentum" → "2026-02-24"
_sent_today: dict = {}


def _is_fresh(ticker: str, alert_type: str) -> bool:
    """Return True if this alert hasn't been sent today for this ticker+type."""
    key = f"{ticker}_{alert_type}"
    today = datetime.now().strftime("%Y-%m-%d")
    if _sent_today.get(key) == today:
        return False
    _sent_today[key] = today
    return True


def _send(subject: str, html_body: str) -> bool:
    """Send an HTML email via SendGrid API. Returns True on success."""
    if not _ENABLED:
        return False
    try:
        payload = {
            "personalizations": [{"to": [{"email": _TO}]}],
            "from": {"email": _FROM, "name": "Augur Intelligence"},
            "subject": subject,
            "content": [{"type": "text/html", "value": html_body}],
        }
        resp = requests.post(
            _SENDGRID_URL,
            headers={
                "Authorization": f"Bearer {_SG_KEY}",
                "Content-Type": "application/json",
            },
            data=json.dumps(payload),
            timeout=15,
        )
        if resp.status_code in (200, 202):
            logger.info(f"📧 Email sent: {subject}")
            return True
        else:
            logger.warning(f"Email send failed: {resp.status_code} {resp.text[:200]}")
            return False
    except Exception as e:
        logger.warning(f"Email send failed ({type(e).__name__}): {e}")
        return False


def _html_header(title: str) -> str:
    return f"""
    <div style="font-family:system-ui,sans-serif;max-width:600px;margin:0 auto">
    <div style="background:#1d1d1f;padding:16px 24px;border-radius:10px 10px 0 0">
      <span style="color:#fff;font-size:18px;font-weight:700">⬡ Augur</span>
      <span style="color:#86868b;font-size:13px;margin-left:12px">{title}</span>
    </div>
    <div style="border:1px solid #e5e5ea;border-top:none;border-radius:0 0 10px 10px;padding:20px 24px">
    """


def _html_footer() -> str:
    return f"""
    </div>
    <p style="font-size:11px;color:#aeaeb2;text-align:center;margin-top:12px">
      Augur Intelligence · {datetime.now().strftime("%Y-%m-%d %H:%M")} UTC
    </p></div>
    """


# ─── Public API ───────────────────────────────────────────────────────────────

def notify_momentum_digest(events: list) -> bool:
    """
    Send a digest email for score momentum events from a scan.
    events = [{ticker, score_type, delta, old_score, new_score, text, impact}, ...]
    Filters to only events not yet sent today. Returns True if email was sent.
    """
    if not events:
        return False

    fresh = [e for e in events if _is_fresh(e["ticker"], "momentum")]
    if not fresh:
        return False

    gainers = [e for e in fresh if e.get("impact") == "positive"]
    losers  = [e for e in fresh if e.get("impact") == "negative"]

    def make_rows(evts, color):
        return "".join(
            f'<tr>'
            f'<td style="padding:8px 12px;font-weight:700;font-family:monospace">{e["ticker"]}</td>'
            f'<td style="padding:8px 12px;color:#86868b">{e.get("score_type","").upper()}</td>'
            f'<td style="padding:8px 12px;font-weight:700;color:{color}">'
            f'{"+" if e["delta"]>0 else ""}{e["delta"]:.0f} pts</td>'
            f'<td style="padding:8px 12px">{e["old_score"]:.0f} → {e["new_score"]:.0f}</td>'
            f'<td style="padding:8px 12px;color:#86868b;font-size:12px">{e.get("text","")}</td>'
            f'</tr>'
            for e in evts
        )

    table_style = 'style="width:100%;border-collapse:collapse;font-size:13px"'
    thead = (
        '<thead><tr style="background:#f5f5f7">'
        '<th style="padding:8px 12px;text-align:left">Ticker</th>'
        '<th style="padding:8px 12px;text-align:left">Type</th>'
        '<th style="padding:8px 12px;text-align:left">Change</th>'
        '<th style="padding:8px 12px;text-align:left">Scores</th>'
        '<th style="padding:8px 12px;text-align:left">Detail</th>'
        '</tr></thead>'
    )

    body = _html_header("Score Momentum Alert")
    body += f'<p style="font-size:14px;margin-bottom:16px"><b>{len(fresh)}</b> significant score change(s) detected:</p>'

    if gainers:
        body += '<p style="color:#34c759;font-weight:700;margin:12px 0 6px">📈 Gainers</p>'
        body += f'<table {table_style}>{thead}<tbody>{make_rows(gainers, "#34c759")}</tbody></table>'

    if losers:
        body += '<p style="color:#ff3b30;font-weight:700;margin:16px 0 6px">📉 Losers</p>'
        body += f'<table {table_style}>{thead}<tbody>{make_rows(losers, "#ff3b30")}</tbody></table>'

    body += _html_footer()

    subject = f"Augur: {len(fresh)} Momentum Event{'s' if len(fresh)!=1 else ''}"
    if gainers:
        subject += f" — 📈 {', '.join(e['ticker'] for e in gainers[:3])}"
    return _send(subject, body)


def notify_high_rc_play(ticker: str, play: dict, rc_score: int) -> bool:
    """
    Send an alert for a single high-RC options play (RC ≥ 80).
    Deduped per ticker+expiry per day.
    """
    expiry = play.get("expiry", "")
    if not _is_fresh(ticker, f"rc_{expiry}"):
        return False

    rc_color = "#34c759" if rc_score >= 80 else "#ff9500"
    direction = play.get("direction", "")
    dir_color = "#34c759" if "bull" in direction.lower() else "#ff3b30" if "bear" in direction.lower() else "#007aff"

    def row(label, val):
        return (
            f'<tr>'
            f'<td style="padding:7px 12px;color:#86868b;font-size:12px;width:120px">{label}</td>'
            f'<td style="padding:7px 12px;font-size:13px">{val}</td>'
            f'</tr>'
        )

    body = _html_header(f"High-Quality Play: {ticker}")
    body += f'''
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:20px">
      <div style="font-size:32px;font-weight:800;font-family:monospace;color:#1d1d1f">{ticker}</div>
      <div style="padding:8px 16px;background:{rc_color}18;border-radius:10px;
                  border:1px solid {rc_color}40;font-size:22px;font-weight:800;color:{rc_color}">
        {rc_score}/100
      </div>
      <div style="font-size:13px;font-weight:600;color:{dir_color}">{direction}</div>
    </div>
    <table style="width:100%;border-collapse:collapse;border:1px solid #e5e5ea;border-radius:8px">
      <tbody>
        {row("Strategy", play.get("strategy","—"))}
        {row("Strike", f"${play.get('strike','—')}")}
        {row("Expiry", expiry or "—")}
        {row("DTE", f"{play.get('dte','—')} days")}
        {row("Action", play.get("action","—"))}
        {row("Entry Price", f"${play.get('entry_price', play.get('ask','—'))}")}
        {row("Max Loss", f"${play.get('max_loss','—')}")}
        {row("Max Gain", play.get("max_gain","—"))}
      </tbody>
    </table>
    '''
    if play.get("rationale"):
        body += f'<p style="font-size:12px;color:#86868b;margin-top:16px;line-height:1.6">{play["rationale"]}</p>'
    body += _html_footer()

    subject = f"Augur ⚡ {ticker} {play.get('strategy','')} — RC {rc_score}/100"
    return _send(subject, body)


def test_email() -> bool:
    """Send a test email to verify SendGrid config is working."""
    body = _html_header("Test Email")
    body += '<p style="font-size:14px">✅ Augur email notifications are working correctly.</p>'
    body += _html_footer()
    return _send("Augur: Email Test", body)
