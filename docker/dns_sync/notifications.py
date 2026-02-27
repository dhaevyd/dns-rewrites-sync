"""Webhook and email notifications"""

import logging
import os
import smtplib
from datetime import datetime, timezone
from email.message import EmailMessage

import requests

logger = logging.getLogger(__name__)

# Discord embed colours
_RED = 0xE74C3C
_ORANGE = 0xE67E22


def notify_sync_failed(server_name: str, server_type: str, error: str):
    subject = f"[dns-sync] Sync failed: {server_name}"
    body = (
        f"Sync failed for spoke: {server_name} ({server_type})\n"
        f"Error: {error}\n"
        f"Time: {_now()} UTC"
    )
    _dispatch(subject, body, color=_RED)


def notify_hub_unreachable(hub_name: str, hub_type: str, error: str):
    subject = f"[dns-sync] Hub unreachable: {hub_name}"
    body = (
        f"Hub server is unreachable: {hub_name} ({hub_type})\n"
        f"Error: {error}\n"
        f"Time: {_now()} UTC"
    )
    _dispatch(subject, body, color=_ORANGE)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _dispatch(subject: str, body: str, color: int):
    discord_url = os.environ.get("DNS_SYNC_DISCORD_WEBHOOK_URL", "")
    smtp_host = os.environ.get("DNS_SYNC_SMTP_HOST", "")
    smtp_to = os.environ.get("DNS_SYNC_SMTP_TO", "")
    if discord_url:
        _send_discord(discord_url, subject, body, color)
    if smtp_host and smtp_to:
        _send_email(subject, body)


def _send_discord(url: str, title: str, description: str, color: int):
    payload = {
        "embeds": [{
            "title": title,
            "description": description,
            "color": color,
            "timestamp": _now(),
        }]
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
    except Exception as e:
        logger.error("Discord notification failed: %s", e)


def _send_email(subject: str, body: str):
    smtp_host = os.environ.get("DNS_SYNC_SMTP_HOST", "")
    smtp_port = int(os.environ.get("DNS_SYNC_SMTP_PORT", "587"))
    smtp_user = os.environ.get("DNS_SYNC_SMTP_USER", "")
    smtp_password = os.environ.get("DNS_SYNC_SMTP_PASSWORD", "")
    smtp_from = os.environ.get("DNS_SYNC_SMTP_FROM", "") or smtp_user
    smtp_to = os.environ.get("DNS_SYNC_SMTP_TO", "")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp_from
    msg["To"] = smtp_to
    msg.set_content(body)
    try:
        with smtplib.SMTP(smtp_host, smtp_port) as smtp:
            smtp.starttls()
            if smtp_user and smtp_password:
                smtp.login(smtp_user, smtp_password)
            smtp.send_message(msg)
    except Exception as e:
        logger.error("Email notification failed: %s", e)
