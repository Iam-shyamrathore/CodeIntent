"""Runtime configuration. Secrets are loaded only on the server."""

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env", override=False)


def required(name: str) -> str:
    value = os.getenv(name, "")
    if not value:
        raise RuntimeError(f"{name} is required")
    return value


def production_check():
    required("DATABASE_URL")
    required("NEO4J_URI")
    required("NEO4J_PASSWORD")
    if os.getenv("CODEINTENT_ENV") == "production":
        for name in ["CODEINTENT_API_SECRET", "CODEINTENT_OPERATOR_TOKEN"]:
            if len(required(name)) < 32:
                raise RuntimeError(f"{name} must contain at least 32 characters")
