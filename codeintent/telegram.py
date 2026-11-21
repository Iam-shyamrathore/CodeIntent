"""Telegram bot: link a chat to a GitHub App installation, answer /status and /why, push alerts.

Talks to the Bot API directly (https://core.telegram.org/bots/api) with JSON POSTs. Messages use
``parse_mode=HTML``: every piece of data is escaped (``<``, ``>``, ``&``, quotes) and only the
``b``, ``i``, ``code`` and ``a`` tags are produced. The bot token never appears in logs or
exceptions: the request URL embeds it, so transport errors are re-raised by category only.
"""

from __future__ import annotations

import hashlib
import html
import logging
import os
import re
import secrets
import time
from datetime import datetime

import httpx

from codeintent import store

logger = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org"
MAX_MESSAGE = 4096
"""sendMessage accepts 1-4096 characters after entity parsing; the raw HTML is held to this too."""
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
"""No 0/O, 1/I/L: the code is read off a screen and typed."""
CODE_LENGTH = 8
CODE_MINUTES = 15
LABELS = {
    "breaks": "Breaks you",
    "needs-change": "Needs a change",
    "not-checked": "Not checked",
    "no-known-impact": "No known impact",
}
ORDER = ["breaks", "not-checked", "needs-change", "no-known-impact"]
WHAT = {
    "removed": "removed",
    "parameter-removed": "no longer accepts this argument",
    "parameter-required": "now requires an argument you don't pass",
    "parameter-moved": "positional arguments changed order",
    "deprecated": "deprecated",
    "default-changed": "default changed",
}
"""Mirrors ``WHAT`` in codeintent/upgrades/report.py (not imported: it pulls in the analysis engine)."""
PACKAGE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9._-]{0,98}[A-Za-z0-9])?$")
HELP = (
    "<b>CodeIntent</b> posts dependency-upgrade verdicts on pull requests.\n\n"
    "/status: repositories and the newest breaking pull requests\n"
    "/why <i>package</i>: the latest verdict for a package\n"
    "/link <i>CODE</i>: link this chat to a workspace (code from the dashboard)\n"
    "/unlink: stop alerts in this chat"
)


class TelegramError(Exception):
    """A Bot API call failed. The message never contains the token or the request URL."""

    def __init__(
        self,
        message: str,
        code: int | None = None,
        retry_after: int | None = None,
        migrate_to: int | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.retry_after = retry_after
        self.migrate_to = migrate_to


def configured() -> bool:
    return bool(os.getenv("TELEGRAM_BOT_TOKEN") and bot_username())


def bot_username() -> str:
    return os.getenv("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")


def call(method: str, payload: dict | None = None, timeout: float = 15) -> object:
    """POST one Bot API method and return its ``result``."""
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise TelegramError("TELEGRAM_BOT_TOKEN is not set")
    failure = None
    try:
        response = httpx.post(
            f"{TELEGRAM_API}/bot{token}/{method}", json=payload or {}, timeout=timeout
        )
        body = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        # httpx errors carry the request URL, which contains the token: keep only the category.
        failure = f"{method} failed ({type(exc).__name__})"
    if failure:
        raise TelegramError(failure)
    if not isinstance(body, dict) or not body.get("ok"):
        body = body if isinstance(body, dict) else {}
        description = str(body.get("description") or f"HTTP {response.status_code}")
        parameters = body.get("parameters") or {}
        raise TelegramError(
            f"{method} failed: {description.replace(token, '<token>')[:300]}",
            code=body.get("error_code") or response.status_code,
            retry_after=parameters.get("retry_after"),
            migrate_to=parameters.get("migrate_to_chat_id"),
        )
    return body.get("result")


def send(chat_id: int, text: str) -> dict:
    """Send one HTML message; waits out one short flood-control pause (429 retry_after) if asked."""
    if not text or len(text) > MAX_MESSAGE:
        raise ValueError("Telegram messages must be 1-4096 characters")
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "link_preview_options": {"is_disabled": True},
    }
    try:
        return call("sendMessage", payload)
    except TelegramError as exc:
        if exc.code != 429 or not exc.retry_after or exc.retry_after > 10:
            raise
        time.sleep(exc.retry_after)
    return call("sendMessage", payload)


