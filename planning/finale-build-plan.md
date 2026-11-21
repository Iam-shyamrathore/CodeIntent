# CodeIntent: Finale Build Plan (v3)

hackFront India Grand Finale · 21–22 November 2026 · status verified against `main` (`2543af4`) and `codex/deployable-v1` (`18bb4aa`) at 18:50 IST, 21 Nov

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
| Live public app | Live | Web on Vercel (`code-intent-tawny.vercel.app`, HTTP 200) and API on Heroku v6 (`/ready` 200); Neo4j Aura kept awake by a six-hourly job (`57860d9`). |
| Public GitHub import with progress, cancel, retry, checkpoint recovery | Built | `codeintent/github.py`, `codeintent/tasks.py` (Procrastinate on PostgreSQL, orphan recovery). |
| Immutable hashed source snapshots; Neo4j evidence graph with scoped vector/full-text retrieval | Built | `store.py`, `graph.py`; real PostgreSQL/Neo4j integration tests (`docs/validation.md`). |
| Decision extraction (introduce / deprecate / remove / restore / replace) with reversal detection; cited answers with quote/offset checks and second-model review | Built | `temporal.py`, `investigate.py`; 30/30 regression cases, 7/7 unsupported prompts refused (regression evidence, not a held-out study). |
| Web workbench: evidence drawer, timeline, graph, real investigation stages, withheld-claim counts, shareable reports with OG previews | Built | `18e8cef`. |
| Next.js security advisory | Fixed | 16.4.3 → 16.4.6 (`9d5ba9a`); `npm audit` 0 vulnerabilities. |
| Manifest and lockfile parser: `pyproject.toml`, `requirements*.txt`, `uv.lock`, `poetry.lock`, `setup.cfg`, `setup.py`, with source lines and pin classification | Built | `codeintent/upgrades/manifests/` (`b70c938`); osv-scalibr fixtures plus the real consumers at their broken tags. |
| Consumer usage extractor (LibCST: aliases, keyword args, local subclasses, `**kwargs` forwarding, import fallbacks; dynamic access recorded as unknown) | Built, verified on real repos | `codeintent/upgrades/usage/` (`d46dbcb`, `11ccc49`). Exact lines confirmed on openai-python, Flask, Jinja and botocore; 12/12 sampled usages true. Fallback fix: names rebound in `except ImportError` mark later uses as guarded. |
| Release locator (PyPI → repository → tags/commits) and verified artifact download | Built, verified on real releases | `releases.py`, `artifacts.py` (`9e65454`). 12 real upgrades located; commits match GitHub (httpx `80960fa3`, numpy `1d49c7f7`); renamed, missing and yanked cases handled. |
| Library API compare (griffe, static only) | Built, verified on real releases | `codeintent/upgrades/surface.py` (`09fe0ac`, `18bb4aa`). 4/4 outages at the issue lines; 5 further real breaks found; 0 removal/parameter findings on 6 harmless upgrades. Detail in §5. |
| Blind-spot reduction (T29) | In progress | (a) `try/except ImportError` definitions done: botocore "Not checked" 21–23 → 3. (b) return types, (c) library `**kwargs`, (d) renames, (e) caching/parallel scans remain. |
| Verdict engine and CLI, backtest harness | Not built | T8, T9. |
| Known-vulnerability check (OSV.dev), upcoming breakage | Not built | T30, T31; added in v3. |
| Upstream range index, workspaces data model, pin explainer, GitHub App, Telegram, MCP, new web pages | Not built | No code yet. |
| ArgosX scan | Planned | One Pro scan once the dashboard and webhook are live; not a hard requirement. `docs/security/remediation-log.md` records it. |
| Accounts | Single operator token | No user accounts; public repositories only. |

**Testing approach.** Verification runs on real repositories, real PyPI artifacts and real GitHub data, not mocks. T9 records these runs as fixtures so CI replays them offline, and the deployed API is tested against real repositories.

