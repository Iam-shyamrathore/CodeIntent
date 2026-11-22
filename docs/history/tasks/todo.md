# Tasks: CodeIntent upgrade verdicts

Plan: [tasks/plan.md](plan.md). Sizes: S = 1–2 files, M = 3–5 files. Each task leaves the system working.
Standard checks: `uv run pytest -q`, `uv run ruff check . && uv run ruff format --check .`, `npm run typecheck && npm run build`.

## Phase 0: Gates and baseline

- [x] **T1 Resolve the Next.js security advisory** (S). Skills: `vercel-react-best-practices`
  - Accept: the upgrade is applied; `npm run build` passes with no security error; landing, investigate and report routes all return 200.
  - Files: `package.json`, `package-lock.json`, any API changes the upgrade requires.
- [x] **T2 Deploy the current app to a live HTTPS URL** (M). Skills: `shipping-and-launch`, `neo4j-aura-provisioning-skill`, `render-deploy` or `deploy-to-vercel`
  - Accept: public `/health` returns 200; authenticated `/ready` returns 200; the saved HTTPX report opens on the public URL.
  - Files: `heroku.yml` / `render.yaml`, `docs/deployment.md`, `.env.example`. Deps: T1.
- [x] **T3 ArgosX baseline scan**: dropped. Not a hard requirement, and scanning today's site would mostly test the investigation app being replaced. Folded into T28.

### Checkpoint 0
- [x] Live URL works, all standard checks pass.

## Phase 1: Verdict engine (offline, highest risk)

- [x] **T4 Manifest and lockfile parser** (M). Skills: `modern-python`, `property-based-testing`
  - Accept: `pyproject.toml` (PEP 621 + uv/poetry groups), `requirements*.txt` (incl. `-r`, markers, hashes), `uv.lock` and `poetry.lock` all parse to `{name, specifier, locked_version, direct, source_line}`; names normalised per PEP 503; pins (upper bounds, `!=`, `==`) are flagged.
  - Verify: property tests for specifier round-trips; fixtures from real repos.
  - Files: `codeintent/upgrades/manifests/*`, `codeintent/upgrades/models.py`, `tests/upgrades/test_manifests.py`.
- [x] **T5 Usage extractor** (M). Skills: `test-driven-development`
  - Accept: LibCST finds imports (aliases, `from x import y`), attribute chains rooted at imported names, call keyword arguments, module-level aliases, local subclasses of library classes and `**kwargs` forwarding to `super().__init__`, each with file and line. Import names map to distributions (e.g. `yaml` → PyYAML). Dynamic access (`getattr`, `**kwargs` pass-through, star imports) is recorded as an *unknown* with a reason.
  - Files: `codeintent/upgrades/usage/extractor.py`, `codeintent/upgrades/usage/distributions.py`, `tests/upgrades/test_usage.py`.
- [x] **T6 Release locator** (S)
  - Accept: given `package, from, to`, return the repository from PyPI `project_urls`, the release artifacts for both versions, and the matching git tags or commits. When it can't, it returns an explicit "not located" reason.
  - Files: `codeintent/upgrades/releases.py`, `codeintent/upgrades/artifacts.py`, `tests/upgrades/test_releases.py`.
- [x] **T7 Library API surface and consumer-driven diff** (M). Skills: `differential-review`
  - Accept: load each version statically with griffe (`allow_inspection=False`); resolve every used symbol (including non-public aliases) in both versions; compare parameters for used keyword arguments; add DeprecationWarning detection. Extract the API from each version's released source (modules, classes, functions, parameters, kw-only args, `**kwargs`, literal defaults, `__all__`, `warnings.warn(Deprecation…)` sites) and diff it into `APIChange{kind: removed|param_removed|renamed|default_changed|deprecated, symbol, detail}`. httpx 0.27.2 → 0.28.0 must include `Client(proxies=)` removed.
  - Files: `codeintent/upgrades/surface.py`, `tests/upgrades/test_surface.py`. Deps: T6.
  - Done: `check(old, new, usage)` returns `removed | parameter-removed | parameter-required | parameter-moved | default-changed | deprecated` plus typed unchecked reasons. `renamed` is not detected; removals carry the old release's deprecation message, which usually names the replacement. Verified on real artifacts: 4/4 outages at the issue lines, botocore 1.29.130 guarded, jinja2 3.1 and werkzeug 2.1/3.0 variants on Flask 1.1.2, and 6 harmless upgrades with no removal or parameter findings.
