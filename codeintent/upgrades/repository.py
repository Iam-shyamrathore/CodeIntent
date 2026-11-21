"""Download a repository at a ref as a source tarball, unpacked safely; nothing in it is run."""

from __future__ import annotations

import os
import subprocess
import tarfile
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from pathlib import Path

import httpx

MAX_TARBALL_BYTES = 300_000_000
_scoped: ContextVar[Callable[[], str] | None] = ContextVar("github_token", default=None)


@contextmanager
def using(source: Callable[[], str]) -> Iterator[None]:
    """Make ``token()`` return ``source()`` (e.g. a GitHub App installation token) inside the block."""
    reset = _scoped.set(source)
    try:
        yield
    finally:
        _scoped.reset(reset)


def token() -> str | None:
    """The scoped token from ``using``, else GITHUB_TOKEN, else an authenticated ``gh`` CLI's token,
    else None (public, rate-limited)."""
    if (source := _scoped.get()) is not None:
        return source()
    if os.getenv("GITHUB_TOKEN"):
        return os.environ["GITHUB_TOKEN"]
    try:
        found = subprocess.run(
            ["gh", "auth", "token"],
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    return found.stdout.strip() or None


def download(
    repository: str, ref: str, destination: Path, secret: str | None = None
) -> Path:
    """Unpack ``owner/name`` at ``ref`` under ``destination`` and return the source root."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "CodeIntent/1.0"}
    if secret:
        headers["Authorization"] = f"Bearer {secret}"
    archive = destination / "source.tar.gz"
    size = 0
    with (
        httpx.Client(timeout=120, follow_redirects=True, headers=headers) as client,
        client.stream(
            "GET", f"https://api.github.com/repos/{repository}/tarball/{ref}"
        ) as response,
        archive.open("wb") as handle,
    ):
        response.raise_for_status()
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_TARBALL_BYTES:
                raise ValueError(
                    f"{repository}@{ref} is larger than {MAX_TARBALL_BYTES} bytes"
                )
            handle.write(chunk)
    unpacked = destination / "source"
    unpacked.mkdir()
    with tarfile.open(archive) as bundle:
        bundle.extractall(unpacked, filter="data")
    archive.unlink()
    roots = [p for p in unpacked.iterdir() if p.is_dir()]
    return roots[0] if len(roots) == 1 else unpacked


def temporary() -> tempfile.TemporaryDirectory:
    return tempfile.TemporaryDirectory(prefix="codeintent-repo-")
