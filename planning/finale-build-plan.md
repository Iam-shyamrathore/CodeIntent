# CodeIntent: Finale Build Plan (v3)

hackFront India Grand Finale · 21–22 November 2026 · status verified against `codex/deployable-v1` (`c085bef`), deployed as Heroku v11 and Vercel production

> **One line.** A GitHub App that comments on every PR that changes a dependency: whether the new version breaks the code you actually have, at which lines, why upstream changed it, what to use instead, and whether that version has known vulnerabilities.
>
> **Principle.** Few features, each one production grade. A feature is done only when it works on real repositories, fails visibly, is checked against real historical breakages, and someone who has never seen it can use it.

## 1. Why this, and why us

The pain is real but specific. 52% of developers cite breaking changes in updated dependencies as a top maintenance pain, and 49% adapt to one at least monthly (Tidelift 2019/2020 surveys). Routine bumps rarely hurt: only 3.2% of the Dependabot security PRs studied by Alfadel et al. broke builds. The cost sits in major bumps and behaviour changes the changelog does not mention, which is exactly what upstream PR and issue history records.

| Approach | Examples | What they use | Gap CodeIntent fills |
| --- | --- | --- | --- |
| Upgrade impact / merge confidence | Endor Labs upgrade impact, Renovate Merge Confidence, Snyk, Aikido AutoFix | Call graphs, crowd test pass rates | None of them read the upstream project's PRs, reviews and issues. CodeIntent ties each change to the dated upstream decision, names the replacement, and detects later reversals ("already restored", "still disputed"), with every quote checked against the source. |
| AI review of dependency PRs | Fossabot, Elastic dependency-review, thoughtbot review skill, migratowl | Changelog and model judgement | |
| API diff mapped to your lines | DepDelta, unstale, Drift, blastradius, upgrade-impact | Static API diffs | |

**Trust rule.** The verdict itself is deterministic: static usage × static API difference. The model only explains and cites, and an unsupported claim is withheld. CodeIntent never says "safe" or "secure".

**Where it lives.** The GitHub App is the product: a check and one comment on the PR, where developers already work. Telegram pushes the findings to the team, the MCP server lets the team's AI agent pull them and write the fix, and the web app handles setup and the dashboard. A developer gets full value without opening the web app.

```
PR changes a dependency ──webhook──▶ API (Heroku) ──queue──▶ Worker
  Worker: manifests → usage → releases → API compare → advisories → upstream decision → verdict
  Results: PostgreSQL (ledger, verdicts) + Neo4j (file → symbol → release → upstream PR)
  Outputs: PR check + comment (product) · Telegram (push) · MCP (agent pulls) · Web (setup + dashboard)
  Daily: every existing dependency, locked → latest = upcoming breakage + advisories
```

Full diagram: `docs/architecture.md`.

## 2. Where we are (verified, not planned)