**Corrections to v2.**
- botocore 1.29.130 is not a breaking consumer. boto/botocore#2922 (botocore 1.29.122) guarded the import with `try/except ImportError` and a `DEFAULT_CIPHERS = None` fallback. The breaking consumer is botocore **1.29.121** (`httpsession.py:23`); 1.29.130 must return "Needs a change", not "Breaks you".
- Usage extractor and release locator are verified on real data rather than "untested"; their recorded backtests land with T9.
- Verdicts run on every PR that changes a dependency, not only Dependabot/Renovate PRs.

## 3. What ships by 12 PM, 22 November

Python ecosystem, direct dependencies. About 17 working hours remain, so scope is tiered. **Must** items make the demo and the production bar; **Should** items ship if their checkpoint is met; **Could** items are cut first.

| Tier | Feature | What it does | Acceptance test |
| --- | --- | --- | --- |
| Must | 1. Verdict engine and CLI | Loads both library versions statically (griffe, no install, no import, SHA-256 checked artifacts), resolves every symbol and argument the consumer uses, and returns a verdict with affected lines, the replacement, and reasons for anything unchecked. | `python -m scripts.verdict --repo owner/name@ref --package P --from A --to B` prints JSON; 4/4 outages and the botocore 1.29.130 control in §5. |
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

## 4. Schedule and cut rules (IST)

| Window | Work | Checkpoint / cut rule |
| --- | --- | --- |
| 18:50–21:00 | T29 blind spots, time-boxed about 30 min each: (b) return types, (c) library `**kwargs`, (d) renames, (e) scan cache, parallel scan, PyPI metadata cache. Parallel agents: scan speed, OSV advisories, labelled backtest cases, GitHub App webhook. | Anything unfinished at 21:00 moves after the GitHub App. True findings unchanged on every real case. |
| 21:00–22:30 | T8 verdict engine and CLI. | 4/4 outages "Breaks you" with the right line; botocore 1.29.130 "Needs a change". If not, the demo uses only the cases caught and §5 reports the miss. |
| 22:30–00:00 | T9 backtest harness over the labelled cases and ≥50 harmless bumps. | Numbers published in `artifacts/backtest/latest.json`. |
| 00:00–03:30 | Data model and shared range index; upstream PR linking; GitHub App webhook, check run and comment; demo repo with a Dependabot PR. | Real PR gets a check by 03:30. If the App is blocked, fall back to a GitHub Action that runs the CLI and posts the same comment. |
| 03:30–06:00 | MCP server; Telegram alerts; OSV advisories. | Claude Code fix from the brief; Telegram alert for the demo PR. |
| 06:00–08:30 | Web setup flow, repository overview, verdict report. | PR comment links open on the live URL. |
| 08:30–10:00 | Pin explainer; upcoming breakage; failure states; structured logs. | Pins cut to "introduced by" if over time. |
| 10:00–11:00 | ArgosX Pro scan of the dashboard with two test workspaces; fix findings; remediation log; evaluator guide. | Report and fixes logged by 11:00. |
| 11:00–12:00 | Code freeze, rehearse the demo twice, submit. | No merges after 11:15. |

**Cut order if time runs short:** upcoming breakage → pin "can be lifted" (keep "introduced by") → Telegram commands (keep alerts) → sign-in and private repositories → T29 (b)/(c).

The market track (3 interviews with security/platform leads, Market Fit Canvas, persona matrix, pitch) runs in parallel and does not block code.

## 5. Production bar (verified before submission)

### Backtest on real outages

