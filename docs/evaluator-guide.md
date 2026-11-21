# Trying CodeIntent

CodeIntent is a GitHub App. When a pull request changes a Python dependency, it reads your code and both
releases of the library, without running either, and says whether the upgrade breaks you, where, and what to
use instead. It also checks the latest releases every day before any pull request exists.

## 1. See it on a real pull request (1 minute)

The public demo repository pins `httpx==0.27.2` and calls `httpx.Client(proxies=...)`, which httpx 0.28
removed. Dependabot opened the upgrade; CodeIntent answered on its own.

- **Breaks you:** https://github.com/Iam-shyamrathore/codeintent-demo/pull/1 (check run and comment:
  `weather/client.py:12`, use `proxy=` or `mounts=`, removed in encode/httpx#3319)
- **No known impact:** https://github.com/Iam-shyamrathore/codeintent-demo/pull/2 (requests, plus the three
  advisories the upgrade leaves behind)

## 2. Install it on your own repository (3 minutes)

1. Open https://code-intent-tawny.vercel.app and choose **Install on GitHub**. Pick one repository with a
   `pyproject.toml`, `requirements*.txt`, `uv.lock` or `poetry.lock`.
2. Within a minute or two, the dashboard's **Before you upgrade** tile lists any dependency whose latest
   release breaks or changes code you use, known advisories on the versions you run, and pins that can be
   lifted, each with file and line.
3. Open any pull request that changes a dependency (or wait for Dependabot/Renovate). One check run and
   one comment appear, and the comment is edited in place on later pushes.

The App asks for read access to contents and metadata, and write access to checks and pull requests (for
its own check and comment). Nothing in your repository is installed, imported or run.

## 3. Connect Telegram (1 minute)

On the dashboard, choose **Connect Telegram** and add `@codeintent_alerts_bot` to a group with the
one-time code. The group gets an alert when a pull request breaks or needs a change, when a new release would
break you, when a pin can be lifted, and when a version you run has a known advisory. Each finding is sent
once. `/status` and `/why httpx` work in the chat.

## 4. Let your AI agent fix it (2 minutes)

On the dashboard, the **AI agents** tile creates a token (shown once) and the command to add it:

```bash
claude mcp add --transport http codeintent https://codeintent-api-ded80aad7f4b.herokuapp.com/mcp \
  --header "Authorization: Bearer ci_mcp_…"
```

Then ask the agent, for example: *"Use codeintent's upgrade_brief for httpx to latest on
Iam-shyamrathore/codeintent-demo and apply the steps."* Tools: `upgrade_brief`, `why_pinned`,
`list_dependencies`, `advisories` ([docs/mcp.md](mcp.md)). The token reads your installation's repositories,
private ones included, and can be revoked from the same tile.

## 5. Run the engine locally

```bash
uv sync
uv run python -m scripts.verdict --repo openai/openai-python@v1.54.4 --package httpx --from 0.27.2 --to 0.28.0
```

## How well it works

`artifacts/backtest/latest.json`, over 101 labelled upgrades from real repositories:

- 19 real breakages: 14 called **Breaks you** (13 at the lines named in the original issues); the other 5 are
  **Not checked**, never **No known impact**.
- 2 controls whose import has a fallback: neither called **Breaks you**.
- 80 harmless upgrades from merged Dependabot PRs with passing CI: 78 ran, **0 false Breaks you** (95% upper
  bound 4.7%).

"No known impact" means every use of the library was compared in both releases and nothing it relies on
changed. It is never a promise that the upgrade is safe.
