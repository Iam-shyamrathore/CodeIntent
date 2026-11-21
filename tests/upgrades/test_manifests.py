from pathlib import Path

import pytest

from codeintent.upgrades.manifests import scan
from codeintent.upgrades.manifests.pins import classify, from_poetry

SCALIBR = Path(__file__).parents[1] / "fixtures/upgrades/third_party/osv-scalibr"


def repo(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return tmp_path


def copy(tmp_path: Path, source: Path, name: str) -> Path:
    return repo(tmp_path, {name: source.read_text()})


def deps(result, **filters):
    return {
        d.name: d
        for d in result.dependencies
        if all(getattr(d, key) == value for key, value in filters.items())
    }


def reasons(result):
    return {(i.location.file, i.reason) for i in result.issues}


@pytest.mark.parametrize(
    "specifier,kinds",
    [
        ("<0.28", ["upper_bound"]),
        ("<=1.2.3", ["upper_bound"]),
        ("==1.2.3", ["exact"]),
        ("===1.0", ["exact"]),
        ("==0.7.*", ["wildcard"]),
        ("!=5.0", ["exclusion"]),
        ("~=1.24.0", ["compatible"]),
        (">=41.0,<42.0", ["upper_bound"]),
        (">=2.0", []),
        ("", []),
    ],
)
def test_classify_reports_each_constraint_that_limits_upgrades(specifier, kinds):
    assert [p.kind for p in classify(specifier)] == kinds


@pytest.mark.parametrize(
    "constraint,specifier,kinds",
    [
        ("^1.2", "<2.0,>=1.2", ["caret"]),
        ("^0.2.3", "<0.3.0,>=0.2.3", ["caret"]),
        ("~1.2.3", "<1.3.0,>=1.2.3", ["tilde"]),
        ("1.2.3", "==1.2.3", ["exact"]),
        (">=1,<2", "<2,>=1", ["upper_bound"]),
        ("*", "", []),
    ],
)
def test_poetry_constraints_become_pep440_with_their_original_pin_kind(
    constraint, specifier, kinds
):
    converted, pins = from_poetry(constraint)
    assert converted == specifier
    assert [p.kind for p in pins] == kinds


def test_poetry_union_constraints_are_not_guessed():
    with pytest.raises(ValueError):
        from_poetry("^1.2 || ^2.0")


def test_requirements_names_specifiers_and_lines(tmp_path):
    result = scan(
        copy(tmp_path, SCALIBR / "requirements/with_versions.txt", "requirements.txt")
    )
    found = deps(result)
    assert found["nltk"].specifier == "==3.2.2"
    assert found["nltk"].location.line == 1
    assert found["qwerty"].specifier == "==0.1"
    assert found["qwerty"].location.line == 5
    assert found["pkg-dot-name"].declared.startswith("pkg.dot.name")
    assert found["combination-also-valid"].specifier == ">=3.5"
    assert [p.kind for p in found["asdf"].pins] == ["wildcard"]
    assert [p.kind for p in found["yolo"].pins] == ["exact"]
    assert [p.kind for p in found["pkg"].pins] == ["upper_bound"]
    assert found["newspaper3k"].pins == ()
    assert all(d.format == "requirements" and d.direct for d in found.values())


def test_requirements_continuations_report_the_first_line(tmp_path):
    result = scan(
        copy(
            tmp_path,
            SCALIBR / "requirements/multiline_and_comments.txt",
            "requirements.txt",
        )
    )
    found = deps(result)
    assert (found["pkga"].location.line, found["pkgb"].location.line) == (3, 7)


def test_requirements_extras_and_markers(tmp_path):
    result = scan(
        copy(tmp_path, SCALIBR / "requirements/extras.txt", "requirements.txt")
    )
    assert deps(result)["celery"].extras == ("pytest", "redis")
    marked = scan(
        repo(
            tmp_path / "m", {"requirements.txt": 'foo5==1.0; python_version < "2.7"\n'}
        )
    )
    assert deps(marked)["foo5"].marker == 'python_version < "2.7"'


def test_requirements_environment_variables_are_reported_not_guessed(tmp_path):
    result = scan(
        copy(tmp_path, SCALIBR / "requirements/env_var.txt", "requirements.txt")
    )
    assert set(deps(result)) == {"asdf", "another"}
    assert ("requirements.txt", "environment-variable") in reasons(result)


def test_requirements_include_cycles_terminate(tmp_path):
    root = repo(
        tmp_path,
        {
            "requirements.txt": (SCALIBR / "requirements/loop.txt").read_text(),
            "other-loop.txt": "-r requirements.txt\nhttpx<0.28\n",
        },
    )
    result = scan(root)
    assert deps(result)["httpx"].location.file == "other-loop.txt"
    assert any(i.reason == "include-cycle" for i in result.issues)


def test_requirements_includes_constraints_and_non_registry_sources(tmp_path):
    root = repo(
        tmp_path,
        {
            "requirements.txt": (
                "-r requirements/base.txt\n-c constraints.txt\n"
                "-r ../../etc/passwd\n"
                "-e git+https://github.com/a/b.git#egg=b\n"
                "foo @ https://example.com/foo-1.0-py3-none-any.whl\n"
            ),
            "requirements/base.txt": "httpx>=0.27,<0.28\n",
            "constraints.txt": "urllib3<2\n",
        },
    )
    result = scan(root)
    found = deps(result)
    assert found["httpx"].location.file == "requirements/base.txt"
    assert found["urllib3"].constraint_only is True
    assert found["b"].source == "vcs" and found["b"].specifier == ""
    assert found["foo"].source == "url"
    assert ("requirements.txt", "include-outside-repository") in reasons(result)


def test_pyproject_project_and_optional_dependencies_with_lines(tmp_path):
    result = scan(
        copy(tmp_path, SCALIBR / "pyprojecttoml/optional_deps.toml", "pyproject.toml")
    )
    found = deps(result)
    assert (found["requests"].group, found["requests"].location.line) == ("main", 9)
    assert (found["black"].group, found["black"].location.line) == ("optional:dev", 15)
    assert (found["aiohttp"].group, found["aiohttp"].location.line) == (
        "optional:async",
        18,
    )


def test_pyproject_escaped_marker_strings_still_get_lines(tmp_path):
    result = scan(
        copy(tmp_path, SCALIBR / "pyprojecttoml/env_markers.toml", "pyproject.toml")
    )
    found = deps(result)
    assert found["importlib-metadata"].location.line == 6
    assert found["importlib-metadata"].marker == 'python_version < "3.10"'


def test_pyproject_dynamic_dependencies_are_reported(tmp_path):
    result = scan(
        copy(tmp_path, SCALIBR / "pyprojecttoml/dynamic_deps.toml", "pyproject.toml")
    )
    assert result.dependencies == ()
    assert ("pyproject.toml", "dynamic-dependencies") in reasons(result)


def test_pyproject_dependency_groups_uv_and_poetry_tables(tmp_path):
    text = """[project]
name = "app"
dependencies = ["httpx<0.28", "ruff"]

[dependency-groups]
test = ["pytest>=8", {include-group = "lint"}]
lint = ["mypy==1.13.0"]

[tool.uv]
dev-dependencies = ["coverage~=7.6"]

[tool.uv.sources]
ruff = { git = "https://github.com/astral-sh/ruff" }

[tool.poetry.dependencies]
python = "^3.12"
pydantic = "^2.7"
"Flask" = { version = "~2.3.2", extras = ["async"] }

[tool.poetry.group.dev.dependencies]
black = "24.10.0"
"""
    result = scan(repo(tmp_path, {"pyproject.toml": text}))
    found = deps(result)
    assert (found["httpx"].group, found["httpx"].location.line) == ("main", 3)
    assert found["ruff"].source == "vcs"
    assert (found["pytest"].group, found["pytest"].location.line) == ("group:test", 6)
    assert (found["mypy"].group, found["mypy"].location.line) == ("group:lint", 7)
    assert (found["coverage"].group, found["coverage"].location.line) == (
        "group:dev",
        10,
    )
    assert "python" not in found
    assert found["pydantic"].specifier == "<3.0,>=2.7"
    assert [p.kind for p in found["pydantic"].pins] == ["caret"]
    assert (found["flask"].extras, found["flask"].location.line) == (("async",), 18)
    assert (found["black"].group, found["black"].specifier) == (
        "group:dev",
        "==24.10.0",
    )


def test_uv_lock_supplies_locked_versions_and_marks_transitive_dependencies(tmp_path):
    root = repo(
        tmp_path,
        {
            "pyproject.toml": '[project]\nname = "uv-lockfiles"\ndependencies = ["emoji", "protobuf>=3.19.0,<5.0.0.dev0"]\n',
            "uv.lock": (SCALIBR / "uvlock/two-packages.lock").read_text(),
        },
    )
    found = deps(scan(root), format="pyproject")
    assert found["protobuf"].locked_version == "4.25.5"
    assert found["emoji"].locked_version == "2.14.0"
    locked = deps(scan(root), format="uv.lock")
    assert locked["protobuf"].direct is True and locked["protobuf"].location.line == 14
    assert "uv-lockfiles" not in locked


def test_uv_lock_root_groups_and_transitive_dependencies(tmp_path):
    result = scan(copy(tmp_path, SCALIBR / "uvlock/grouped-packages.lock", "uv.lock"))
    found = deps(result, format="uv.lock")
    assert (found["emoji"].direct, found["emoji"].group) == (True, "main")
    assert (found["click"].direct, found["click"].group) == (True, "optional:cli")
    assert (found["black"].group, found["black"].locked_version) == (
        "optional:dev,optional:test",
        "24.10.0",
    )
    assert found["click"].location.line == 39
    assert found["mccabe"].direct is False


def test_uv_lock_git_sources_and_unknown_versions(tmp_path):
    git = deps(
        scan(copy(tmp_path, SCALIBR / "uvlock/source-git.lock", "uv.lock")),
        format="uv.lock",
    )
    assert git["ruff"].source == "vcs" and git["ruff"].direct is True
    future = scan(repo(tmp_path / "f", {"uv.lock": "version = 2\n"}))
    assert ("uv.lock", "unsupported-lock-version") in reasons(future)


def test_poetry_lock_v1_and_v2_groups_and_sources(tmp_path):
    v2 = deps(
        scan(
            copy(
                tmp_path,
                SCALIBR / "poetrylock/multiple-packages.v2.lock",
                "poetry.lock",
            )
        )
    )
    assert (v2["faker"].locked_version, v2["faker"].group) == ("33.3.0", "dev,test")
    assert v2["factory-boy"].location.line == 17
    v1 = deps(
        scan(
            copy(
                tmp_path / "1",
                SCALIBR / "poetrylock/optional-package.lock",
                "poetry.lock",
            )
        )
    )
    assert (v1["numpy"].locked_version, v1["numpy"].group) == ("1.23.3", "main")
    git = deps(
        scan(
            copy(tmp_path / "g", SCALIBR / "poetrylock/source-git.lock", "poetry.lock")
        )
    )
    assert git["ike"].source == "vcs"


def test_setup_cfg_and_literal_setup_py(tmp_path):
    cfg = deps(scan(copy(tmp_path, SCALIBR / "setupcfg/valid.cfg", "setup.cfg")))
    assert (cfg["numpy"].specifier, cfg["numpy"].location.line) == ("~=1.24.0", 10)
    assert cfg["pytest"].group == "optional:dev"
    assert [p.kind for p in cfg["coverage"].pins] == ["exclusion"]
    py = deps(scan(copy(tmp_path / "p", SCALIBR / "setup/setup.py", "setup.py")))
    assert (py["jinja2"].specifier, py["jinja2"].location.line) == ("==2.11.3", 24)
    assert py["pkg2"].specifier == "==0.1.2"
    assert [p.kind for p in py["pydantic"].pins] == ["upper_bound"]


def test_setup_py_non_literal_requirements_are_reported_not_executed(tmp_path):
    root = repo(
        tmp_path,
        {
            "setup.py": "from setuptools import setup\nREQS = open('r.txt').read().split()\nsetup(install_requires=REQS)\n"
        },
    )
    result = scan(root)
    assert result.dependencies == ()
    assert ("setup.py", "non-literal-setup-argument") in reasons(result)


def test_files_outside_the_repository_are_never_read(tmp_path):
    outside = tmp_path / "outside.txt"
    outside.write_text("secret==1.0\n")
    root = tmp_path / "repo"
    root.mkdir()
    (root / "requirements.txt").symlink_to(outside)
    result = scan(root)
    assert result.dependencies == ()
    assert ("requirements.txt", "path-outside-repository") in reasons(result)


def test_invalid_toml_is_reported(tmp_path):
    result = scan(repo(tmp_path, {"pyproject.toml": "[project\nname="}))
    assert ("pyproject.toml", "invalid-toml") in reasons(result)