# --- rendering ---------------------------------------------------------------------------------


def esc(value: object, limit: int = 300) -> str:
    text = str(value if value is not None else "")
    if len(text) > limit:
        text = text[: limit - 1] + "…"
    return html.escape(text, quote=True)


def link(url: str | None, label: str) -> str:
    """``<a>`` for http(s) URLs only; anything else renders as the bare (escaped) label."""
    if not url or not re.match(r"^https?://[^\s<>\"']+$", url):
        return label
    return f'<a href="{html.escape(url, quote=True)}">{label}</a>'


def public_url(path: str = "") -> str | None:
    base = os.getenv("CODEINTENT_PUBLIC_URL", "").rstrip("/")
    return f"{base}{path}" if base else None


def pull_url(repository: str, number: int) -> str:
    return f"https://github.com/{repository}/pull/{number}"


def fit(blocks: list[str], more: str | None = None) -> str:
    """Join blocks; when they exceed one message, keep whole blocks and point to the dashboard."""
    body = "\n\n".join(b for b in blocks if b)
    if len(body) <= MAX_MESSAGE:
        return body
    tail = "\n\n<i>Truncated.</i> " + link(
        more or public_url("/dashboard"), "Open the dashboard"
    )
    kept = []
    for block in blocks:
        if len("\n\n".join(kept + [block])) + len(tail) > MAX_MESSAGE:
            break
        kept.append(block)
    if not kept:
        return tail.strip()[:MAX_MESSAGE]
    return "\n\n".join(kept) + tail


def symbol(change: dict) -> str:
    """``httpx.Client(proxies=)``: public path as users import it. Mirrors ``_target`` in report.py."""
    parts = str(change.get("symbol") or "").split(".")
    name = ".".join(
        p
        for i, p in enumerate(parts)
        if i == 0 or not p.startswith("_") or p.startswith("__")
    )
    return f"{name}({change['parameter']}=)" if change.get("parameter") else name


def decision_for(verdict: dict, finding: dict, index: int) -> dict | None:
    """The upstream decision behind a finding: matched by change key, else by position."""
    change = finding.get("change") or {}
    decisions = [d for d in verdict.get("decisions") or [] if isinstance(d, dict)]
    for decision in decisions:
        key = decision.get("change_key") or {}
        if (key.get("symbol"), key.get("parameter"), key.get("kind")) == (
            change.get("symbol"),
            change.get("parameter"),
            change.get("kind"),
        ):
            return decision
    return decisions[index] if index < len(decisions) else None


def target_advisories(verdict: dict) -> list[dict]:
    """Active (not withdrawn) advisories that affect the version the pull request moves to."""
    for check in verdict.get("advisories") or []:
        if (
            isinstance(check, dict)
            and check.get("version") == verdict.get("end")
            and check.get("status") == "advisories"
        ):
            return [
                a
                for a in check.get("advisories") or []
                if isinstance(a, dict) and not a.get("withdrawn")
            ]
    return []


