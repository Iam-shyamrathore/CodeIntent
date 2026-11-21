"""MCP access tokens: each belongs to one installation and is shown once; only its SHA-256 is stored."""

from __future__ import annotations

import hashlib
import secrets
import uuid

from codeintent import store

PREFIX = "ci_mcp_"
MAX_ACTIVE = 10


def digest(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def issue(installation_id: int) -> dict:
    """A new token for a live installation. Raises LookupError when it does not exist or has too many."""
    token = PREFIX + secrets.token_urlsafe(32)
    ident = str(uuid.uuid4())
    with store.connection() as conn:
        live = conn.execute(
            "SELECT 1 FROM ci_installations WHERE id=%s AND deleted_at IS NULL FOR UPDATE",
            (installation_id,),
        ).fetchone()
        if not live:
            raise LookupError("installation")
        active = conn.execute(
            "SELECT count(*) AS n FROM ci_mcp_tokens WHERE installation_id=%s AND revoked_at IS NULL",
            (installation_id,),
        ).fetchone()["n"]
        if active >= MAX_ACTIVE:
            raise OverflowError(MAX_ACTIVE)
        row = conn.execute(
            """INSERT INTO ci_mcp_tokens(id,installation_id,token_hash,hint)
            VALUES (%s,%s,%s,%s) RETURNING id,hint,created_at""",
            (ident, installation_id, digest(token), token[-4:]),
        ).fetchone()
    return {"token": token, **_public(row)}


def _public(row: dict) -> dict:
    return {
        "id": str(row["id"]),
        "hint": row["hint"],
        "created_at": row["created_at"],
        "last_used_at": row.get("last_used_at"),
    }


def listing(installation_id: int) -> list[dict]:
    with store.connection() as conn:
        rows = conn.execute(
            """SELECT id,hint,created_at,last_used_at FROM ci_mcp_tokens
            WHERE installation_id=%s AND revoked_at IS NULL ORDER BY created_at DESC""",
            (installation_id,),
        ).fetchall()
    return [_public(r) for r in rows]


def revoke(installation_id: int, ident: str) -> bool:
    with store.connection() as conn:
        return bool(
            conn.execute(
                """UPDATE ci_mcp_tokens SET revoked_at=now()
                WHERE id=%s AND installation_id=%s AND revoked_at IS NULL RETURNING id""",
                (ident, installation_id),
            ).fetchone()
        )


def resolve(token: str) -> int | None:
    """The installation an active token belongs to, or None. Records when it was last used."""
    if not token.startswith(PREFIX) or len(token) > 200:
        return None
    with store.connection() as conn:
        row = conn.execute(
            """UPDATE ci_mcp_tokens t SET last_used_at=now() FROM ci_installations i
            WHERE t.token_hash=%s AND t.revoked_at IS NULL
              AND i.id=t.installation_id AND i.deleted_at IS NULL AND NOT i.suspended
            RETURNING t.installation_id""",
            (digest(token),),
        ).fetchone()
    return row["installation_id"] if row else None


def watches(installation_id: int, repository: str) -> bool:
    with store.connection() as conn:
        return bool(
            conn.execute(
                """SELECT 1 FROM ci_installation_repositories
                WHERE installation_id=%s AND lower(full_name)=lower(%s)""",
                (installation_id, repository),
            ).fetchone()
        )