| Upgrade | Consumer at old tag | What broke | Expected | Result now (T7, `18bb4aa`) |
| --- | --- | --- | --- | --- |
| httpx 0.27.2 → 0.28.0 | openai-python v1.54.4 | `Client(proxies=)` removed, reached through a subclass and `**kwargs` forwarding | Breaks you, correct line | `proxies=` removed at `_base_client.py:857`, `:1438`, `cli/_cli.py:179`; hint "Use 'proxy' or 'mounts' instead" |
| itsdangerous 2.0.1 → 2.1.0 | Flask 1.1.2 | `itsdangerous.json` removed (non-public alias) | Breaks you, correct line | removed at `json/__init__.py:15` |
| MarkupSafe 2.0.1 → 2.1.0 | Jinja2 2.11.3 | `soft_unicode` removed (re-export under try/except) | Breaks you, correct line | removed at `filters.py:13`, `runtime.py:9` |
| urllib3 1.26.15 → 2.0.0 | botocore 1.29.121 | `util.ssl_.DEFAULT_CIPHERS` removed, unguarded import | Breaks you, correct line | removed at `httpsession.py:23` |
| urllib3 1.26.15 → 2.0.0 | botocore 1.29.130 (control) | Import guarded with a `None` fallback since #2922 | Needs a change, **not** Breaks you | removed, marked guarded at `httpsession.py:52`, `:118`, `:119` |

- **Extra breaks found so far** (real releases, Flask 1.1.2): jinja2 3.1 `Markup`/`escape` (`__init__.py:14–15`), werkzeug 2.1 `BaseResponse` (`app.py:32`), werkzeug 3.0 `url_quote` (`helpers.py:30`) and `url_parse` (`testing.py:18`), each with the library's own "will be removed in…" message. The remaining research cases (urllib3 2.0 `method_whitelist`, numpy 2.0 `NaN`, pandas 2.0 `append`, pydantic 2 `BaseSettings`, SQLAlchemy 2.0 `MetaData.bind`, …) are added in T9; any case we cannot verify is dropped and listed.
- **Harmless set:** ≥50 patch/minor bumps that mature repositories merged with green CI, sampled mechanically. So far 6 real harmless upgrades give 0 removal or parameter findings. Target 0 false "Breaks you"; with 0/50 the 95% Wilson upper bound is about 7%, and we publish that bound, not "0%".
- **Reported:** recall on breaks, line-localisation accuracy, false-alarm rate with its interval, coverage, and the distribution of "Not checked" reasons. "Not checked" is never counted as correct. Results go to `artifacts/backtest/latest.json` and CI replays them offline.

### Reliability

Constant-time HMAC webhook verification; duplicate `X-GitHub-Delivery` ignored; webhooks return within 1 s and enqueue durable jobs with retry; GitHub rate-limit backoff and ETag caching; scan results cached per file content hash so repeat checks re-scan only changed files; every failure shows a neutral check and a reason in the PR, never a silent pass.

### Security

Least-privilege App permissions (metadata and contents read; pull requests and checks write); secrets in the environment only, never in the Next.js bundle; library code is never installed, built or imported; artifact SHA-256 checks and safe extraction; tenant-isolation test; the security pass (`security-review`, `semgrep`, threat model, Actions hardening) covers the engine and webhook.

**ArgosX** scans the live site from outside: exposed databases (including Supabase misconfiguration), API keys in page source, security headers, and with the Pro tier, behaviour behind a test login. It does not see the engine, the webhook or the App permissions, so it complements the security pass rather than replacing it. Scanning today's site would mostly test the investigation app we are replacing, so we run one Pro scan (covered by `HACKFRONT-IN26`) after the dashboard and webhook are live, with a test account per workspace to probe isolation.

### Self-serve

Live HTTPS URL (exists), a public demo repository with the App installed and an open Dependabot PR, a Telegram bot link, the MCP config to copy, an evaluator guide. An evaluator can use all of it without us.

**Deliberately out of scope** (the architecture extends to them later): other ecosystems such as npm, vulnerability reachability (whether the vulnerable function is actually called), library health scores, audit export, fleet dashboard, Slack and Linear.

## 6. Partner technology: Neo4j

One graph answers every verdict, pin and advisory question with a bounded traversal:

