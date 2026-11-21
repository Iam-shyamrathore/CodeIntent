# Upgrade verdict evaluation set

`upgrades.json` is a list of labelled cases. Each one says: for this consumer repo at
this commit, upgrading `package` from `from` to `to` should (or should not) affect
these call sites.

## Schema

```json
{
  "id": "httpx-0.28-openai",
  "label": "breaks | guarded | harmless",
  "consumer": {"repo": "owner/name", "ref": "<tag, branch or sha>", "commit": "<full sha of ref>"},
  "package": "httpx",            // PyPI name, lowercase
  "from": "0.27.2", "to": "0.28.0", // exact PyPI versions (both checked to exist)
  "expected": [{
    "symbol": "httpx.Client",     // fully-qualified symbol in the library
    "parameter": "proxies",       // optional: removed/renamed keyword
    "attribute": "get",           // optional: removed attribute on a return value
    "file": "src/openai/_base_client.py", "line": 857,
    "kind": "parameter-removed | import-removed | module-removed | method-removed | moved | return-type-changed"
  }],
  "evidence": ["<issue/PR/changelog URLs>", "..."],
  "notes": "free text: how it was verified, caveats"
}
```

`line` is the line in the consumer file at `commit`. For imports it is the import
line. For calls it is the line where the call starts; if the removed keyword sits on a
different line, `notes` gives that line too.

## Labels

- **breaks**: the consumer's code at that commit uses something the new version
  removed or changed, with nothing protecting it. Expected verdict: *Breaks you* (or
  *Needs a change*). `expected` lists every affected site we confirmed.
- **guarded**: the same use is there, but wrapped in a protection that actually works
  (`try/except ImportError` with a fallback, `except AttributeError`, version
  checks). Expected verdict: not *Breaks you*. `expected` still lists the site, so the
  engine can be scored on finding it and spotting the guard.
  `click-8.1-black-22.1.0` is a trap here. It is labelled **breaks** even though it
  sits inside a `try`, because the handler catches `ModuleNotFoundError` and the error
  actually raised is a plain `ImportError`.
- **harmless**: a real merged upgrade with green CI and no code changes. Expected
  verdict: *No known impact* (or *Not checked* if the package is not imported).
  `expected` is `[]`.

## How breaking and guarded cases were verified

Each hand-curated case was checked against primary sources:

1. **Library side**: the release notes or changelog at the `to` tag show the removal
   (URL in `evidence`). Where the changelog was vague, we listed the library's source
   tree at both versions (e.g. `click/_unicodefun.py` is in 8.0.4 and gone in 8.1.0;
   `werkzeug/wrappers/json.py` is in 2.0.3 and gone in 2.1.0).
2. **Consumer side**: we fetched the file at the exact ref with
   `gh api repos/O/R/contents/PATH?ref=REF -H "Accept: application/vnd.github.raw"`
   and read the line numbers from that file. `commit` comes from
   `gh api repos/O/R/commits/REF --jq .sha`.
3. **Breakage**: an issue or PR (usually in the consumer's repo) shows the failure,
   usually with a traceback that matches the file and line. Sites with no traceback
   behind them are flagged in `notes`.
4. Both versions were confirmed to exist on PyPI. Each consumer's version constraints
   were checked so the `to` version is installable (or `notes` explains how users
   ended up with it).

numpy and pandas are compiled libraries. Their cases are included on purpose, to see
how the engine handles them.

## How harmless cases were sampled

`scripts/sample_harmless.py` picks these mechanically, with no hand-picking. Re-run it
with `uv run python scripts/sample_harmless.py --target 80 --write evals/upgrades.json`.
That replaces only the `harmless` cases.

- **Frame**: GitHub search through the GraphQL `search` API.
  Query: `is:pr is:merged author:app/dependabot language:Python {head:dependabot/pip | head:dependabot/uv} merged:<day> sort:created-asc`.
  - Days run in order from 2026-08-03.
  - Each query is read 100 results per page, up to the 1000-result search cap.
  - Single-day windows are needed because one month is about 30k PRs.
  - Search cannot filter PRs by stars, so maturity is filtered afterwards.
- **Filters**, applied in this order (rejections are counted per filter and printed):
  1. The repo has at least 500 stars and is not a fork or archived.
  2. The head branch is `dependabot/pip/*` or `dependabot/uv/*`.
  3. The title is a single-package `Bump X from A to B [in DIR]`. Grouped or
     multi-package bumps are rejected.
  4. It is a patch or minor bump: same major version, no pre-release. For 0.x
     versions, only patch bumps count.
  5. It is not a bump only to docs or `.github/` requirements.
  6. At most 2 cases per repo; the first ones in sampling order are kept.
  7. The package and both versions exist on PyPI.
  8. Every PR commit is authored by Dependabot, so no human follow-up commits.
  9. Every changed file is a Python dependency manifest: requirements*.txt/.in,
     constraints*.txt, pyproject.toml, uv.lock, poetry.lock, Pipfile(.lock),
     setup.cfg or setup.py.
  10. The head commit's `statusCheckRollup` is `SUCCESS` and at least one check
      actually succeeded (neutral or skipped alone is not enough).
- **Case fields**:
  - `consumer.ref` and `consumer.commit` are the PR's `baseRefOid`, the code before
    the bump.
  - `evidence` has the PR URL, the checks URL, and the check summary as it was at
    sampling time.
- **Caveats**:
  - GitHub deletes check runs after about a year (2025 PRs return none). So the
    sampling windows must be recent, and the check summary stored in each case is the
    durable record.
  - Re-running later gives the same results only while those check runs still exist.
  - "No follow-up fix" is approximated by the commit and file rules above. Later
    commits on the base branch were not inspected.
