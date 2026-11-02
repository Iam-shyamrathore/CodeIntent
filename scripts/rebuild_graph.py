"""Rebuild published graph projections from the authoritative PostgreSQL ledger."""

from codeintent import store
from codeintent.graph import embed_corpus, project, project_decisions
from codeintent.parsing import parse_sources


def main():
    with store.connection() as conn:
        indexes = conn.execute(
            "SELECT * FROM ci_indexes WHERE published_at IS NOT NULL ORDER BY created_at"
        ).fetchall()
    for index in indexes:
        corpus = index["corpus"]
        project(corpus, parse_sources(corpus["documents"]), scope=index["id"])
        project_decisions(corpus, index["decisions"], scope=index["id"])
        embed_corpus(corpus, scope=index["id"])
        print(f"Rebuilt {corpus['repository']} · {index['id']}", flush=True)


if __name__ == "__main__":
    main()
