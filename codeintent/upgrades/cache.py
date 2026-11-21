"""Small on-disk JSON cache helpers: content digests, tolerant reads and atomic writes.

Every helper is best effort: a missing, corrupt or unwritable cache entry behaves like a cache miss.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from pathlib import Path


def digest(*parts: str | bytes) -> str:
    """SHA-256 over ``parts``, length-prefixed so that different splits never collide."""
    hasher = hashlib.sha256()
    for part in parts:
        data = part.encode("utf-8") if isinstance(part, str) else part
        hasher.update(len(data).to_bytes(8, "big"))
        hasher.update(data)
    return hasher.hexdigest()


def read_json(path: Path, max_age: float | None = None):
    """Parsed JSON at ``path``, or ``None`` when absent, unreadable, corrupt or older than ``max_age`` seconds."""
    try:
        if max_age is not None and time.time() - path.stat().st_mtime > max_age:
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def write_json(path: Path, value) -> None:
    """Write ``value`` as JSON to ``path`` atomically (temporary file, then rename); errors are ignored."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=path.parent,
            prefix=path.name + ".",
            suffix=".tmp",
            delete=False,
        )
        try:
            with handle:
                json.dump(value, handle, separators=(",", ":"))
            os.replace(handle.name, path)
        except BaseException:
            Path(handle.name).unlink(missing_ok=True)
            raise
    except OSError:
        pass