def package_block(verdict: dict, findings: int = 3, places: int = 3) -> str:
    label = LABELS.get(verdict.get("verdict"), verdict.get("label") or "Verdict")
    lines = [
        f"<b>{esc(label)}</b>: <code>{esc(verdict.get('package'), 100)}</code> "
        f"{esc(verdict.get('start'), 40)} → {esc(verdict.get('end'), 40)}"
    ]
    reason = str(verdict.get("reason") or "")
    if reason:
        lines.append(esc(reason[0].upper() + reason[1:] + ".", 400))
    listed = [f for f in verdict.get("findings") or [] if isinstance(f, dict)]
    for index, finding in enumerate(listed[:findings]):
        change = finding.get("change") or {}
        what = WHAT.get(change.get("kind"), str(change.get("kind") or "changed"))
        if finding.get("guarded"):
            what += " (your import has a fallback)"
        lines.append(f"• <code>{esc(symbol(change), 160)}</code> {esc(what)}")
        spots = sorted(
            {
                (str(loc.get("file")), loc.get("line") or 0)
                for loc in finding.get("locations") or []
                if isinstance(loc, dict) and loc.get("file")
            }
        )
        if spots:
            shown = ", ".join(
                f"<code>{esc(f'{file}:{line}', 160)}</code>"
                for file, line in spots[:places]
            )
            more = f" and {len(spots) - places} more" if len(spots) > places else ""
            lines.append(f"  In your code: {shown}{more}")
        if change.get("replacement"):
            lines.append(
                f"  Use instead: <code>{esc(change['replacement'], 160)}</code>"
            )
        decision = decision_for(verdict, finding, index)
        if decision and decision.get("pr_url") and decision.get("pr_number"):
            title = f"#{decision['pr_number']} {decision.get('pr_title') or ''}".strip()
            lines.append(f"  Upstream: {link(decision['pr_url'], esc(title, 160))}")
    if len(listed) > findings:
        lines.append(f"<i>and {len(listed) - findings} more change(s)</i>")
    risky = target_advisories(verdict)
    if risky:
        shown = ", ".join(
            link(a.get("url"), esc(a.get("id"), 60))
            + (f" (fixed in {esc(a['fixed'], 40)})" if a.get("fixed") else "")
            for a in risky[:3]
        )
        more = f" and {len(risky) - 3} more" if len(risky) > 3 else ""
        lines.append(
            f"Known advisories for {esc(verdict.get('end'), 40)}: {shown}{more}"
        )
    return "\n".join(lines)


def verdict_list(row: dict) -> list[dict]:
    verdicts = row.get("verdicts")
    return (
        [v for v in verdicts if isinstance(v, dict)]
        if isinstance(verdicts, list)
        else []
    )


def alerting(verdict: dict) -> bool:
    return verdict.get("verdict") in {"breaks", "needs-change"} or bool(
        target_advisories(verdict)
    )


def alert_text(row: dict) -> str:
    verdicts = sorted(
        verdict_list(row),
        key=lambda v: (
            ORDER.index(v["verdict"]) if v.get("verdict") in ORDER else 9,
            str(v.get("package")),
        ),
    )
    title = f"#{row['number']} {row.get('title') or ''}".strip()
    report = public_url(f"/pulls/{row['id']}")
    head = (
        f"<b>{esc(row['repository'], 200)}</b>\n"
        f"{link(pull_url(row['repository'], row['number']), esc(title, 200))}"
    )
    blocks = [head]
    blocks += [package_block(v) for v in verdicts if alerting(v)]
    others = [v for v in verdicts if not alerting(v)]
    if others:
        blocks.append(
            "\n".join(
                f"{esc(LABELS.get(v.get('verdict'), v.get('label') or ''))}: <code>{esc(v.get('package'), 100)}</code> "
                f"{esc(v.get('start'), 40)} → {esc(v.get('end'), 40)}"
                for v in others[:10]
            )
        )
    if report:
        blocks.append(link(report, "Full report"))
    return fit(blocks, report)


# --- link codes --------------------------------------------------------------------------------


def _normalise(code: str) -> str:
    return re.sub(r"[\s-]", "", code).upper()


def _hash(code: str) -> str:
    return hashlib.sha256(_normalise(code).encode()).hexdigest()


