# CodeIntent: Finale Build Plan

hackFront India Grand Finale · 21–22 November 2026

**One line:** CodeIntent tells you whether a dependency upgrade breaks your code, and why. It names the exact lines it affects and the upstream decision behind the change. It explains every pin you have and hands the fix to your AI agent.

**Principle:** few features, each one production grade. A feature counts as done only when it works on real repositories, handles failure, is tested against real historical breakages, and is usable by someone who has never seen it.

## 1. Where we are

**Works in the build today**

- Public GitHub import of PRs, reviews, issues, commits, diffs and current files, with progress, cancel, retry and checkpoint recovery.
- Immutable, hashed, dated source snapshots in PostgreSQL.
- Tree-sitter extraction of symbols and calls for Python, JS/TS, Go, Rust and Java.
- Neo4j evidence graph with scoped vector/full-text retrieval and bounded traversal.
- Decision extraction (introduce, deprecate, remove, restore, replace) with aspect-scoped detection of when a later decision replaces or reverses an earlier one.
- Cited answers with deterministic quote/offset checks; a second-model review withholds unsupported claims (30/30 regression cases pass, 7/7 unsupported prompts refused).
- Web workbench: evidence drawer, decision timeline, graph, live investigation stages, saved shareable reports.
- Operator authentication, quotas, health/readiness checks, migrations, CI.

**Mocked, hardcoded or missing**

- The public examples are bundled fixtures. There is no live public URL yet (only Heroku/Vercel configuration).
- No user accounts: a single operator token. Public repositories only.
- Import selects recent PRs, not the PRs between two releases.
- No dependency parsing, no link from consumer code to library symbols.
- No GitHub automation, notifications or agent integration.
- Next.js 16.4.3 carries a known security advisory.

## 2. Where we will be by 12 PM, 22 November

Python ecosystem only, done properly.

**The GitHub App is the product.** Its findings appear where developers already work: a check and a comment on the PR. Telegram pushes those findings to the team, and the MCP server lets the team's AI agent pull them to write the fix. The web app supports all of this: installing, connecting Telegram, and a dashboard of every repository. Developers should get full value without opening it.

1. **GitHub App and accounts.** Install on an organisation or repository (public or private). Sign in with GitHub. All data, reports and alerts are scoped to the installing workspace.
2. **Dependency map.** Parse `pyproject.toml`, `requirements*.txt`, `uv.lock`, `poetry.lock`, `setup.cfg` and `setup.py`. LibCST finds every imported library symbol and keyword argument the code uses, with file and line.
3. **Upstream decision index.** For a library and a version range, import the PRs, reviews, issues and changelog between the two release tags, then extract removals, deprecations, restorations and replacements. Each library range is indexed once and shared across every workspace.
4. **Upgrade verdict on every PR that changes a dependency**, whether Dependabot, Renovate or a developer opened it. A GitHub check plus one comment:
   - **Breaks you**, **Needs a change**, **No known impact**, or **Not checked** (with the reason).
   - The affected lines, the upstream decision, its cited PR, the recommended replacement, and any later reversal.
   - It never says "safe". Anything it could not analyse is shown as not checked.
   - A newly added dependency has no earlier version to compare, so it gets the pin and vulnerability checks instead.
5. **Pin explainer.** For every upper bound or exclusion (e.g. `httpx<0.28`): the commit/PR that added it and why. When upstream has fixed or restored the cause, it says "this pin can be lifted".
6. **Telegram bot.** Link a workspace with a one-time code. It alerts on breaking upgrades and liftable pins, supports `/status` and `/why <package>`, and links to the full report.
7. **MCP server for AI agents.** Claude Code, Cursor, Codex or Devin call `upgrade_brief(package, to_version)` and `why_pinned(package)`, get back the exact lines, reason and recommended replacement, and write the fix.
8. **Web app (setup and dashboard).** Install flow, Telegram linking, a repository overview (dependencies, verdicts, pins, advisories, upcoming breakage) and a verdict report built on the existing evidence UI.
9. **Known-vulnerability check.** Every dependency a PR adds or changes, and every dependency already in the map, is looked up in OSV.dev (the database `pip-audit` uses, aggregating the PyPA and GitHub advisory databases). It shows the advisory IDs for that exact version and the lowest version that fixes them, with the advisory source credited. It says "No known advisories", never "secure", and it does not claim the vulnerable code is reachable.
10. **Upcoming breakage.** For every existing dependency, compare the locked version with the latest release using the verdict engine, before any upgrade PR exists: "you're on Jinja 3.0 and still use `jinja2.Markup`, which 3.1 removes, at `app.py:14`". Shown on the overview, in `/status` and through MCP.

