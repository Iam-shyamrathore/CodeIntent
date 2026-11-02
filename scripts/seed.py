"""Install the public demonstration corpus through the same durable import pipeline."""

import json
import uuid

from psycopg.types.json import Jsonb

from codeintent import store
from codeintent.settings import ROOT


def seed():
    corpus = json.loads((ROOT / "fixtures/corpus/httpx.json").read_text())
    from codeintent.graph import index_id

    with store.connection() as conn:
        existing = conn.execute(
            "SELECT ready_index FROM ci_repositories WHERE name='encode/httpx'"
        ).fetchone()
        if existing and existing["ready_index"] == index_id(corpus):
            print("Demo index already published.")
            return
        active = conn.execute(
            "SELECT id FROM ci_imports WHERE repository='encode/httpx' AND status IN ('queued','running','retrying')"
        ).fetchone()
        if active:
            print("Demo import already queued.")
            return
        from codeintent.tasks import import_repository

        ident = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO ci_imports(id,repository,options,checkpoint) VALUES (%s,'encode/httpx','{}',%s)",
            (ident, Jsonb({"corpus": corpus})),
        )
        task = import_repository.configure(
            connection=conn, lock="repo:encode/httpx"
        ).defer(import_id=ident)
        conn.execute("UPDATE ci_imports SET task_id=%s WHERE id=%s", (task, ident))
    print("Public demo import queued.")


if __name__ == "__main__":
    seed()