| Capability | Status | Evidence in the repository |
| --- | --- | --- |
| Live public app | Live | Web on Vercel (`code-intent-tawny.vercel.app`) and API plus worker on Heroku (v11); Neo4j Aura kept awake by a six-hourly job (`57860d9`). |
| GitHub App `codeintent-dependency-check` | Live | Registered with Metadata and Contents read, Pull requests and Checks write, `pull_request` events. Signed webhooks, installations and repositories recorded (`7930346`); installed on a real account. |
| Manifest and lockfile parser | Built, verified on real repos | `codeintent/upgrades/manifests/` (`b70c938`, `f26f84f`): `pyproject.toml`, `*requirements*.txt`, `uv.lock`, `poetry.lock`, `setup.cfg`, `setup.py`, with source lines and pin kinds. |
| Consumer usage extractor | Built, verified on real repos | `codeintent/upgrades/usage/` (LibCST): aliases, keyword args, local subclasses, `**kwargs` forwarding, import fallbacks; cached per file and parsed in parallel (`b8554be`). |
| Release locator and verified artifacts | Built, verified on real releases | `releases.py`, `artifacts.py`: PyPI → repository → tags and commits; SHA-256-checked downloads, never installed or imported. |
| Library API compare | Built, verified on real releases | `surface.py` (griffe, static only): removals, keyword and positional changes, new required parameters, literal default changes, deprecations tied to the arguments that trigger them, replacements, `try/except` fallbacks, return types, `**kwargs` forwarding, namedtuples, shims. |
| Verdict engine and CLI | Built | `verdict.py`, `scripts/verdict.py` (`c80fb32`): Breaks you / Needs a change / No known impact / Not checked by fixed rules; replacement hints found in the release before the target (`08e7c50`). |
| Upstream decision for each change | Built, verified on real repos | `upstream.py` (`1eebc0d`): the PR that made each change, the PR that deprecated it, later restorations, quotes checked word for word; 19 of 19 real changes mapped correctly. |
| PR check run and comment | Built, deployed | `report.py`, `tasks.py` (`7d2fcf9`, `8cfde6c`): one check run and one comment edited in place, with the "why" line; any failure turns the check neutral with the reason. |
| Known-vulnerability check | Built | `advisories.py` (`afb4dcf`): OSV.dev per exact version, lowest fixed version, "Not checked" when the lookup fails. |
| Upcoming breakage | Built (engine) | `upcoming.py` (`5399fc9`): locked → latest for every direct dependency; this repository's 22 dependencies in 17 s. |
| MCP server for AI agents | Built | `mcp_server.py` (`c6e927c`): `upgrade_brief`, `why_pinned`, `list_dependencies`, `advisories` over streamable HTTP with a bearer token; `docs/mcp.md`. |
| Telegram bot `@codeintent_alerts_bot` | Built, deployed | `telegram.py` (`c085bef`): one-time link codes, alerts per reported PR, `/status`, `/why`, `/unlink`; webhook registered. |
| Web setup, dashboard and verdict report | Built, deployed | `/setup` with the install link, `/dashboard`, `/dashboard/[owner]/[name]`, `/pulls/[id]` (`3a330d1`). |
| Sign in with GitHub | Built, deployed | GitHub App user authorization with PKCE; dashboard, reports and Telegram scoped to the user's installations (`b1f6ee2`). |
| Product landing page and bento dashboard | Built, deployed | One-screen landing with a Three.js halftone hero and the three steps (install, connect Telegram, automatic); bento dashboard (`2fbd623`, `6eaaa7f`). |
| Labelled backtest set | Built | `evals/upgrades.json` (`c6cc913`): 101 cases, 19 breaks, 2 guarded controls, 80 harmless sampled from merged Dependabot PRs with passing checks. |
| Backtest harness and published numbers | Built, run on all 101 cases | `scripts/backtest.py`, `artifacts/backtest/latest.json`: 14 of 19 breaks caught (13 at the expected lines, 5 Not checked, none missed as No known impact); both guarded controls not Breaks you; 0 false Breaks you on 78 harmless upgrades (95% upper bound 4.7%), 70 No known impact. |
| Pin explainer | Partial | Every pin with file, line and kind (`why_pinned`); the introducing commit is not looked up yet. |
| Investigation workbench (previous product) | Built, kept | Evidence graph, decision extraction with reversal detection and cited answers (`temporal.py`, `investigate.py`); reachable from the footer. |
| ArgosX scan | Planned | One Pro scan of the dashboard with two test workspaces; `docs/security/remediation-log.md` records it. |

**Testing approach.** Verification runs on real repositories, real PyPI artifacts and real GitHub data, not mocks. T9 records these runs as fixtures so CI replays them offline, and the deployed API is tested against real repositories.

**Corrections to v2.**
- botocore 1.29.130 is not a breaking consumer. boto/botocore#2922 (botocore 1.29.122) guarded the import with `try/except ImportError` and a `DEFAULT_CIPHERS = None` fallback. The breaking consumer is botocore **1.29.121** (`httpsession.py:23`); 1.29.130 must return "Needs a change", not "Breaks you".
- Usage extractor and release locator are verified on real data rather than "untested"; their recorded backtests land with T9.
- Verdicts run on every PR that changes a dependency, not only Dependabot/Renovate PRs.

## 3. What ships

Python ecosystem, direct dependencies. **Must** items make the demo and the production bar; **Should** items ship when their acceptance test passes; **Could** items come after.