def new_link_code(installation_id: int) -> dict:
    """A one-time code valid for 15 minutes; only its SHA-256 is stored. LookupError if unknown."""
    code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))
    with store.connection() as conn:
        if not conn.execute(
            "SELECT 1 FROM ci_installations WHERE id=%s AND deleted_at IS NULL",
            (installation_id,),
        ).fetchone():
            raise LookupError("installation")
        conn.execute(
            "DELETE FROM ci_telegram_links WHERE expires_at<now()-interval '1 day'"
        )
        row = conn.execute(
            """INSERT INTO ci_telegram_links(code_hash,installation_id,expires_at)
            VALUES (%s,%s,now()+make_interval(mins=>%s)) RETURNING expires_at""",
            (_hash(code), installation_id, CODE_MINUTES),
        ).fetchone()
    return {"code": code, "expires_at": row["expires_at"]}


def linked_chats(installation_id: int) -> list[dict]:
    with store.connection() as conn:
        return conn.execute(
            "SELECT title,linked_at FROM ci_telegram_chats WHERE installation_id=%s ORDER BY linked_at DESC",
            (installation_id,),
        ).fetchall()


# --- commands ----------------------------------------------------------------------------------


def _title(chat: dict) -> str:
    if chat.get("type") == "private":
        name = (
            f"@{chat['username']}"
            if chat.get("username")
            else chat.get("first_name") or "Private chat"
        )
        return f"Private chat with {name}"[:128]
    return str(chat.get("title") or chat.get("type") or "Chat")[:128]


def _linked(conn, chat_id: int) -> list[dict]:
    return conn.execute(
        """SELECT i.id,i.account_login FROM ci_telegram_chats c
        JOIN ci_installations i ON i.id=c.installation_id AND i.deleted_at IS NULL
        WHERE c.chat_id=%s ORDER BY lower(i.account_login),i.id""",
        (chat_id,),
    ).fetchall()


def link_chat(chat: dict, code: str) -> str:
    code = _normalise(code)
    if not re.fullmatch(f"[{CODE_ALPHABET}]{{{CODE_LENGTH}}}", code):
        return "That is not a link code. Create one on the CodeIntent dashboard, then send <code>/link CODE</code>."
    with store.connection() as conn:
        row = conn.execute(
            """UPDATE ci_telegram_links l SET used_at=now() FROM ci_installations i
            WHERE l.code_hash=%s AND l.used_at IS NULL AND l.expires_at>now()
              AND i.id=l.installation_id AND i.deleted_at IS NULL
            RETURNING l.installation_id,i.account_login""",
            (_hash(code),),
        ).fetchone()
        if not row:
            return "This code is unknown, already used or expired. Create a new one on the CodeIntent dashboard; codes last 15 minutes."
        conn.execute(
            """INSERT INTO ci_telegram_chats(chat_id,installation_id,title) VALUES (%s,%s,%s)
            ON CONFLICT(chat_id,installation_id) DO UPDATE SET title=EXCLUDED.title""",
            (chat["id"], row["installation_id"], _title(chat)),
        )
        from codeintent.tasks import notify_upcoming

        # Upcoming breakage already found before this chat was linked arrives right after the reply.
        notify_upcoming.configure(connection=conn, schedule_in={"seconds": 5}).defer(
            installation_id=row["installation_id"]
        )
    return (
        f"Linked to <b>{esc(row['account_login'], 100)}</b>. This chat will get an alert when a dependency "
        "pull request breaks your code, needs a change, or moves to a version with known advisories, "
        "and when a new release of something you use would break you.\n\n"
        "Try /status or /why <i>package</i>."
    )


def unlink_chat(chat_id: int) -> str:
    with store.connection() as conn:
        gone = conn.execute(
            "DELETE FROM ci_telegram_chats WHERE chat_id=%s RETURNING installation_id",
            (chat_id,),
        ).fetchall()
    if not gone:
        return "This chat is not linked to a workspace."
    return "Unlinked. This chat will get no more alerts. Link it again with a new code from the dashboard."


NOT_LINKED = (
    "This chat is not linked to a workspace yet. On the CodeIntent dashboard, choose "
    "<b>Connect Telegram</b> and send the code here with <code>/link CODE</code>."
)