- [x] **T29 Reduce static blind spots** (M). Skills: `fp-check`, `variant-analysis`
  - Accept: (a) names defined under `try: import / except ImportError: fallback` resolve to the `try` side; (b) attributes of return values follow declared return types; (c) library `**kwargs` is followed to the function that receives it, a few hops deep; (d) removals name the replacement from the old alias target, quoted names in the deprecation message that exist in the new release, or a same-signature object marked "likely renamed"; (e) usage scans are cached per file content hash, run in parallel, and PyPI metadata is cached. Re-run on every real case so far: "Not checked" counts fall, true findings unchanged, no new false findings; openai first check under 3 s, repeat under 1 s.
  - Files: `codeintent/upgrades/surface.py`, `codeintent/upgrades/usage/extractor.py`, `codeintent/upgrades/artifacts.py`. Deps: T7.
- [x] **T8 Verdict engine and CLI** (M)
  - Accept: usage × API changes → `Breaks you | Needs a change | No known impact | Not checked`, with affected lines and the reasons anything wasn't checked. `python -m scripts.verdict --repo owner/name@ref --package P --from A --to B` prints JSON.
  - Files: `codeintent/upgrades/verdict.py`, `scripts/verdict.py`, `tests/upgrades/test_verdict.py`. Deps: T4, T5, T7.
- [x] **T9 Backtest harness** (M). Skills: `fp-check`, `regression-hunt`
  - Accept: all 4 breakages return "Breaks you" with the right line: httpx 0.28 → `openai-python`, itsdangerous 2.1 → Flask 1.1.x, MarkupSafe 2.1 → Jinja2 2.11.x, urllib3 2.0 → botocore 1.29.121 (and botocore 1.29.130, which guards the import, must not). The 14 additional verified cases from the research record are labelled too, and a mechanically sampled set of ≥50 harmless upgrades produces 0 false "Breaks you" (Wilson 95% upper bound reported). Results go to `artifacts/backtest/latest.json`; CI replays recorded fixtures offline.
  - Files: `evals/upgrades.json`, `scripts/backtest.py`, `tests/test_backtest.py`, `.github/workflows/*`. Deps: T8.

### Checkpoint 1: is the core real?
- [x] 4/4 breakages caught, 0 false alarms on the harmless set, every "Not checked" has a reason. **Review with the team before continuing.**

## Phase 2: Explanations, shared index, pins

- [x] **T10 Upstream explanation for each change** (M). Skills: `neo4j-cypher-skill`
  - Accept: collect the PRs, reviews and issues between the two tags (compare API → commits → associated PRs). Link each API change to the PR that touched that symbol, then extract decisions and replacement guidance through the existing `temporal`/citation path. Detect reversals by checking the symbol in later releases. All quotes pass `domain` citation validation.
  - Files: `codeintent/github.py` (range mode), `codeintent/explain.py`, `codeintent/temporal.py`, `tests/test_explain.py`. Deps: T7.
- [ ] **T11 Data model** (M). Skills: `supabase-postgres-best-practices`, `neo4j-modeling-skill`
  - Accept: migration `006_workspaces.sql` adds workspaces, installations, repositories, webhook_deliveries, library_ranges, pins and verdicts, each scoped by `workspace_id` where it's workspace data. Neo4j gets constraints for Repository/File/Usage/LibrarySymbol/APIChange/Decision/Pin; migration replay test passes.
  - Files: `migrations/006_workspaces.sql`, `codeintent/store.py`, `codeintent/graph.py`, `tests/test_storage_integration.py`.
- [ ] **T12 Shared library-range index job** (M). Skills: `neo4j-driver-python-skill`
  - Accept: durable job `index_library_range(package, from, to)` is idempotent and cached, so the same range is computed only once. Results are projected to Neo4j; progress and errors are visible.
  - Files: `codeintent/tasks.py`, `codeintent/graph.py`, `codeintent/store.py`. Deps: T10, T11.
- [ ] **T13 Repository analysis job and graph verdict** (M). Skills: `neo4j-query-tuning-skill`
  - Accept: analysing a repo stores its usage and dependencies (workspace-scoped). The verdict is a bounded Cypher traversal that matches the T8 result on all backtest cases, and the query is profiled with no full scans.
  - Files: `codeintent/tasks.py`, `codeintent/graph.py`, `codeintent/verdict.py`. Deps: T12.
