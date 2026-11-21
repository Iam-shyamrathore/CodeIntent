"""Telegram bot: linking, /status, /why and alerts, end to end against a local Bot API recorder.

Every outgoing Bot API call goes to a real HTTP server on 127.0.0.1 (``TELEGRAM_API`` points at it),
which records the exact JSON and answers like Telegram. Messages are checked against Telegram's HTML
parse rules. The database tests use real Postgres in a disposable schema:
CODEINTENT_RUN_INTEGRATION=1 DATABASE_URL=... uv run pytest tests/test_telegram.py
"""

from __future__ import annotations

import copy
import html
import json
import os
import re
import threading
import uuid
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.types.json import Jsonb

from codeintent import store, telegram
from codeintent.api import app
from codeintent.upgrades.verdict import UpgradeVerdict

SECRET = "test-service-secret"
WEBHOOK = "webhook_secret_" + "x" * 40
TOKEN = "123456:LOCAL-recorder-token-not-real"
BOT = "CodeIntentBot"
integration = pytest.mark.skipif(
    os.getenv("CODEINTENT_RUN_INTEGRATION") != "1", reason="requires real Postgres"
)

# From `python -m scripts.verdict --path openai-python-v1.54.4 --package httpx --from 0.27.2
# --to 0.28.0 --no-advisories`, trimmed (quotes, coverage, release); validated through the model.
HTTPX = UpgradeVerdict.model_validate(
    {
        "package": "httpx",
        "start": "0.27.2",
        "end": "0.28.0",
        "verdict": "breaks",
        "label": "Breaks you",
        "reason": "2 change(s) in httpx 0.28.0 break code you use, at 3 place(s)",
        "findings": [
            {
                "severity": "breaks",
                "change": {
                    "kind": "parameter-removed",
                    "symbol": "httpx._client.AsyncClient",
                    "parameter": "proxies",
                    "detail": "httpx._client.AsyncClient accepts proxies= in 0.27.2 but not in 0.28.0",
                    "message": "The 'proxies' argument is now deprecated. Use 'proxy' or 'mounts' instead.",
                    "replacement": "proxy= or mounts=",
                    "replacement_source": "message",
                    "before": {"file": "httpx/_client.py", "line": 1375},
                    "after": {"file": "httpx/_client.py", "line": 1355},
                },
                "guarded": False,
                "locations": [
                    {"file": "src/openai/_base_client.py", "line": 1438, "column": 38}
                ],
            },
            {
                "severity": "breaks",
                "change": {
                    "kind": "parameter-removed",
                    "symbol": "httpx._client.Client",
                    "parameter": "proxies",
                    "detail": "httpx._client.Client accepts proxies= in 0.27.2 but not in 0.28.0",
                    "message": "The 'proxies' argument is now deprecated. Use 'proxy' or 'mounts' instead.",
                    "replacement": "proxy= or mounts=",
                    "replacement_source": "message",
                    "before": {"file": "httpx/_client.py", "line": 628},
                    "after": {"file": "httpx/_client.py", "line": 641},
                },
                "guarded": False,
                "locations": [
                    {"file": "src/openai/_base_client.py", "line": 857, "column": 38},
                    {"file": "src/openai/cli/_cli.py", "line": 179, "column": 18},
                ],
            },
        ],
        "decisions": [
            {
                "change_key": {
                    "symbol": f"httpx._client.{name}",
                    "parameter": "proxies",
                    "kind": "parameter-removed",
                },
                "pr_number": 3319,
                "pr_title": "Introduce new `SSLContext` API & escalate deprecations.",
                "pr_url": "https://github.com/encode/httpx/pull/3319",
                "merged_at": "2024-10-28T14:30:08Z",
            }
            for name in ("AsyncClient", "Client")
        ],
    }
).model_dump(mode="json")
# A clean upgrade whose target release has a published advisory (OSV GHSA-q2x7-8rv6-6q7h).
JINJA = UpgradeVerdict.model_validate(
    {
        "package": "Jinja2",
        "start": "3.1.3",
        "end": "3.1.4",
        "verdict": "no-known-impact",
        "label": "No known impact",
        "reason": "nothing the code uses changed between Jinja2 3.1.3 and 3.1.4",
        "advisories": [
            {
                "package": "jinja2",
                "version": "3.1.4",
                "status": "advisories",
                "advisories": [
                    {
                        "id": "GHSA-q2x7-8rv6-6q7h",
                        "aliases": ["CVE-2024-56326"],
                        "summary": "Jinja has a sandbox breakout through indirect reference to format method",
                        "fixed": "3.1.5",
                        "source": "GitHub Advisory Database",
                        "url": "https://osv.dev/vulnerability/GHSA-q2x7-8rv6-6q7h",
                    }
                ],
            },
            {"package": "jinja2", "version": "3.1.3", "status": "none-known"},
        ],
    }
).model_dump(mode="json")
CLEAN = UpgradeVerdict.model_validate(
    {
        "package": "idna",
        "start": "3.6",
        "end": "3.7",
        "verdict": "no-known-impact",
        "label": "No known impact",
        "reason": "the code does not import idna directly",
    }
).model_dump(mode="json")


