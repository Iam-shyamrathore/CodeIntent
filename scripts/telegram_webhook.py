"""Point the Telegram bot at this deployment's webhook and register its command menu.

TELEGRAM_BOT_TOKEN=... TELEGRAM_WEBHOOK_SECRET=... python -m scripts.telegram_webhook

Uses setWebhook (url, secret_token, allowed_updates=["message"]) and setMyCommands, then prints
getWebhookInfo. Neither the token nor the secret is printed.
"""

from __future__ import annotations

import json
import os
import re
import sys

from codeintent import telegram

DEFAULT_API = "https://codeintent-api-ded80aad7f4b.herokuapp.com"
COMMANDS = [
    {
        "command": "status",
        "description": "Repositories and the newest breaking pull requests",
    },
    {"command": "why", "description": "Latest verdict for a package, e.g. /why httpx"},
    {"command": "link", "description": "Link this chat with a code from the dashboard"},
    {"command": "unlink", "description": "Stop alerts in this chat"},
]


def main() -> int:
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    if not os.getenv("TELEGRAM_BOT_TOKEN"):
        print("Set TELEGRAM_BOT_TOKEN first.", file=sys.stderr)
        return 2
    # Bot API: secret_token is 1-256 characters of A-Z, a-z, 0-9, _ and -.
    if not re.fullmatch(r"[A-Za-z0-9_-]{32,256}", secret):
        print(
            "Set TELEGRAM_WEBHOOK_SECRET to 32-256 characters of A-Z a-z 0-9 _ - "
            "(python3 -c 'import secrets; print(secrets.token_urlsafe(48))').",
            file=sys.stderr,
        )
        return 2
    base = (os.getenv("CODEINTENT_API_PUBLIC_URL") or DEFAULT_API).rstrip("/")
    url = f"{base}/telegram/webhook"
    if not url.startswith("https://"):
        print("The webhook URL must use HTTPS.", file=sys.stderr)
        return 2
    try:
        me = telegram.call("getMe")
        telegram.call(
            "setWebhook",
            {
                "url": url,
                "secret_token": secret,
                "allowed_updates": ["message"],
                "drop_pending_updates": True,
            },
        )
        telegram.call("setMyCommands", {"commands": COMMANDS})
        info = telegram.call("getWebhookInfo")
    except telegram.TelegramError as exc:
        print(f"Telegram rejected the request: {exc}", file=sys.stderr)
        return 1
    username = (me or {}).get("username") if isinstance(me, dict) else None
    configured = telegram.bot_username()
    if username and configured and username.lower() != configured.lower():
        print(
            f"Warning: the token belongs to @{username}, but TELEGRAM_BOT_USERNAME is @{configured}.",
            file=sys.stderr,
        )
    # getWebhookInfo never returns the secret token; print only these fields regardless.
    keep = (
        "url",
        "has_custom_certificate",
        "pending_update_count",
        "max_connections",
        "allowed_updates",
        "last_error_date",
        "last_error_message",
        "ip_address",
    )
    shown = {k: info[k] for k in keep if isinstance(info, dict) and k in info}
    print(json.dumps({"bot": username, "webhook": shown}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
