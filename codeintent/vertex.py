"""Single explicit Vertex provider; credential material never leaves this module."""

import json
import os
from pathlib import Path

from dotenv import dotenv_values, load_dotenv
from google import genai
from google.oauth2 import service_account

ROOT = Path(__file__).resolve().parents[1]


def client() -> genai.Client:
    load_dotenv(ROOT / ".env", override=False)
    source_env = os.environ.get("CODEINTENT_VERTEX_ENV_FILE")
    if source_env:
        settings = dotenv_values(source_env)
        if str(settings.get("GOOGLE_GENAI_USE_VERTEX", "")).lower() != "true":
            raise ValueError(
                "Referenced provider configuration must explicitly select Vertex"
            )
        key = settings.get("GOOGLE_API_KEY")
        if not key:
            raise ValueError("Referenced Vertex configuration has no API key")
        return genai.Client(
            vertexai=True,
            api_key=key,
            http_options={"api_version": "v1", "timeout": 60000},
        )
    if os.getenv("GOOGLE_API_KEY"):
        return genai.Client(
            vertexai=True,
            api_key=os.environ["GOOGLE_API_KEY"],
            http_options={"api_version": "v1", "timeout": 60000},
        )
    filename = os.getenv("GOOGLE_APPLICATION_CREDENTIALS")
    if not filename:
        # Standard Application Default Credentials / attached cloud identity.
        return genai.Client(
            vertexai=True,
            project=os.environ["GOOGLE_CLOUD_PROJECT"],
            location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
            http_options={"api_version": "v1", "timeout": 60000},
        )
    project = (
        os.environ.get("GOOGLE_CLOUD_PROJECT")
        or json.loads(Path(filename).read_text())["project_id"]
    )
    credentials = service_account.Credentials.from_service_account_file(
        filename, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return genai.Client(
        vertexai=True,
        project=project,
        location=os.getenv("GOOGLE_CLOUD_LOCATION", "global"),
        credentials=credentials,
        http_options={"api_version": "v1", "timeout": 60000},
    )