class TelegramHTML(HTMLParser):
    """Telegram's HTML parse mode: only these tags; <a> only with href; entities limited; balanced."""

    ALLOWED = {"b", "i", "code", "pre", "a"}
    ENTITIES = {"lt", "gt", "amp", "quot"}

    def __init__(self):
        super().__init__(convert_charrefs=False)
        self.stack, self.text = [], []

    def handle_starttag(self, tag, attrs):
        assert tag in self.ALLOWED, tag
        if tag == "a":
            assert [k for k, _ in attrs] == ["href"] and re.match(
                r"^https?://", attrs[0][1]
            )
        else:
            assert not attrs
        if tag in {"code", "pre"}:
            assert not set(self.stack) & {"code", "pre"}, "code cannot nest"
        self.stack.append(tag)

    def handle_endtag(self, tag):
        assert self.stack and self.stack.pop() == tag, tag

    def handle_data(self, data):
        assert "<" not in data and ">" not in data
        self.text.append(data)

    def handle_entityref(self, name):
        assert name in self.ENTITIES, name
        self.text.append(html.unescape(f"&{name};"))

    def handle_charref(self, name):
        self.text.append(html.unescape(f"&#{name};"))


def check_html(text: str) -> str:
    """Assert ``text`` parses under Telegram's HTML rules; return the visible text."""
    assert 1 <= len(text) <= telegram.MAX_MESSAGE
    # Bare & must be escaped: every & starts an entity.
    assert not re.search(r"&(?!(lt|gt|amp|quot|#\d+|#x[0-9a-fA-F]+);)", text)
    parser = TelegramHTML()
    parser.feed(text)
    parser.close()
    assert not parser.stack, parser.stack
    visible = "".join(parser.text)
    assert len(visible) <= 4096
    return visible


class Recorder:
    """A local stand-in for api.telegram.org that records each Bot API request."""

    def __init__(self):
        self.calls: list[dict] = []
        self.blocked: set[int] = set()
        recorder = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                match = re.match(r"^/bot([^/]+)/(\w+)$", self.path)
                recorder.calls.append(
                    {"token": match[1], "method": match[2], "body": body}
                )
                if match[1] != TOKEN:
                    code, reply = (
                        401,
                        {"ok": False, "error_code": 401, "description": "Unauthorized"},
                    )
                elif body.get("chat_id") in recorder.blocked:
                    code, reply = (
                        403,
                        {
                            "ok": False,
                            "error_code": 403,
                            "description": "Forbidden: bot was kicked from the group chat",
                        },
                    )
                else:
                    code, reply = (
                        200,
                        {
                            "ok": True,
                            "result": {
                                "message_id": len(recorder.calls),
                                "date": 1730000000,
                                "chat": {"id": body.get("chat_id"), "type": "private"},
                                "text": "sent",
                            },
                        },
                    )
                data = json.dumps(reply).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def sent(self) -> list[dict]:
        return [c["body"] for c in self.calls if c["method"] == "sendMessage"]