- `Repository → File → Usage (symbol, keyword, line) → LibrarySymbol ← APIChange → Decision → Source (PR / issue / review)`
- `Pin → IntroducedBy → Source`, and `Decision -[REVERSED_BY]→ Decision`
- `Dependency → Release → Advisory (OSV id, fixed in)`

The upstream part (`LibrarySymbol`, `APIChange`, `Decision`, `Source`, `Advisory`) is public and shared across workspaces; the consumer part carries `workspace_id`. PostgreSQL stays the ledger: jobs, webhook deliveries, verdict records, snapshots. The existing scoped retrieval and evidence graph are reused, not rebuilt.

## 7. User segments

| Segment | Their problem | Use case | Feature | At 12 PM |
| --- | --- | --- | --- | --- |
| **Security / platform lead, 20–200 developer SaaS or fintech** (primary, payer) | Outdated and vulnerable dependencies pile up because engineering won't take upgrades it can't assess | See which upgrades break which repos and which versions carry advisories; know when a pin can go | Dashboard, PR verdicts, advisories, Telegram alerts | Must + Should |
| **Developers on those teams** | Upgrades break things; nobody remembers why a pin exists | Decide whether to merge; fix fast | PR verdict, pin explainer, MCP brief | Must + Should |
| **Open-source maintainers** (free on public repos) | Upgrades break their CI and users; pins rot | Verdicts on their own dependency PRs | Same GitHub App | Must |
| **Auditors / compliance** | Need evidence of how dependency risk was handled | Why an upgrade was deferred | Dated verdict records | Export planned |

**Validation question for interviews:** "Last time an upgrade broke something while tests passed, how did you find out, how long did it take, and was the cause in the changelog?"

## 8. Risks and dependencies

| Risk | Impact | Mitigation |
| --- | --- | --- |
| Static diff misses behaviour-only changes | High | Diff literal defaults; surface upstream decisions on touched symbols as "Needs a change"; measure on the harmless set. |
| Dynamic Python hides usage | High | "Not checked" with the reason; never "No known impact" when an unchecked usage touches a changed symbol. |
| Renames reported only as removals | Med | T29(d): replacement from the old alias target, quoted names in the deprecation message that exist in the new release, then "likely renamed" from a matching signature. |
| Untyped return values and library `**kwargs` | Med | T29(b)/(c): follow declared return types and `**kwargs` forwarding; otherwise "Not checked". |
| Environment-dependent definitions (optional third-party imports) | Low | Reported as "environment-dependent"; later resolved against the consumer's lock file. |
| Scope added in v3 (T29–T31) squeezes the schedule | High | Time-boxed; cut order in §4; advisories are small and reuse the dependency map. |
| GitHub App registration or approval delays the primary journey | High | Register in the first hour; GitHub Action fallback posts the same comment. |
| GitHub rate limits | Med | Installation tokens, ETag caching, the shared range index, existing backoff. |
| OSV.dev unavailable | Low | Cached per version with expiry; failure is shown as "Not checked", never as "No known advisories". |
| Aura Free pauses or limits indexes | Med | Keep-alive job exists; check vector/full-text support on the tier before the demo. |
| Cross-workspace leak | High | `workspace_id` everywhere; isolation test; ArgosX Pro scan with two test accounts. |
| Exposed credentials (Aura password pasted in chat) | Med | Rotate after the finale; secrets only in Heroku/Vercel environments. |

## 9. Definition of done

A team installs the CodeIntent GitHub App. From then on, every PR that changes a dependency on a Python repository gets a verdict tied to the exact lines it affects and the upstream decision behind it, with known advisories alongside. Pins are explained, upcoming breakage is listed before upgrade PRs arrive, alerts arrive in Telegram, and the fix brief goes to the team's AI agent. All four real historical breakages are caught, the botocore control is not flagged as breaking, and the known-harmless set shows no false "Breaks you".
