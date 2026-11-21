# Phase 1 research record: upgrade verdict engine

Date: 21 November 2026. Inputs: five parallel research reviews of local clones and papers, plus hands-on experiments on real PyPI artifacts. This record explains what we reuse, what we build, and why.

## Decisions

| Component | Decision | Library (licence, pinned version ≥7 days old) | Why |
| --- | --- | --- | --- |
| PEP 440/508/503/735 semantics | Reuse | `packaging` 26.3 (Apache-2.0 OR BSD-2-Clause) | De-facto standard; includes `dependency_groups` and `pylock` |
| `requirements*.txt` | Reuse behind an adapter | `pip-requirements-parser` 32.0.1 (MIT) | pip's own parser with line numbers, `-r`/`-c`, hashes, markers; used by pip-audit and CycloneDX. Dormant since 2022, so isolated behind our interface |
| Poetry `^`/`~` constraints | Reuse | `poetry-core` 2.5.0 (MIT) | Reference implementation, incl. `^0.x` edge cases |
| `pyproject.toml`, `uv.lock`, `poetry.lock` | Build thin readers | stdlib `tomllib` + our line locator | No library covers the union with source lines; line locator follows osv-scalibr's approach |
| Consumer usage extraction | Build on LibCST | `libcst` 1.9.0 (MIT + PSF) | Scope and qualified-name metadata for aliases, `from` imports and keyword arguments; Tree-sitter stays for other languages |
| Import name → distribution | Build | Wheel `top_level.txt` / `RECORD`, approach from deptry (MIT, studied) | Works without installing; `packages_distributions()` reflects our environment, not the target's |
| Library API model | Reuse, static only | `griffe` 2.4.1 (ISC) with `allow_inspection=False` | Static model of modules, aliases, `__all__`, parameters, stubs |
| Breaking-change detection | Build on griffe's model, consumer-driven | — | See experiment 2 |
| Release artifacts | Build | PyPI JSON API, SHA-256 verified, safe extraction | Never `pip install`, never build sdists, never import |
| Release locator, upstream PRs | Build | PyPI JSON, PEP 753 label normalisation, PEP 740 provenance, GitHub compare → commits → PRs | Heuristics learned from dependabot-core (MIT) and Renovate (AGPL, studied only) |

Rejected: `aexpy` and `pidiff` (they import the library, i.e. execute code), `griffe.load_pypi` (runs `pip install`, which can execute sdist build backends), Renovate code (AGPL), `importlib.metadata.packages_distributions()` (wrong environment).

## Experiments (real artifacts from PyPI, SHA-256 verified)

### 1. griffe `find_breaking_changes` alone: 2 of 4 ground-truth outages

| Case | Result |
| --- | --- |
| httpx 0.27.2 → 0.28.0, `Client(proxies=)` | Found (`PARAMETER_REMOVED`) |
| urllib3 1.26.15 → 2.0.0, `util.ssl_.DEFAULT_CIPHERS` | Found (`OBJECT_REMOVED`) |
| itsdangerous 2.0.1 → 2.1.0, `itsdangerous.json` | **Missed**: an imported alias griffe treats as non-public |
| MarkupSafe 2.0.1 → 2.1.0, `soft_unicode` | **Missed**: re-exported from a private module under try/except |

### 2. Consumer-driven resolution on griffe's static model: 4 of 4

Resolving each symbol the consumer uses (including non-public aliases) in both versions, then comparing parameters for used keyword arguments, returned "Breaks you" for all four cases.

**Design consequence:** the verdict starts from consumer usage, not from the library's declared public API. griffe's breakage list is a secondary signal for explanations.

### 3. The real openai-python break is indirect

At `openai-python` v1.54.4 (`src/openai/_base_client.py`), `proxies=` reaches `httpx.Client.__init__` through:
`SyncHttpxClientWrapper(DefaultHttpxClient)` → `DefaultHttpxClient = _DefaultHttpxClient` (or `httpx.Client` under `TYPE_CHECKING`) → `class _DefaultHttpxClient(httpx.Client)` with `def __init__(self, **kwargs): ...; super().__init__(**kwargs)`.

**Design consequence:** the usage extractor must follow module-level aliases, local subclasses of library classes, and `**kwargs` forwarding to `super().__init__`. When forwarding cannot be proven, the result is "Not checked: keyword arguments forwarded dynamically", never "No known impact".

## Safety rules

- Never execute target or library code: `griffe.load(..., allow_inspection=False, force_inspection=False)`; no `pip install`; no sdist builds; no imports.
- Verify every artifact's SHA-256 against PyPI metadata. Extract with size caps, path-traversal checks and `tarfile` `filter="data"`. Prefer pure-Python wheels, then sdists.
- Unknown is "Not checked" with a reason, never "safe".

## Evaluation plan

- Ground truth: the 4 outages plus 14 additional verified cases (werkzeug 3.0 `url_quote`, jinja2 3.1 `escape`/`Markup`, urllib3 2.0 `method_whitelist`, setuptools 72 `command.test`, importlib-metadata 5.0 `entry_points` dict API, numpy 2.0 `NaN`/`PINF`, pandas 2.0 `append`, pydantic 2 `BaseSettings`/`ErrorWrapper`, SQLAlchemy 2.0 `MetaData.bind`), each pinned to a consumer tag.
- Harmless set: at least 50 merged Dependabot/Renovate patch or minor bumps with green CI in mature repos, sampled mechanically (a 0/50 false-alarm result gives a 95% Wilson upper bound of about 7%).
- Report recall, false-alarm rate with Wilson intervals, line-localisation accuracy, coverage, and the distribution of "Not checked" reasons. "Not checked" is never folded into accuracy.

## Sources

- AexPy, ISSRE 2022, doi:10.1109/ISSRE55969.2022.00052 (86.9% recall on 61 known breaking changes; study-only, dynamic).
- "How Do Python Framework APIs Evolve?", SANER 2020, ieeexplore 9054800.
- Ochoa et al., "Breaking Bad? Semantic Versioning and Impact of Breaking Changes in Maven Central", EMSE 2022, arXiv:2110.07889 (only 7.9% of clients affected, supporting usage-scoped verdicts).
- Reyes et al., BUMP, SANER 2024, arXiv:2401.09906 (benchmark methodology).
- Venturini et al., "I depended on you and you broke me", TOSEM 2023, arXiv:2301.04563.
- Salis et al., PyCG, ICSE 2021, arXiv:2103.00587 (dynamic features that defeat static analysis).
- Breaking-Good, SCAM 2024, arXiv:2407.03880 (explanations for breaking updates).
- Hybrid-Linker, arXiv:2107.01894; FRLink, IST 2017 (commit/issue linking heuristics).
- Rahman et al., pinning vs floating, ASE 2025, arXiv:2510.08609 (classify pins by constraint type).
- PEP 440, 503, 508, 621, 735, 740, 751, 753.
