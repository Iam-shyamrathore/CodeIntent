from __future__ import annotations

from pathlib import Path

import pytest

from codeintent import codemap

FILES = {
    "pyproject.toml": """
[project]
name = "app"
dependencies = ["httpx==0.27.2", "PyYAML==6.0.1"]
[project.scripts]
app = "app.cli:main"
""",
    "src/app/__init__.py": "",
    "src/app/client.py": """
import httpx


def make(proxy):
    return httpx.Client(proxies=proxy)


class Session:
    def __init__(self, proxy):
        self.client = make(proxy)

    def get(self, url):
        return self.fetch(url)

    def fetch(self, url):
        return self.client.get(url)
""",
    "src/app/api.py": """
from fastapi import APIRouter

from app.client import make
from . import client

router = APIRouter()


@router.get("/users")
def users():
    return make(None)


def sessions():
    return client.Session(None).get("/")
""",
    "src/app/cli.py": """
import yaml

from app import api


def main():
    api.users()
    return yaml.safe_load("a: 1")
""",
    "tests/test_client.py": """
from app.client import make


def test_make():
    assert make(None)
""",
    "scripts/run.py": """
from app.cli import main

if __name__ == "__main__":
    main()
""",
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    for name, text in FILES.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text.lstrip("\n"))
    return tmp_path


@pytest.fixture
def built(repo: Path) -> dict:
    return codemap.build(repo, codemap.dependencies_of(repo))


def by_path(built: dict) -> dict[str, dict]:
    return {f["path"]: f for f in built["files"]}


def test_names_modules_from_their_package_root(built):
    files = by_path(built)
    assert files["src/app/client.py"]["module"] == "app.client"
    assert files["src/app/__init__.py"]["module"] == "app"


def test_records_which_local_file_imports_which(built):
    edges = {(i["file"], i["target"]) for i in built["imports"]}
    assert ("src/app/api.py", "src/app/client.py") in edges
    assert ("src/app/cli.py", "src/app/api.py") in edges
    assert ("tests/test_client.py", "src/app/client.py") in edges
    assert ("scripts/run.py", "src/app/cli.py") in edges


def test_marks_tests_and_entry_points(built):
    files = by_path(built)
    assert files["tests/test_client.py"]["test"] is True
    assert files["src/app/client.py"]["test"] is False
    assert files["scripts/run.py"]["entry"] is True  # if __name__ == "__main__"
    assert files["src/app/cli.py"]["entry"] is True  # [project.scripts]


def test_names_route_handlers(built):
    entries = {f["id"]: f["entry"] for f in built["functions"]}
    assert entries["src/app/api.py:users"] == "GET /users"


def test_resolves_calls_it_can_be_sure_of(built):
    calls = {(c["caller"], c["callee"]) for c in built["calls"]}
    assert ("src/app/api.py:users", "src/app/client.py:make") in calls  # from-import
    assert (
        "src/app/api.py:sessions",
        "src/app/client.py:Session.__init__",
    ) in calls  # module attribute, class to its __init__
    assert (
        "src/app/client.py:Session.__init__",
        "src/app/client.py:make",
    ) in calls  # same file
    assert (
        "src/app/client.py:Session.get",
        "src/app/client.py:Session.fetch",
    ) in calls  # self.method()
    assert ("src/app/cli.py:main", "src/app/api.py:users") in calls
    assert ("tests/test_client.py:test_make", "src/app/client.py:make") in calls


def test_leaves_out_calls_it_cannot_resolve(built):
    callees = {c["callee"] for c in built["calls"]}
    assert all(":" in c and not c.startswith("httpx") for c in callees)
    # self.client.get() goes through an attribute holding a library object, not a local function.
    assert not any(
        c["caller"] == "src/app/client.py:Session.fetch" for c in built["calls"]
    )


def test_maps_every_dependency_to_the_lines_that_use_it(built):
    assert built["packages"]["pyyaml"] == ["yaml"]
    httpx_uses = {(u["file"], u["line"], u["function"]) for u in built["uses"]["httpx"]}
    assert ("src/app/client.py", 5, "src/app/client.py:make") in httpx_uses
    call = next(u for u in built["uses"]["httpx"] if u["line"] == 5)
    assert call["keywords"] == ["proxies"]
    assert {u["file"] for u in built["uses"]["pyyaml"]} == {"src/app/cli.py"}


def test_reports_third_party_imports_it_could_not_match(built):
    # fastapi is imported but not declared, so no distribution claims it.
    assert built["unmatched"] == ["fastapi"]


def test_skips_files_that_do_not_parse(repo):
    (repo / "src/app/broken.py").write_text("def (:\n")
    built = codemap.build(repo, {})
    assert "src/app/broken.py" not in by_path(built)
    assert "src/app/client.py" in by_path(built)