- [x] **T14 Pin explainer** (M)
  - Accept: for each pin, find the commit/PR that introduced it (history of the manifest file, then the line) and its cited reason. Say "can be lifted" only when evidence shows the cause was fixed or restored upstream; otherwise "keep" or "unknown". Tested on `httpx<0.28` in a real repo.
  - Files: `codeintent/pins.py`, `codeintent/github.py`, `tests/test_pins.py`. Deps: T4, T10.

- [x] **T30 Known-vulnerability check** (S). Skills: `supply-chain-risk-auditor`, `security-and-hardening`
  - Accept: batch-query OSV.dev for every dependency (name + locked or pinned version, ecosystem PyPI); return advisory IDs, aliases (CVE/GHSA), summary, severity when given, and the lowest fixed version; cache per (package, version) with expiry; failures become "Not checked: advisory lookup failed", never "No known advisories". Verified against real known-vulnerable versions (e.g. requests 2.31.0, urllib3 1.26.15) and their fixed versions. Shown in the PR comment, Telegram, MCP and the overview.
  - Files: `codeintent/upgrades/advisories.py`. Deps: T4.
- [x] **T31 Upcoming breakage scan** (S)
  - Accept: for each direct dependency, run the verdict from the locked version to the latest non-yanked release on PyPI; list removed or deprecated APIs the code uses, with lines. Runs after each analysis and daily. Verified on Flask 1.1.2 (jinja2 3.1 `Markup`, werkzeug 3.0 `url_quote`).
  - Files: `codeintent/upgrades/upcoming.py`. Deps: T8.

### Checkpoint 2
- [ ] Backtest still 4/4 and 0 false alarms through the graph path; isolation test passes (workspace A cannot read B).

## Phase 3: GitHub App (primary journey)

- [x] **T15 GitHub App and installation auth** (S). Code done (`codeintent/github_app.py`); waiting on App registration and Heroku config. Skills: `gh-cli`, `security-and-hardening`
  - Accept: App manifest with least-privilege permissions (contents:read, pull_requests:write, checks:write, metadata:read); JWT plus a cached installation token client; private repos readable after install.
  - Files: `codeintent/github_app.py`, `codeintent/settings.py`, `docs/github-app.md`.
- [x] **T16 Webhook endpoint** (M). Skills: `fastapi`, `api-and-interface-design`
  - Accept: HMAC signature verified (constant time); duplicate `X-GitHub-Delivery` ignored. Handles `installation*`, `pull_request` from Dependabot/Renovate, and `push` touching manifests. Each event enqueues a job and returns within 1 s.
  - Files: `codeintent/api.py`, `codeintent/webhooks.py`, `tests/test_webhooks.py`. Deps: T11, T15.
- [x] **T17 Dependency PR parser** (S)
  - Accept: the package, from and to versions are taken from the PR's manifest diff (the authority), with the title as fallback. Multi-package and grouped PRs are handled.
  - Files: `codeintent/depprs.py`, `tests/test_depprs.py`.
- [x] **T18 Check run and PR comment** (M). Skills: `pr-writer`
  - Accept: one check run plus one comment per PR, updated in place on new commits. Shows the verdict line, affected lines, upstream decision with link, replacement and reversal. Failures show a clear neutral state, never a silent pass.
  - Files: `codeintent/report_pr.py`, `codeintent/tasks.py`, `tests/test_report_pr.py`. Deps: T13, T16, T17.
- [x] **T19 Sign in with GitHub and workspace sessions** (M). Skills: `security-and-hardening`, `secret-serialization`
  - Accept: web sign-in via the GitHub App user flow; sessions are signed and HTTP-only. A user only sees workspaces whose installation they can access, and reports are workspace-scoped.
  - Files: `app/api/auth/*`, `lib/session.ts`, `codeintent/api.py`, `tests/test_api_contract.py`. Deps: T11, T15.

### Checkpoint 3: primary journey
- [x] On a real repository: install the App, Dependabot opens a PR, and the check and comment appear on their own with the correct verdict.

## Phase 4: Telegram and MCP