def status(chat_id: int) -> str:
    with store.connection() as conn:
        homes = _linked(conn, chat_id)
        if not homes:
            return NOT_LINKED
        ids = [h["id"] for h in homes]
        repos = conn.execute(
            """SELECT r.installation_id,r.full_name,d.id,d.number,d.title,d.verdict
            FROM ci_installation_repositories r
            LEFT JOIN LATERAL (
              SELECT a.id,a.number,a.title,a.verdict FROM ci_pull_analyses a
              WHERE a.installation_id=r.installation_id AND a.repository=r.full_name AND a.verdict IS NOT NULL
              ORDER BY a.created_at DESC,a.id DESC LIMIT 1) d ON true
            WHERE r.installation_id=ANY(%s) ORDER BY lower(r.full_name) LIMIT 60""",
            (ids,),
        ).fetchall()
        breaking = conn.execute(
            """SELECT a.id,a.repository,a.number,a.title,a.verdicts FROM ci_pull_analyses a
            JOIN ci_installation_repositories r ON r.installation_id=a.installation_id AND r.full_name=a.repository
            WHERE a.installation_id=ANY(%s) AND a.verdict='breaks'
            ORDER BY a.created_at DESC,a.id DESC LIMIT 5""",
            (ids,),
        ).fetchall()
    blocks = []
    for home in homes:
        mine = [r for r in repos if r["installation_id"] == home["id"]]
        lines = [
            f"<b>{esc(home['account_login'], 100)}</b> · {len(mine)} repositor{'y' if len(mine) == 1 else 'ies'}"
        ]
        for repo in mine:
            if repo["id"]:
                title = f"#{repo['number']} {repo['title'] or ''}".strip()
                lines.append(
                    f"• {esc(repo['full_name'], 200)}: <b>{esc(LABELS.get(repo['verdict'], repo['verdict']))}</b> "
                    f"({link(public_url('/pulls/' + str(repo['id'])), esc(title, 120))})"
                )
            else:
                lines.append(f"• {esc(repo['full_name'], 200)}: no verdict yet")
        if not mine:
            lines.append("No repositories are selected for this installation.")
        blocks.append("\n".join(lines))
    if breaking:
        lines = ["<b>Newest “Breaks you” pull requests</b>"]
        for row in breaking:
            title = f"{row['repository']} #{row['number']} {row['title'] or ''}".strip()
            lines.append(
                f"• {link(pull_url(row['repository'], row['number']), esc(title, 200))}"
            )
            for v in verdict_list(row):
                if v.get("verdict") == "breaks":
                    lines.append(
                        f"  {esc(LABELS['breaks'])}: <code>{esc(v.get('package'), 100)}</code> "
                        f"{esc(v.get('start'), 40)} → {esc(v.get('end'), 40)}"
                    )
            report = public_url(f"/pulls/{row['id']}")
            if report:
                lines.append(f"  {link(report, 'Report')}")
        blocks.append("\n".join(lines))
    else:
        blocks.append("No “Breaks you” pull requests.")
    return fit(blocks)


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def why(chat_id: int, package: str) -> str:
    package = package.strip()
    if not package:
        return "Send <code>/why package</code>, for example <code>/why httpx</code>."
    if not PACKAGE.match(package):
        return "That is not a Python package name."
    wanted = canonical(package)
    with store.connection() as conn:
        homes = _linked(conn, chat_id)
        if not homes:
            return NOT_LINKED
        row = conn.execute(
            """SELECT a.id,a.repository,a.number,a.title,a.verdicts,a.created_at FROM ci_pull_analyses a
            JOIN ci_installation_repositories r ON r.installation_id=a.installation_id AND r.full_name=a.repository
            WHERE a.installation_id=ANY(%s) AND a.status='reported' AND EXISTS(
              SELECT 1 FROM jsonb_array_elements(
                CASE WHEN jsonb_typeof(a.verdicts)='array' THEN a.verdicts ELSE '[]'::jsonb END) v
              WHERE lower(regexp_replace(v->>'package','[-_.]+','-','g'))=%s)
            ORDER BY a.created_at DESC,a.id DESC LIMIT 1""",
            ([h["id"] for h in homes], wanted),
        ).fetchone()
    if not row:
        return f"No analysed pull request in the linked repositories changes <code>{esc(package, 100)}</code>."
    verdict = next(
        v for v in verdict_list(row) if canonical(str(v.get("package"))) == wanted
    )
    title = f"{row['repository']} #{row['number']} {row['title'] or ''}".strip()
    created = row["created_at"]
    when = f"{created.day} {created:%b %Y}" if isinstance(created, datetime) else ""
    blocks = [
        f"Latest verdict for <code>{esc(package, 100)}</code>: "
        f"{link(pull_url(row['repository'], row['number']), esc(title, 200))}"
        + (f" · {when}" if when else ""),
        package_block(verdict, findings=6, places=3),
    ]
    report = public_url(f"/pulls/{row['id']}")
    if report:
        blocks.append(link(report, "Full report"))
    return fit(blocks, report)