**Production bar (verified before submission)**

- **Backtest on real outages.** At old public tags, each of these must return "Breaks you" with the correct line:
  - httpx 0.28 `proxies` → `openai-python`
  - itsdangerous 2.1 `json` → Flask 1.1
  - MarkupSafe 2.1 `soft_unicode` → Jinja2 2.11
  - urllib3 2.0 `DEFAULT_CIPHERS` → botocore 1.29.121 (`httpsession.py:23`, unguarded). botocore 1.29.122+ (boto/botocore#2922) guards the import and falls back to `None`, so 1.29.130 must *not* return "Breaks you"

  A labelled set of upgrades known to be harmless must produce no false "Breaks you". Results are published with the numbers.
- **Reliability.** Verified webhook signatures, idempotent delivery handling, durable jobs with retry, GitHub rate-limit backoff, and clear failure states in the PR, in Telegram and on the web.
- **Security.** Least-privilege App permissions, secrets kept in the environment only, tenant-isolation tests, two ArgosX scans with a remediation log, and the Next.js advisory resolved.
- **Self-serve.** A live HTTPS URL; a public demo repository with the App installed and an open Dependabot PR; a Telegram bot link; setup docs. An evaluator can use all of it without us.

**Deliberately out of scope** (the architecture extends to them later): other ecosystems such as npm, vulnerability reachability (whether the vulnerable function is actually called), library health scores, audit export, fleet dashboard, Slack and Linear.

## 3. User segments

| Segment | Their version of the problem | Use cases | Feature that serves them | Status at 12 PM |
| --- | --- | --- | --- | --- |
| **Security / platform lead at a 20–200 developer SaaS or fintech company** (primary, payer) | Outdated and vulnerable dependencies pile up because engineering won't take upgrades it can't assess | See which upgrades break which repos; get alerted when a blocked upgrade or pin clears | Repository overview, verdicts, Telegram alerts | Working |
| **Developers on those teams** | Upgrades break things; nobody remembers why a pin exists | Know whether to merge a dependency PR; fix a breaking upgrade quickly | PR verdict, pin explainer, MCP brief to their AI agent | Working |
| **Open-source maintainers** (free on public repositories) | Upgrades break their users and their own CI; old pins rot | Verdicts on their own dependency PRs; lift stale pins | Same GitHub App on public repositories | Working |
| **Auditors / compliance** | Need evidence of how dependency risk was handled | Review why an upgrade was deferred or a pin kept | Dated verdict records (export planned) | Planned |

## 4. Partner technology: Neo4j (deepened)

Neo4j becomes the core of the product. One graph connects:

`Repository → File → Used symbol / argument → Library symbol → Upstream decision (removed / deprecated / restored / replaced) → Cited PR / issue`

It also connects `Pin → Introducing change → Reason → Upstream fix or restoration`.

Every verdict and pin explanation is a bounded traversal of this graph, and the shared upstream index lives in it. The product cannot answer without it.

## 5. Definition of done

A team installs the CodeIntent GitHub App. From then on, every PR that changes a dependency on a Python repository gets a verdict tied to the exact lines it affects and the upstream decision behind it, known advisories are shown for every dependency, upcoming breakage is listed before upgrades arrive, and every pin is explained. Alerts arrive in Telegram, and the fix brief goes to the team's AI agent. All four real historical breakages are caught, with no false alarms on the known-harmless set.
