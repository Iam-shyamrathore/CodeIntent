"""Idempotent local secret configuration; never copies a provider key."""

import argparse
import secrets
from pathlib import Path

from dotenv import dotenv_values

root = Path(__file__).resolve().parents[1]
args = argparse.ArgumentParser()
args.add_argument("--vertex-env", type=Path)
options = args.parse_args()
env = root / ".env"
values = dict(dotenv_values(env)) if env.exists() else {}
values.setdefault("GOOGLE_APPLICATION_CREDENTIALS", "")
values.setdefault("GOOGLE_CLOUD_LOCATION", "global")
values.setdefault("NEO4J_URI", "bolt://127.0.0.1:7692")
values.setdefault("NEO4J_USERNAME", "neo4j")
values.setdefault("NEO4J_PASSWORD", secrets.token_urlsafe(24))
values.setdefault("VERTEX_GENERATION_MODEL", "gemini-2.5-flash")
values.setdefault("VERTEX_EMBEDDING_MODEL", "gemini-embedding-001")
if options.vertex_env:
    filename = options.vertex_env.expanduser().resolve(strict=True)
    values["CODEINTENT_VERTEX_ENV_FILE"] = str(filename)
env.write_text("".join(f"{key}={value or ''}\n" for key, value in values.items()))
env.chmod(0o600)
runtime = root / ".runtime"
runtime.mkdir(exist_ok=True)
graph_env = runtime / "neo4j.env"
graph_env.write_text(
    f"NEO4J_AUTH=neo4j/{values['NEO4J_PASSWORD']}\n"
    "NEO4J_server_memory_heap_initial__size=256m\nNEO4J_server_memory_heap_max__size=512m\n"
    "NEO4J_server_memory_pagecache_size=256m\n"
)
graph_env.chmod(0o600)
print(
    "Local configuration ready. Existing graph credentials preserved; provider secrets remain outside the project."
)