def _command(text: str) -> tuple[str, str, bool] | None:
    """``/status@CodeIntentBot arg`` -> ("status", "arg", addressed). None if it is not for this bot."""
    match = re.match(
        r"^/([A-Za-z0-9_]{1,32})(?:@([A-Za-z0-9_]{1,64}))?(?:\s+(.*))?$",
        text.strip(),
        re.S,
    )
    if not match:
        return None
    name, target, rest = match.groups()
    me = bot_username()
    if target and me and target.lower() != me.lower():
        return None
    return name.lower(), (rest or "").strip(), bool(target)


def _migrate(conn, old: int, new: int) -> None:
    """A group became a supergroup with a new id: keep its links (and drop exact duplicates)."""
    conn.execute(
        """UPDATE ci_telegram_chats c SET chat_id=%s WHERE chat_id=%s AND NOT EXISTS(
          SELECT 1 FROM ci_telegram_chats n WHERE n.chat_id=%s AND n.installation_id=c.installation_id)""",
        (new, old, new),
    )
    conn.execute("DELETE FROM ci_telegram_chats WHERE chat_id=%s", (old,))


def respond(update: dict) -> dict | None:
    """Act on one Update and return the reply to send ({chat_id, text}), or None to stay silent."""
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict) or not isinstance(chat.get("id"), int):
        return None
    chat_id = chat["id"]
    if isinstance(message.get("migrate_to_chat_id"), int):
        with store.connection() as conn:
            _migrate(conn, chat_id, message["migrate_to_chat_id"])
        return None
    text = message.get("text")
    if not isinstance(text, str) or not text.startswith("/"):
        return None
    parsed = _command(text)
    if not parsed:
        return None
    name, argument, addressed = parsed
    if name == "start":
        reply = link_chat(chat, argument) if argument else HELP + "\n\n" + NOT_LINKED
    elif name == "link":
        reply = (
            link_chat(chat, argument)
            if argument
            else "Send <code>/link CODE</code> with the code from the CodeIntent dashboard."
        )
    elif name == "unlink":
        reply = unlink_chat(chat_id)
    elif name == "status":
        reply = status(chat_id)
    elif name == "why":
        reply = why(chat_id, argument)
    elif name == "help" or chat.get("type") == "private" or addressed:
        reply = HELP
    else:
        # Unaddressed unknown commands in groups may be meant for another bot.
        return None
    return {"chat_id": chat_id, "text": reply}


def handle_update(update: dict) -> dict | None:
    """Respond to one webhook Update and send the reply. Errors are logged by category only."""
    try:
        reply = respond(update)
        if reply:
            send(reply["chat_id"], reply["text"])
        return reply
    except Exception as exc:
        logger.warning("Telegram update failed (%s)", type(exc).__name__)
        return None


# --- alerts ------------------------------------------------------------------------------------


