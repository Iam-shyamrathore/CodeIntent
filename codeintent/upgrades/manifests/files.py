"""Read repository files without following paths or links outside the repository."""

from __future__ import annotations

from pathlib import Path

MAX_BYTES = 2_000_000


class Unreadable(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def confined(root: Path, path: Path) -> Path:
    real = path.resolve()
    if not real.is_relative_to(root.resolve()):
        raise Unreadable(
            "path-outside-repository", f"{path.name} resolves outside the repository"
        )
    return real


def read(root: Path, path: Path) -> str:
    real = confined(root, path)
    if real.stat().st_size > MAX_BYTES:
        raise Unreadable(
            "file-too-large", f"{path.name} is larger than {MAX_BYTES} bytes"
        )
    return real.read_text(encoding="utf-8", errors="replace")


def relative(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root.resolve()).as_posix()