| Tier | Feature | What it does | Acceptance test |
| --- | --- | --- | --- |
| Must | 1. Verdict engine and CLI | Loads both library versions statically (griffe, no install, no import, SHA-256 checked artifacts), resolves every symbol and argument the consumer uses, and returns a verdict with affected lines, the replacement, and reasons for anything unchecked. | `python -m scripts.verdict --repo owner/name@ref --package P --from A --to B` prints JSON; 4/4 outages and the botocore 1.29.130 control in §4. |
| Must | 2. Upstream decision for each change | Between the two release tags: compare → commits → PRs. Each API change is linked to the PR that touched the symbol; the existing decision extraction and citation checks give the reason, replacement and any later reversal. Each library range is indexed once and shared. | Each of the 4 outages shows a cited upstream PR whose quotes pass validation. |
| Must | 3. Verdict on every PR that changes a dependency | A GitHub App receives `pull_request`, diffs the manifests and lock files, and posts one check run plus one comment, updated in place. A newly added dependency gets the pin and advisory checks (there is no old version to compare). | On the public demo repo, a real Dependabot PR gets the check and comment with no manual step. |
| Must | 4. Web app: setup and dashboard | Install flow and Telegram linking; repository overview (dependencies, locked version, verdict, pins, advisories, upcoming breakage); verdict report reusing the evidence drawer and timeline. | Links from the PR comment open on the live URL; usable at 360 / 768 / 1280 px. |
| Should | 5. MCP server | `upgrade_brief(repo, package, to_version)`, `why_pinned(repo, package)`, `list_upgrades(repo)`, `advisories(repo)` over streamable HTTP with a per-workspace token. | Claude Code fixes the demo break from the brief alone. |
| Should | 6. Telegram bot | One-time link code; alerts on "Breaks you", new advisories and liftable pins; `/status`, `/why <package>`. | Alert arrives for the demo PR. |
| Should | 7. Known-vulnerability check | Every dependency a PR adds or changes, and every dependency in the map, is looked up in OSV.dev (the source `pip-audit` uses; aggregates the PyPA and GitHub advisory databases). Shows advisory and CVE/GHSA IDs for that exact version and the lowest fixed version, with the source credited. | Correct advisories and fixed version for real known-vulnerable versions (e.g. requests 2.31.0); a failed lookup shows "Not checked", never "No known advisories". |
| Should | 8. Pin explainer | For each upper bound or exclusion: the commit/PR that added it and its stated reason. "Can be lifted" only when the verdict for locked → latest is "No known impact" and the cited cause is fixed or restored upstream; otherwise "keep" or "unknown". | Correct on a real `httpx<0.28` pin. |
| Should | 9. Workspaces | Workspace = GitHub App installation. Every row and graph node of workspace data carries `workspace_id`. | Isolation test: workspace A cannot read B. |
| Could | 10. Upcoming breakage | For each direct dependency, locked → latest release through the verdict engine, before any PR exists: "you still use `jinja2.Markup`, which 3.1 removes, at `app.py:14`". Daily and after each analysis. | Flask 1.1.2 shows jinja2 3.1 `Markup` and werkzeug 3.0 `url_quote`. |
| Could | 11. Sign in with GitHub, private repositories | GitHub App user flow, signed HTTP-only sessions. | User sees only installations they can access. |

### Verdict semantics

| Verdict | Rule | GitHub check conclusion |
| --- | --- | --- |
| **Breaks you** | Something you use is removed with no guard, an argument you pass is removed or now means something else, or a new required parameter is not passed. The replacement is named when known. | failure |
| **Needs a change** | Something you use is deprecated (the warning fires for the arguments you pass), is removed but your import falls back (botocore 1.29.130), or a default you rely on changed. | neutral |
| **No known impact** | Every use was resolved in both versions with no relevant change, and no unchecked usage touches anything the upgrade changed. Shown with what was checked; never called "safe". | success |
| **Not checked** | An unchecked usage touches a changed symbol: dynamic access, `**kwargs` pass-through, star imports, compiled-only modules, environment-dependent definitions, untyped return values, transitive dependency, release not located. Always with the reason. | neutral |

Advisories are reported next to the verdict, never folded into it: "Known advisories: GHSA-… (fixed in X)", "No known advisories", or "Advisory lookup failed".

## 4. Production bar (verified before submission)

### Backtest on real outages