def notify(analysis_id: str) -> int:
    """Alert every linked chat once about a reported analysis worth acting on. Returns messages sent.

    Each (analysis, chat) pair is claimed in ci_telegram_alerts before sending; a failed send
    releases the claim and raises, so a task retry reaches only the chats that missed it.
    """
    with store.connection() as conn:
        row = conn.execute(
            """SELECT a.id,a.installation_id,a.repository,a.number,a.title,a.status,a.verdicts
            FROM ci_pull_analyses a JOIN ci_installations i ON i.id=a.installation_id AND i.deleted_at IS NULL
            WHERE a.id=%s""",
            (analysis_id,),
        ).fetchone()
        if (
            not row
            or row["status"] != "reported"
            or not any(alerting(v) for v in verdict_list(row))
        ):
            return 0
        chats = [
            r["chat_id"]
            for r in conn.execute(
                "SELECT chat_id FROM ci_telegram_chats WHERE installation_id=%s ORDER BY linked_at",
                (row["installation_id"],),
            ).fetchall()
        ]
    if not chats:
        return 0
    text = alert_text(row)
    sent, failed = 0, None
    for chat_id in chats:
        with store.connection() as conn:
            claimed = conn.execute(
                "INSERT INTO ci_telegram_alerts(analysis_id,chat_id) VALUES (%s,%s) ON CONFLICT DO NOTHING RETURNING chat_id",
                (analysis_id, chat_id),
            ).fetchone()
        if not claimed:
            continue
        try:
            send(chat_id, text)
            sent += 1
        except TelegramError as exc:
            with store.connection() as conn:
                if exc.code == 403:
                    # The bot was removed from the group or blocked: stop alerting that chat.
                    conn.execute(
                        "DELETE FROM ci_telegram_chats WHERE chat_id=%s", (chat_id,)
                    )
                    logger.warning("Telegram chat removed the bot; unlinked it")
                    continue
                conn.execute(
                    "DELETE FROM ci_telegram_alerts WHERE analysis_id=%s AND chat_id=%s",
                    (analysis_id, chat_id),
                )
                if exc.migrate_to:
                    _migrate(conn, chat_id, exc.migrate_to)
            failed = exc
    if failed:
        raise failed
    return sent


# --- upcoming breakage -------------------------------------------------------------------------


def upcoming_block(item: dict, kinds: set[str]) -> str:
    """One dependency from a repository scan: the breaking next release and/or advisories on what runs now."""
    lines = []
    verdict = item.get("verdict") or {}
    if "breaks" in kinds and verdict:
        lines.append(package_block(verdict))
    if "lift" in kinds:
        where = item.get("location") or {}
        spot = (
            f"{where.get('file')}:{where.get('line')}"
            if where.get("line")
            else where.get("file")
        )
        lines.append(
            f"<b>Pin can be lifted</b>: <code>{esc(item.get('package'), 100)}{esc(item.get('specifier'), 60)}</code> "
            f"blocks {esc(item.get('latest'), 40)}, which changes nothing your code uses."
        )
        if spot:
            lines.append(f"  Pinned at <code>{esc(spot, 160)}</code>")
        origin = item.get("origin") or {}
        if origin.get("pr_url") and origin.get("pr_number"):
            title = f"#{origin['pr_number']} {origin.get('pr_title') or ''}".strip()
            lines.append(f"  Added in {link(origin['pr_url'], esc(title, 160))}")
        elif origin.get("commit_url"):
            first = str(origin.get("message") or "").split("\n", 1)[0]
            lines.append(f"  Added in {link(origin['commit_url'], esc(first, 160))}")
    if "advisory" in kinds:
        check = item.get("advisories") or {}
        active = [
            a
            for a in check.get("advisories") or []
            if isinstance(a, dict) and not a.get("withdrawn")
        ]
        shown = ", ".join(
            link(a.get("url"), esc(a.get("id"), 60))
            + (f" (fixed in {esc(a['fixed'], 40)})" if a.get("fixed") else "")
            for a in active[:3]
        )
        more = f" and {len(active) - 3} more" if len(active) > 3 else ""
        lines.append(
            f"<b>Known advisories</b>: <code>{esc(item.get('package'), 100)}</code> "
            f"{esc(item.get('current'), 40)}, the version you run now: {shown}{more}"
        )
    return "\n".join(lines)