@pytest.fixture
def recorder(monkeypatch):
    server = Recorder()
    monkeypatch.setattr(telegram, "TELEGRAM_API", server.url)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", BOT)
    monkeypatch.setenv("TELEGRAM_WEBHOOK_SECRET", WEBHOOK)
    monkeypatch.setenv("CODEINTENT_PUBLIC_URL", "https://codeintent.example")
    yield server
    server.server.shutdown()


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CODEINTENT_API_SECRET", SECRET)
    with TestClient(app, headers={"X-Api-Key": SECRET}) as test:
        yield test


def update(chat: dict, text: str, update_id: int = 10000) -> dict:
    """An Update with a Message, shaped like the Bot API reference (Update, Message, Chat, User)."""
    entity_length = len(text.split()[0]) if text.startswith("/") else 0
    message = {
        "message_id": 1365,
        "from": {
            "id": 1111111,
            "is_bot": False,
            "first_name": "Ada",
            "username": "ada",
            "language_code": "en",
        },
        "chat": chat,
        "date": 1730000000,
        "text": text,
    }
    if entity_length:
        message["entities"] = [
            {"offset": 0, "length": entity_length, "type": "bot_command"}
        ]
    return {"update_id": update_id, "message": message}


PRIVATE = {"id": 1111111, "first_name": "Ada", "username": "ada", "type": "private"}
GROUP = {"id": -1001234567890, "title": "Platform <team> & ops", "type": "supergroup"}


def post(client, payload, secret=WEBHOOK):
    return client.post(
        "/telegram/webhook",
        json=payload,
        headers={"X-Telegram-Bot-Api-Secret-Token": secret},
    )


# --- rendering and parsing (no database) ---------------------------------------------------------


def test_alert_renders_real_verdict_under_telegram_html_rules(monkeypatch):
    monkeypatch.setenv("CODEINTENT_PUBLIC_URL", "https://codeintent.example")
    row = {
        "id": "6f1c3a52-6f0e-4d47-9a37-2f1b9b3f3f10",
        "repository": "acme/app",
        "number": 42,
        "title": "Bump httpx <0.28 & 'friends'",
        "verdicts": [CLEAN, HTTPX, JINJA],
    }
    text = telegram.alert_text(row)
    visible = check_html(text)
    assert "Bump httpx <0.28 & 'friends'" in visible
    assert "Breaks you: httpx 0.27.2 → 0.28.0" in visible
    assert "httpx.Client(proxies=) no longer accepts this argument" in visible
    assert "src/openai/_base_client.py:857, src/openai/cli/_cli.py:179" in visible
    assert "Use instead: proxy= or mounts=" in visible
    assert (
        "Upstream: #3319 Introduce new `SSLContext` API & escalate deprecations."
        in visible
    )
    assert "Known advisories for 3.1.4: GHSA-q2x7-8rv6-6q7h (fixed in 3.1.5)" in visible
    assert "No known impact: idna 3.6 → 3.7" in visible
    assert '<a href="https://github.com/acme/app/pull/42">' in text
    assert (
        '<a href="https://codeintent.example/pulls/6f1c3a52-6f0e-4d47-9a37-2f1b9b3f3f10">Full report</a>'
        in text
    )


def test_long_messages_keep_whole_blocks_and_link_the_dashboard(monkeypatch):
    monkeypatch.setenv("CODEINTENT_PUBLIC_URL", "https://codeintent.example")
    many = []
    for n in range(60):
        v = copy.deepcopy(HTTPX)
        v["package"] = f"pkg-{n}"
        many.append(v)
    text = telegram.alert_text(
        {
            "id": str(uuid.uuid4()),
            "repository": "acme/app",
            "number": 7,
            "title": "x",
            "verdicts": many,
        }
    )
    check_html(text)
    assert text.endswith(
        '<a href="https://codeintent.example/pulls/' + text.split("/pulls/")[-1]
    )
    assert "<i>Truncated.</i>" in text