- [x] **T20 Telegram bot** (M)
  - Accept: link a chat to a workspace with a one-time code from the web. Alerts fire on "Breaks you", "Needs a change" and liftable pins; `/status` and `/why <package>` work. Webhook secret-token check in production, long polling locally; rate-limited.
  - Files: `codeintent/telegram.py`, `codeintent/api.py`, `codeintent/tasks.py`, `tests/test_telegram.py`. Deps: T13, T14.
- [x] **T21 MCP server** (M). Skills: `mcp-builder`, `fastmcp-server`, `test-quality`
  - Accept: tools `list_upgrades(repo)`, `upgrade_brief(repo, package, to_version)` and `why_pinned(repo, package)` return structured briefs (lines, reason, replacement, citations). Workspace token auth. Verified from Claude Code against the demo repo.
  - Files: `codeintent/mcp.py`, `tests/test_mcp.py`, `docs/mcp.md`. Deps: T13, T14.

### Checkpoint 4
- [ ] A breaking PR triggers a Telegram alert (done), and Claude Code fixes it from the MCP brief (not yet tried end to end).

## Phase 5: Web app

- [ ] **T22 Install and onboarding flow** (M). Skills: `ui-ux-pro-max`, `web-design-guidelines`
  - Accept: install App → choose repos → link Telegram → copy MCP config. Empty, loading and error states work at 360/768/1280 px.
  - Files: `app/(app)/onboarding/*`, `components/onboarding.tsx`, `app/styles.css`. Deps: T19, T20, T21.
- [ ] **T23 Repository overview** (M). Skills: `vercel-react-best-practices`
  - Accept: per repo, a table of dependencies with locked version, latest version, verdict, pins and lift status, and last analysis time; sortable, keyboard accessible.
  - Files: `app/(app)/repos/[id]/page.tsx`, `components/dependency-table.tsx`, `codeintent/api.py`. Deps: T13, T14.
- [ ] **T24 Verdict report page** (M)
  - Accept: affected lines, upstream decision and timeline, replacement, reversal; reuses the evidence drawer and graph; shareable inside the workspace only.
  - Files: `app/(app)/verdicts/[id]/page.tsx`, `components/workbench.tsx`, `components/evidence.tsx`. Deps: T18.

### Checkpoint 5
- [ ] A first-time user completes install → verdict → fix without help (tested with someone outside the team). Skills: `webapp-testing`, `playwright`.

## Phase 6: Harden and ship

- [x] **T25 Observability** (S). Skills: `observability-and-instrumentation`
  - Accept: structured logs carry delivery, job and workspace IDs; counters for verdicts, failures and GitHub rate-limit waits; failed jobs are visible in the web UI and alert in Telegram for operators.
- [~] **T26 Security pass** (M). Threat model, Actions pinning and remediation log done; credential rotation and semgrep pending. Skills: `security-review`, `security-best-practices`, `security-threat-model`, `gha-security-review`, `github-actions-hardening`, `agentic-actions-auditor`, `secret-serialization`, `semgrep`
  - Accept: threat model written to `docs/security/threat-model.md`; all critical and high findings fixed or justified in the remediation log; workflows pinned by SHA with least-privilege tokens.
- [x] **T27 Demo repository and evaluator guide** (S)
  - Accept: a public demo repo has the App installed and an open Dependabot PR showing a real "Breaks you". `docs/evaluator-guide.md` explains how to try it without us; the backtest numbers are published.
- [ ] **T28 ArgosX Pro scan of the dashboard** (S). Skills: `security-review`
  - Accept: one Pro scan once the dashboard and webhook are live, with a test login for each of two workspaces; the report is saved to `docs/security/argosx.pdf`; the remediation log says what was found, what was fixed, what remains and why. **By 11 AM, 22 Nov.**

### Final checkpoint
- [ ] Definition of done in the Build Plan is met on the live URL. All standard checks pass. Build Plan items 1–10 demonstrably work.

## Market track (parallel, non-blocking)

- [ ] **M1 Interview script and 3 interviews** with security/platform leads (assumed / found / changed). Skills: `startup-design`
- [ ] **M2 Market Fit Canvas** with every claim sourced. Skills: `deep-research`, `competitors-analysis`
- [ ] **M3 Persona Use Case Matrix** matching section 3 of the Build Plan.
- [ ] **M4 Pitch and demo script** (2-minute and 5-minute versions). Skills: `startup-pitch`, `pptx`
