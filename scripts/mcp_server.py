"""Serve the CodeIntent MCP server over streamable HTTP at /mcp.

CODEINTENT_MCP_TOKEN=... python -m scripts.mcp_server            # http://127.0.0.1:8220/mcp
PORT=8220 HOST=0.0.0.0 python -m scripts.mcp_server              # e.g. a Heroku process type

The ``__main__`` guard is required: the usage scanner starts a spawn-based process pool, which
re-imports the main module in every worker.
"""

from __future__ import annotations

import logging
import os

import uvicorn


def main() -> None:
    from dotenv import load_dotenv

    load_dotenv()
    logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())
    logging.getLogger("httpx").setLevel(logging.WARNING)
    from codeintent.mcp_server import create_app

    try:
        app = create_app()
    except RuntimeError as error:  # e.g. CODEINTENT_MCP_TOKEN missing in production
        logging.getLogger("codeintent.mcp").error("%s", error)
        raise SystemExit(1) from None
    uvicorn.run(
        app,
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8220")),
        proxy_headers=True,
        forwarded_allow_ips=os.getenv("FORWARDED_ALLOW_IPS", "127.0.0.1"),
        access_log=False,
    )


if __name__ == "__main__":
    main()