| Upgrade | Consumer at old tag | What broke | Expected | Result |
| --- | --- | --- | --- | --- |
| httpx 0.27.2 → 0.28.0 | openai-python v1.54.4 | `Client(proxies=)` removed, reached through a subclass and `**kwargs` forwarding | Breaks you, correct line | **Breaks you** at `_base_client.py:857`, `:1438`, `cli/_cli.py:179`; use `proxy=` or `mounts=`; why: encode/httpx#3319, deprecated in #2879 |
| itsdangerous 2.0.1 → 2.1.0 | Flask 1.1.2 | `itsdangerous.json` removed (non-public alias) | Breaks you, correct line | **Breaks you** at `json/__init__.py:15`; use `json`; why: pallets/itsdangerous#273 |
| MarkupSafe 2.0.1 → 2.1.0 | Jinja2 2.11.3 | `soft_unicode` removed (re-export under try/except) | Breaks you, correct line | **Breaks you** at `filters.py:13`, `runtime.py:9`; use `markupsafe.soft_str`; why: pallets/markupsafe#261 |
| urllib3 1.26.15 → 2.0.0 | botocore 1.29.121 | `util.ssl_.DEFAULT_CIPHERS` removed, unguarded import | Breaks you, correct line | **Breaks you** at `httpsession.py:23`; why: urllib3/urllib3#2705 |
| urllib3 1.26.15 → 2.0.0 | botocore 1.29.130 (control) | Import guarded with a `None` fallback since #2922; but it still passes `strict=True` through `**kwargs` to `PoolManager`, which urllib3 2.0 deprecates and 2.1 rejects (fixed in boto/botocore#3036) | **Not** Breaks you | Not checked: the `**kwargs` into `PoolManager` can't be followed and `PoolManager` changed in 2.0; `DEFAULT_CIPHERS` removal shown as guarded |

- **Further real breaks caught** (Flask 1.1.2): jinja2 3.1 `Markup`/`escape` (`__init__.py:14–15`), werkzeug 2.1 `BaseResponse` (`app.py:32`) and test-client `as_tuple=`, werkzeug 3.0 `url_quote` → `urllib.parse.quote`. Every one of the 7 breaking upgrades run so far returns Breaks you.
- **Early warning:** on the release before each break, the verdict is already Needs a change for the deprecation that later broke the project (httpx 0.26 `proxies`, itsdangerous 2.0 `json`, MarkupSafe 2.0 `soft_unicode`).
- **Full labelled set:** `evals/upgrades.json` adds urllib3 2.0 `method_whitelist`, click 8.1, importlib-metadata 5, numpy 2.0, pandas 2.0, pydantic 2, SQLAlchemy 2.0 and setuptools 72 consumers at their breaking tags; cases that could not be verified are listed as dropped in `evals/README.md`.
- **Backtest result (all 101 cases, `artifacts/backtest/latest.json`):** 14 of 19 real breaks are Breaks you, 13 at the expected lines; the other 5 (numpy 2.0, pandas 2.0, pydantic 2 twice, importlib-metadata 5.0 on celery 5.2.7) are Not checked, never No known impact. Both guarded controls are not Breaks you.
- **Harmless set:** 80 patch and minor bumps merged with passing checks in repositories with 500+ stars, sampled mechanically (`scripts/sample_harmless.py`). 78 ran (2 consumer commits could no longer be downloaded): **0 false Breaks you**, 95% Wilson upper bound 4.7%; 70 No known impact, 2 Needs a change, 6 Not checked.
- **Reported:** recall on breaks, line-localisation accuracy, false-alarm rate with its interval, coverage, and the distribution of "Not checked" reasons. "Not checked" is never counted as correct. Results go to `artifacts/backtest/latest.json` and CI replays them offline.

### Reliability

Constant-time HMAC webhook verification; duplicate `X-GitHub-Delivery` ignored; webhooks return within 1 s and enqueue durable jobs with retry; GitHub rate-limit backoff and ETag caching; scan results cached per file content hash so repeat checks re-scan only changed files; every failure shows a neutral check and a reason in the PR, never a silent pass.

### Security

Least-privilege App permissions (metadata and contents read; pull requests and checks write); secrets in the environment only, never in the Next.js bundle; library code is never installed, built or imported; artifact SHA-256 checks and safe extraction; tenant-isolation test; the security pass (`security-review`, `semgrep`, threat model, Actions hardening) covers the engine and webhook.

**ArgosX** scans the live site from outside: exposed databases (including Supabase misconfiguration), API keys in page source, security headers, and with the Pro tier, behaviour behind a test login. It does not see the engine, the webhook or the App permissions, so it complements the security pass rather than replacing it. Scanning today's site would mostly test the investigation app we are replacing, so we run one Pro scan (covered by `HACKFRONT-IN26`) after the dashboard and webhook are live, with a test account per workspace to probe isolation.

