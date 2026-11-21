"""Fetch released files from PyPI, verify their SHA-256, extract them safely, and cache them.

Artifacts are only downloaded and unpacked: nothing is built, installed, imported or executed.
"""

from __future__ import annotations

import hashlib
import os
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

import httpx
from packaging.utils import canonicalize_name

from codeintent.upgrades import cache

PYPI = "https://pypi.org/pypi"
CACHE = Path(
    os.getenv(
        "CODEINTENT_ARTIFACT_CACHE", Path.home() / ".cache" / "codeintent" / "artifacts"
    )
)
MAX_ARTIFACT_BYTES = 150_000_000
MAX_EXTRACTED_BYTES = 600_000_000
# PyPI release metadata is reused for this long; yanked flags can change, so it is not kept forever.
RELEASE_TTL = float(os.getenv("CODEINTENT_PYPI_TTL", 6 * 3600))


class ArtifactError(Exception):
    def __init__(self, reason: str, detail: str):
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


def _release_path(name: str, version: str) -> Path:
    return CACHE.parent / "pypi" / f"{cache.digest(name, version)}.json"


def release(name: str, version: str, client: httpx.Client) -> dict:
    """PyPI JSON metadata for ``name`` at ``version``, cached on disk for ``RELEASE_TTL`` seconds."""
    canonical = canonicalize_name(name)
    path = _release_path(canonical, version)
    cached = cache.read_json(path, max_age=RELEASE_TTL)
    if isinstance(cached, dict) and "urls" in cached:
        return cached
    response = client.get(f"{PYPI}/{canonical}/{version}/json")
    if response.status_code == 404:
        raise ArtifactError("release-not-found", f"{name} {version} is not on PyPI")
    response.raise_for_status()
    data = response.json()
    cache.write_json(path, data)
    return data


def choose(files: list[dict]) -> dict:
    """Prefer a pure-Python wheel, then any wheel, then the sdist; yanked files only if nothing else exists."""
    usable = [f for f in files if not f.get("yanked")] or files

    def rank(f: dict):
        name = f["filename"]
        if f["packagetype"] == "bdist_wheel":
            return 0 if name.endswith("-none-any.whl") else 1
        return 2 if f["packagetype"] == "sdist" else 3

    candidates = sorted((f for f in usable if rank(f) < 3), key=rank)
    if not candidates:
        raise ArtifactError("no-artifact", "no wheel or sdist is available")
    return candidates[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _stamp(path: Path) -> dict:
    stat = path.stat()
    return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}


def _verified(target: Path, expected: str) -> bool:
    """Whether ``target`` has SHA-256 ``expected``; a sidecar skips re-hashing while size and mtime are unchanged."""
    sidecar = target.with_name(target.name + ".sha256.json")
    try:
        stamp = _stamp(target)
    except OSError:
        return False
    if cache.read_json(sidecar) == {**stamp, "sha256": expected}:
        return True
    if _sha256(target) != expected:
        return False
    cache.write_json(sidecar, {**stamp, "sha256": expected})
    return True


def download(name: str, version: str, client: httpx.Client) -> Path:
    chosen = choose(release(name, version, client)["urls"])
    expected = chosen["digests"]["sha256"]
    target = CACHE / canonicalize_name(name) / version / chosen["filename"]
    if target.is_file() and _verified(target, expected):
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    partial = target.with_suffix(target.suffix + ".part")
    size = 0
    with client.stream("GET", chosen["url"]) as response, partial.open("wb") as handle:
        response.raise_for_status()
        for chunk in response.iter_bytes():
            size += len(chunk)
            if size > MAX_ARTIFACT_BYTES:
                partial.unlink(missing_ok=True)
                raise ArtifactError(
                    "artifact-too-large",
                    f"{chosen['filename']} exceeds {MAX_ARTIFACT_BYTES} bytes",
                )
            handle.write(chunk)
    if _sha256(partial) != expected:
        partial.unlink(missing_ok=True)
        raise ArtifactError(
            "hash-mismatch", f"{chosen['filename']} does not match PyPI's SHA-256"
        )
    partial.replace(target)
    cache.write_json(
        target.with_name(target.name + ".sha256.json"),
        {**_stamp(target), "sha256": expected},
    )
    return target


def _safe_member(name: str) -> bool:
    path = PurePosixPath(name)
    return not path.is_absolute() and ".." not in path.parts


def extract(archive: Path) -> Path:
    destination = archive.parent / (archive.name + ".d")
    if destination.is_dir():
        return destination
    staging = archive.parent / (archive.name + ".tmp")
    staging.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".whl" or archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            members = bundle.infolist()
            if not all(_safe_member(m.filename) for m in members):
                raise ArtifactError(
                    "unsafe-archive",
                    f"{archive.name} contains paths outside the archive",
                )
            if sum(m.file_size for m in members) > MAX_EXTRACTED_BYTES:
                raise ArtifactError(
                    "artifact-too-large",
                    f"{archive.name} expands beyond the size limit",
                )
            bundle.extractall(staging)
    else:
        with tarfile.open(archive) as bundle:
            members = bundle.getmembers()
            if sum(m.size for m in members) > MAX_EXTRACTED_BYTES:
                raise ArtifactError(
                    "artifact-too-large",
                    f"{archive.name} expands beyond the size limit",
                )
            bundle.extractall(staging, filter="data")
    staging.replace(destination)
    return destination


def fetch(name: str, version: str, client: httpx.Client) -> Path:
    """Directory holding the unpacked release of ``name`` at ``version``."""
    return extract(download(name, version, client))