def test_links_only_for_http_urls():
    assert telegram.link("javascript:alert(1)", "x") == "x"
    assert telegram.link('https://e.com/"onmouseover=', "x") == "x"


def test_commands_addressed_to_this_bot_only(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_USERNAME", BOT)
    assert telegram._command("/status@CodeIntentBot") == ("status", "", True)
    assert telegram._command("/why@codeintentbot  httpx ") == ("why", "httpx", True)
    assert telegram._command("/status@OtherBot") is None
    assert telegram._command("/link abcd2345") == ("link", "abcd2345", False)


def test_webhook_rejects_wrong_or_missing_secret(client, recorder, monkeypatch):
    assert post(client, update(PRIVATE, "/start"), secret="wrong").status_code == 401
    assert client.post("/telegram/webhook", json={}).status_code == 401
    monkeypatch.delenv("TELEGRAM_WEBHOOK_SECRET")
    assert post(client, update(PRIVATE, "/start")).status_code == 503
    assert recorder.calls == []


def test_transport_errors_never_carry_the_token(monkeypatch):
    monkeypatch.setattr(telegram, "TELEGRAM_API", "http://127.0.0.1:9")
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", TOKEN)
    with pytest.raises(telegram.TelegramError) as caught:
        telegram.send(1, "hello")
    assert TOKEN not in str(caught.value) and TOKEN not in repr(caught.value)
    assert caught.value.__context__ is None and caught.value.__cause__ is None


def test_api_errors_are_reported_without_the_token(recorder, monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "999:wrong-token")
    with pytest.raises(telegram.TelegramError) as caught:
        telegram.send(1, "hello")
    assert caught.value.code == 401 and "999:wrong-token" not in str(caught.value)


# --- end to end against Postgres -----------------------------------------------------------------


@pytest.fixture
def seeded(monkeypatch, client, recorder):
    original = os.environ.get("DATABASE_URL") or pytest.skip("DATABASE_URL is not set")
    name = "ci_test_" + uuid.uuid4().hex
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(name)))
    monkeypatch.setenv(
        "DATABASE_URL",
        psycopg.conninfo.make_conninfo(original, options=f"-c search_path={name}"),
    )
    store.migrate()
    now = datetime.now(UTC)
    ids = {}
    with store.connection() as conn:
        conn.execute(
            """INSERT INTO ci_installations(id,account_login,account_type,deleted_at) VALUES
            (11,'acme','Organization',NULL),(12,'other','User',NULL),(13,'gone','Organization',now())"""
        )
        conn.execute(
            """INSERT INTO ci_installation_repositories(installation_id,repository_id,full_name,private) VALUES
            (11,1,'acme/app',false),(11,2,'acme/web',true),(12,3,'other/secret',true)"""
        )
        rows = [
            ("breaks", 11, "acme/app", 5, "reported", "breaks", [HTTPX, CLEAN], 3),
            ("advisory", 11, "acme/web", 9, "reported", "no-known-impact", [JINJA], 2),
            ("clean", 11, "acme/web", 10, "reported", "no-known-impact", [CLEAN], 1),
            ("running", 11, "acme/app", 6, "running", None, None, 0),
            ("other", 12, "other/secret", 1, "reported", "breaks", [HTTPX], 0),
        ]
        for key, inst, repo, number, status, verdict, verdicts, days in rows:
            ids[key] = str(uuid.uuid4())
            conn.execute(
                """INSERT INTO ci_pull_analyses(id,installation_id,repository,number,head_sha,base_sha,
                status,verdicts,verdict,title,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    ids[key], inst, repo, number, "a" * 40, "b" * 40, status,
                    Jsonb(verdicts) if verdicts else None, verdict,
                    f"Bump {repo.split('/')[1]} deps #{number}", now - timedelta(days=days),
                ),
            )  # fmt: skip
    yield ids
    with psycopg.connect(original, autocommit=True) as conn:
        conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(name)))


def code_for(client, installation=11) -> dict:
    response = client.post(f"/app/installations/{installation}/telegram-code")
    assert response.status_code == 200, response.text
    return response.json()


@integration
def test_link_code_is_one_time_hashed_and_expires(client, seeded, recorder):
    assert client.post("/app/installations/13/telegram-code").status_code == 404
    assert client.post("/app/installations/99/telegram-code").status_code == 404
    assert (
        client.post(
            "/app/installations/11/telegram-code", headers={"X-Api-Key": "x"}
        ).status_code
        == 401
    )
    made = code_for(client)
    assert re.fullmatch(f"[{telegram.CODE_ALPHABET}]{{8}}", made["code"])
    assert made["deep_link"] == f"https://t.me/{BOT}?start={made['code']}"
    expires = datetime.fromisoformat(made["expires_at"])
    assert timedelta(minutes=14) < expires - datetime.now(UTC) <= timedelta(minutes=15)
    with store.connection() as conn:
        stored = conn.execute("SELECT code_hash FROM ci_telegram_links").fetchall()
    assert [r["code_hash"] for r in stored] != [made["code"]] and len(
        stored[0]["code_hash"]
    ) == 64

    # Deep link: the private chat sends "/start CODE".
    assert post(client, update(PRIVATE, f"/start {made['code']}")).json() == {
        "ok": True
    }
    reply = recorder.sent()[-1]
    assert reply["chat_id"] == PRIVATE["id"] and reply["parse_mode"] == "HTML"
    assert "Linked to acme" in check_html(reply["text"])
    assert recorder.calls[-1]["token"] == TOKEN

    post(client, update(GROUP, f"/link@{BOT} {made['code']}"))
    assert "already used or expired" in check_html(recorder.sent()[-1]["text"])

    stale = code_for(client)
    with store.connection() as conn:
        conn.execute(
            "UPDATE ci_telegram_links SET expires_at=now()-interval '1 second' WHERE used_at IS NULL"
        )
    post(client, update(GROUP, f"/link {stale['code'].lower()}"))
    assert "already used or expired" in check_html(recorder.sent()[-1]["text"])

    fresh = code_for(client)
    post(client, update(GROUP, f"/link@{BOT} {fresh['code']}"))
    assert "Linked to acme" in check_html(recorder.sent()[-1]["text"])
    chats = client.get("/app/installations/11/telegram").json()
    assert chats["configured"] is True and chats["bot_username"] == BOT
    assert [c["title"] for c in chats["chats"]] == [
        "Platform <team> & ops",
        "Private chat with @ada",
    ]
    assert all(set(c) == {"title", "linked_at"} for c in chats["chats"])
    assert client.get("/app/installations/12/telegram").json()["chats"] == []


@integration
def test_status_and_why_cover_only_linked_installations(client, seeded, recorder):
    post(client, update(GROUP, "/status@CodeIntentBot"))
    assert "not linked" in check_html(recorder.sent()[-1]["text"])
    post(client, update(GROUP, f"/link {code_for(client)['code']}"))

    post(client, update(GROUP, "/status@CodeIntentBot"))
    text = recorder.sent()[-1]["text"]
    visible = check_html(text)
    assert "acme · 2 repositories" in visible
    assert "acme/app: Breaks you (#5 Bump app deps #5)" in visible
    assert "acme/web: No known impact (#10 Bump web deps #10)" in visible
    assert "Breaks you: httpx 0.27.2 → 0.28.0" in visible
    assert "other/secret" not in visible
    assert (
        f'<a href="https://codeintent.example/pulls/{seeded["breaks"]}">Report</a>'
        in text
    )

    post(client, update(GROUP, "/why@CodeIntentBot HTTPX"))
    text = recorder.sent()[-1]["text"]
    visible = check_html(text)
    assert "Latest verdict for HTTPX: acme/app #5 Bump app deps #5" in visible
    assert "httpx.AsyncClient(proxies=) no longer accepts this argument" in visible
    assert "In your code: src/openai/_base_client.py:1438" in visible
    assert (
        "Upstream: #3319 Introduce new `SSLContext` API & escalate deprecations."
        in visible
    )
    assert '<a href="https://github.com/encode/httpx/pull/3319">' in text

    post(client, update(GROUP, "/why jinja2"))
    assert "Known advisories for 3.1.4: GHSA-q2x7-8rv6-6q7h" in check_html(
        recorder.sent()[-1]["text"]
    )
    post(client, update(GROUP, "/why <b>"))
    assert "not a Python package name" in check_html(recorder.sent()[-1]["text"])
    post(client, update(GROUP, "/why requests"))
    assert "No analysed pull request" in check_html(recorder.sent()[-1]["text"])

    count = len(recorder.sent())
    post(
        client, update(GROUP, "/frobnicate")
    )  # unaddressed unknown command in a group: silent
    post(client, update(GROUP, "/status@OtherBot"))
    post(client, update(GROUP, "just chatting"))
    post(
        client, {"update_id": 1, "edited_message": update(GROUP, "/status")["message"]}
    )
    assert len(recorder.sent()) == count
    post(client, update(PRIVATE, "/frobnicate"))
    assert "/status" in check_html(recorder.sent()[-1]["text"])

    post(client, update(GROUP, "/unlink"))
    assert "Unlinked" in check_html(recorder.sent()[-1]["text"])
    post(client, update(GROUP, "/status"))
    assert "not linked" in check_html(recorder.sent()[-1]["text"])


@integration
def test_notify_alerts_each_chat_once_and_only_when_it_matters(
    client, seeded, recorder
):
    blocked = {"id": -1009999999999, "title": "Old group", "type": "supergroup"}
    for chat in (PRIVATE, GROUP, blocked):
        post(client, update(chat, f"/link {code_for(client)['code']}"))
    recorder.blocked.add(blocked["id"])
    before = len(recorder.sent())

    assert telegram.notify(seeded["breaks"]) == 2
    alerts = recorder.sent()[before:]
    assert sorted(a["chat_id"] for a in alerts) == sorted(
        [PRIVATE["id"], GROUP["id"], blocked["id"]]
    )
    text = alerts[0]["text"]
    visible = check_html(text)
    assert "acme/app\n#5 Bump app deps #5" in visible
    assert "Breaks you: httpx 0.27.2 → 0.28.0" in visible
    assert "No known impact: idna 3.6 → 3.7" in visible
    assert alerts[0]["link_preview_options"] == {"is_disabled": True}
    # The chat that removed the bot is unlinked; the others are never alerted twice.
    assert [
        c["title"] for c in client.get("/app/installations/11/telegram").json()["chats"]
    ].count("Old group") == 0
    assert telegram.notify(seeded["breaks"]) == 0

    assert telegram.notify(seeded["advisory"]) == 2
    assert "GHSA-q2x7-8rv6-6q7h" in check_html(recorder.sent()[-1]["text"])
    sent = len(recorder.sent())
    assert telegram.notify(seeded["clean"]) == 0
    assert telegram.notify(seeded["running"]) == 0
    assert telegram.notify(seeded["other"]) == 0  # installation 12 has no linked chat
    assert len(recorder.sent()) == sent
    with store.connection() as conn:
        claimed = conn.execute(
            "SELECT count(*) AS n FROM ci_telegram_alerts"
        ).fetchone()["n"]
    assert (
        claimed == 5
    )  # 3 for the breaking PR (one to the chat that then got unlinked), 2 for the advisory