### Self-serve

Live HTTPS URL (exists), a public demo repository with the App installed and an open Dependabot PR, a Telegram bot link, the MCP config to copy, an evaluator guide. An evaluator can use all of it without us.

**Deliberately out of scope** (the architecture extends to them later): other ecosystems such as npm, vulnerability reachability (whether the vulnerable function is actually called), library health scores, audit export, fleet dashboard, Slack and Linear.

## 5. Partner technology: Neo4j

One graph answers every verdict, pin and advisory question with a bounded traversal:

- `Repository → File → Usage (symbol, keyword, line) → LibrarySymbol ← APIChange → Decision → Source (PR / issue / review)`
- `Pin → IntroducedBy → Source`, and `Decision -[REVERSED_BY]→ Decision`
- `Dependency → Release → Advisory (OSV id, fixed in)`

The upstream part (`LibrarySymbol`, `APIChange`, `Decision`, `Source`, `Advisory`) is public and shared across workspaces; the consumer part carries `workspace_id`. PostgreSQL stays the ledger: jobs, webhook deliveries, verdict records, snapshots. The existing scoped retrieval and evidence graph are reused, not rebuilt.

## 6. User segments

| Segment | Their problem | Use case | Feature | Tier |
| --- | --- | --- | --- | --- |
| **Security / platform lead, 20–200 developer SaaS or fintech** (primary, payer) | Outdated and vulnerable dependencies pile up because engineering won't take upgrades it can't assess | See which upgrades break which repos and which versions carry advisories; know when a pin can go | Dashboard, PR verdicts, advisories, Telegram alerts | Must + Should |
| **Developers on those teams** | Upgrades break things; nobody remembers why a pin exists | Decide whether to merge; fix fast | PR verdict, pin explainer, MCP brief | Must + Should |
| **Open-source maintainers** (free on public repos) | Upgrades break their CI and users; pins rot | Verdicts on their own dependency PRs | Same GitHub App | Must |
| **Auditors / compliance** | Need evidence of how dependency risk was handled | Why an upgrade was deferred | Dated verdict records | Export planned |

**Validation question for interviews:** "Last time an upgrade broke something while tests passed, how did you find out, how long did it take, and was the cause in the changelog?"

## 7. Risks and dependencies

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Static diff misses behaviour-only changes | High | Diff literal defaults; surface upstream decisions on touched symbols as "Needs a change"; measure on the harmless set. |
| Dynamic Python hides usage | High | "Not checked" with the reason; never "No known impact" when an unchecked usage touches a changed symbol. |
| Renames reported only as removals | Low | Replacement named from the library's own deprecation message (checked to exist in the new release), or a same-signature object marked "likely renamed". |
| Untyped return values and library `**kwargs` | Med | Declared and inferred return types and `**kwargs` forwarding are followed; anything else is "Not checked" with the reason. |
| Environment-dependent definitions (optional third-party imports) | Low | Reported as "environment-dependent"; later resolved against the consumer's lock file. |
| GitHub App outage or permission change | Med | The same verdict runs from the CLI and MCP; a GitHub Action can post the same comment. |
| GitHub rate limits | Med | Installation tokens, ETag caching, the shared range index, existing backoff. |
| OSV.dev unavailable | Low | Cached per version with expiry; failure is shown as "Not checked", never as "No known advisories". |
| Aura Free pauses or limits indexes | Med | Keep-alive job exists; check vector/full-text support on the tier before the demo. |
| Cross-workspace leak | High | `workspace_id` everywhere; isolation test; ArgosX Pro scan with two test accounts. |
| Exposed credentials (Aura password pasted in chat) | Med | Rotate after the finale; secrets only in Heroku/Vercel environments. |

## 8. Definition of done

A team installs the CodeIntent GitHub App. From then on, every PR that changes a dependency on a Python repository gets a verdict tied to the exact lines it affects and the upstream decision behind it, with known advisories alongside. Pins are explained, upcoming breakage is listed before upgrade PRs arrive, alerts arrive in Telegram, and the fix brief goes to the team's AI agent. All four real historical breakages are caught, the botocore control is not flagged as breaking, and the known-harmless set shows no false "Breaks you".