def upcoming_text(repository: str, entries: list[tuple[dict, set[str]]]) -> str:
    owner_name = repository.split("/", 1)
    page = (
        public_url(f"/dashboard/{owner_name[0]}/{owner_name[1]}")
        if len(owner_name) == 2
        else None
    )
    blocks = [
        f"<b>{esc(repository, 200)}</b>\n"
        "Checked against the latest releases on PyPI, before any pull request:"
    ]
    blocks += [upcoming_block(item, kinds) for item, kinds in entries]
    if page:
        blocks.append(link(page, "Open the repository"))
    return fit(blocks, page)


def notify_upcoming(installation_id: int) -> int:
    """Tell each linked chat about upcoming findings it has not been told about. Returns messages sent.

    Same claim-then-send discipline as ``notify``: a failed send releases its claims for the retry.
    """
    from codeintent.scans import alert_keys

    with store.connection() as conn:
        chats = [
            r["chat_id"]
            for r in conn.execute(
                """SELECT c.chat_id FROM ci_telegram_chats c
                JOIN ci_installations i ON i.id=c.installation_id AND i.deleted_at IS NULL
                WHERE c.installation_id=%s ORDER BY c.linked_at""",
                (installation_id,),
            ).fetchall()
        ]
        scans = conn.execute(
            """SELECT s.repository,s.items FROM ci_repository_scans s
            JOIN ci_installation_repositories r
              ON r.installation_id=s.installation_id AND r.full_name=s.repository
            WHERE s.installation_id=%s AND s.status='done' AND s.items IS NOT NULL
            ORDER BY lower(s.repository)""",
            (installation_id,),
        ).fetchall()
    if not chats or not scans:
        return 0
    sent, failed = 0, None
    for chat_id in chats:
        for scan in scans:
            items = [i for i in scan["items"] or [] if isinstance(i, dict)]
            wanted = [
                (item, key, kind) for item in items for key, kind in alert_keys(item)
            ]
            if not wanted:
                continue
            with store.connection() as conn:
                claimed = {
                    r["key"]
                    for r in conn.execute(
                        """INSERT INTO ci_upcoming_alerts(installation_id,repository,key,chat_id)
                        SELECT %s,%s,k,%s FROM unnest(%s::text[]) k ON CONFLICT DO NOTHING RETURNING key""",
                        (
                            installation_id,
                            scan["repository"],
                            chat_id,
                            [key for _, key, _ in wanted],
                        ),
                    ).fetchall()
                }
            if not claimed:
                continue
            entries: dict[str, tuple[dict, set[str]]] = {}
            for item, key, kind in wanted:
                if key in claimed:
                    entries.setdefault(item["package"], (item, set()))[1].add(kind)
            try:
                send(chat_id, upcoming_text(scan["repository"], list(entries.values())))
                sent += 1
            except TelegramError as exc:
                with store.connection() as conn:
                    conn.execute(
                        """DELETE FROM ci_upcoming_alerts
                        WHERE installation_id=%s AND repository=%s AND chat_id=%s AND key=ANY(%s)""",
                        (installation_id, scan["repository"], chat_id, list(claimed)),
                    )
                    if exc.code == 403:
                        conn.execute(
                            "DELETE FROM ci_telegram_chats WHERE chat_id=%s", (chat_id,)
                        )
                        logger.warning("Telegram chat removed the bot; unlinked it")
                        break
                    if exc.migrate_to:
                        _migrate(conn, chat_id, exc.migrate_to)
                failed = exc
    if failed:
        raise failed
    return sent
