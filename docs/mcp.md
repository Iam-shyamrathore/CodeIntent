# CodeIntent MCP server

AI coding agents (Claude Code, Codex, Cursor, Devin, anything that speaks MCP) can ask CodeIntent
the same question the GitHub App answers on pull requests: *what breaks in this repository if
dependency X moves to version Y, and what exactly do I change?* The answers are deterministic.
Both releases are compared statically against the repository's own code. Nothing is executed, and
no model writes the brief.

- Transport: MCP **streamable HTTP**, endpoint `/mcp` (stateless, so any worker can serve any
  request).
- Auth: every request needs `Authorization: Bearer $CODEINTENT_MCP_TOKEN`. A missing or wrong
  token gets `401`. The token is compared in constant time.
- Hosted endpoint: `https://codeintent-api-ded80aad7f4b.herokuapp.com/mcp`. Create a token on the
  dashboard (**AI agents** tile). It belongs to one GitHub App installation, is shown once, is
  stored only as a SHA-256 digest and can be revoked there.
- Scope: with a workspace token, the installation's own repositories (private ones included) are read
  with its installation token; any other repository is fetched as the public sees it. The
  deployment's own `CODEINTENT_MCP_TOKEN`, if set, reads public repositories only. Each call
  downloads the repository tarball for the requested ref (300 MB cap) into a temporary folder and
  deletes it afterwards.

```bash
claude mcp add --transport http codeintent https://codeintent-api-ded80aad7f4b.herokuapp.com/mcp \
  --header "Authorization: Bearer ci_mcp_…"
```

## Tools

All nine tools are read-only (`readOnlyHint: true`). Each one returns structured JSON and declares
an output schema. A failure comes back as a tool error (`isError: true`) with a short message the
agent can act on, never a stack trace.

| Tool | Arguments | Returns |
| --- | --- | --- |
| `fix_brief` | `repo`, `pull` | For a dependency PR CodeIntent has checked: each package's verdict and every edit (file, line, current code, containing function, what changed and the upstream PR, the replacement); from the workspace graph, the callers, importing files, routes/commands and tests that reach each line; manifest and lock changes; an ordered checklist and tests to run; the agent's patch, assessments, behaviour changes and security news, labelled as the agent's. Reads the stored check, so nothing is downloaded. Needs a workspace token |
| `impact` | `package`, optional `version` | Every line in the workspace's repositories that a known change in the library touches |
| `who_uses` | `package`, optional `symbol` | Where the workspace's default branches use a library, or one name in it, with file and line |
| `dependency_path` | `repo`, `package` | The shortest chains of releases that explain why a package is installed, plus the repository's own uses of the package at the top of each chain |
| `dependents` | `package` | From the ecosystem graph: its source repository (stars, licence, OpenSSF Scorecard), its dependencies and dependents, advisories, and every workspace repository and indexed open-source project that depends on it |
| `upgrade_brief` | `repo` (`owner/name` or `owner/name@ref`), `package`, `to_version` (exact or `latest`), optional `from_version` | `verdict` (`breaks` / `needs-change` / `not-checked` / `no-known-impact`), `reason`, ordered `steps`, `findings` (consumer `file:line` locations, what changed, the replacement and the library's own deprecation message), `unchecked` uses with reasons, OSV `advisories` for both versions, `declarations`, `release`, `coverage` |
| `why_pinned` | `repo`, `package` | Every declaration of the package with `file:line`, specifier, pins (`exact`, `upper_bound`, `exclusion`, ...), group, and locked version. For each deliberate pin, `introduced_by`: the commit and pull request that added it (git blame walked back past edits that kept the clause), so the author's reason can be read before relaxing it. `==` lines in requirements files are locks and are not traced. |
| `list_dependencies` | `repo` | Direct dependencies: current (locked or `==`) version, declarations, latest non-yanked PyPI release, `newer_available`, and `blocked_by` (declarations whose specifier excludes the latest). Capped at 300. |
| `advisories` | `repo` | OSV.dev advisories for every locked or exactly pinned package (direct and transitive, up to 300), split into `affected`, `not_checked` (with reason), `none_known`, and `unpinned` |

`upgrade_brief` reads the current version from a lock file, or else from a single exact `==` pin.
If neither exists, or several versions are found, it returns an error that asks for
`from_version`. A `no-known-impact` verdict never means "safe". It means every use was compared in
both releases and nothing relevant changed.

Example (abridged), `upgrade_brief` with `openai/openai-python@v1.54.4`, `httpx`, `0.27.2` →
`0.28.0`:

```json
{
  "verdict": "breaks",
  "reason": "2 change(s) in httpx 0.28.0 break code you use, at 3 place(s)",
  "steps": [
    "In src/openai/_base_client.py:1438, replace proxies= with proxy= or mounts= in the call to `httpx._client.AsyncClient`; library says: \"The 'proxies' argument is now deprecated. Use 'proxy' or 'mounts' instead.\"",
    "In src/openai/_base_client.py:857, replace proxies= with proxy= or mounts= in the call to `httpx._client.Client`; library says: \"...\"",
    "In src/openai/cli/_cli.py:179, replace proxies= with proxy= or mounts= in the call to `httpx._client.Client`; library says: \"...\"",
    "Change `httpx==0.25.2` at requirements.lock:28 to `httpx==0.28.0`"
  ]
}
```

## Running it

```bash
export CODEINTENT_MCP_TOKEN="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run python -m scripts.mcp_server          # http://127.0.0.1:8220/mcp, plus an open GET /healthz
```

| Variable | Default | Meaning |
| --- | --- | --- |
| `CODEINTENT_MCP_TOKEN` | none | Bearer token clients must send. Required when `CODEINTENT_ENV=production`, where the server refuses to start without it. Elsewhere a missing token logs a warning and leaves the endpoint open (development only). |
| `PORT` / `HOST` | `8220` / `127.0.0.1` | Listen address. Use `HOST=0.0.0.0` in containers and on Heroku. |
| `CODEINTENT_MCP_ALLOWED_HOSTS` | none | Comma-separated public hostnames (for example `mcp.example.com`). When set, requests whose `Host` header is not on the list get `421`. When unset and a token is configured, the Host check is off, because every request already needs the token. |
| `CODEINTENT_MCP_CONCURRENCY` | `2` | Repository analyses that may run at once. A caller that waits more than 60 s for a free slot gets a "busy, retry" tool error. |
| `FORWARDED_ALLOW_IPS` | `127.0.0.1` | Proxies whose `X-Forwarded-*` headers uvicorn trusts. Set it to `*` behind the Heroku router. |
| `GITHUB_TOKEN` | none | Optional. Raises GitHub's anonymous rate limit for tarball downloads. |

A long analysis keeps its response stream open with SSE keepalive pings every 15 s, so proxies that
drop idle connections (such as the Heroku router's 55 s idle window) do not cut it off. A first run
for a package takes about 10 to 60 s. Release files are cached afterwards
(`CODEINTENT_ARTIFACT_CACHE`).

## Connecting an agent

Use your deployed URL in place of `http://127.0.0.1:8220/mcp`. Keep the token in an environment
variable, not in a committed file.

### Claude Code

```bash
claude mcp add --transport http codeintent https://YOUR-HOST/mcp \
  --header "Authorization: Bearer ${CODEINTENT_MCP_TOKEN}"
```

Or commit a project `.mcp.json`. Claude Code expands `${VAR}` when it connects, so the token stays
out of the file:

```json
{
  "mcpServers": {
    "codeintent": {
      "type": "http",
      "url": "https://YOUR-HOST/mcp",
      "headers": { "Authorization": "Bearer ${CODEINTENT_MCP_TOKEN}" }
    }
  }
}
```

A first-time `upgrade_brief` can take longer than a minute. If Claude Code times out, raise its
limit with `MCP_TOOL_TIMEOUT=300000` (milliseconds).

### Cursor

`.cursor/mcp.json` in the project, or `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "codeintent": {
      "url": "https://YOUR-HOST/mcp",
      "headers": { "Authorization": "Bearer ${env:CODEINTENT_MCP_TOKEN}" }
    }
  }
}
```

Some Cursor builds do not interpolate `${env:...}` in remote headers. If the server answers `401`,
put the literal token in your global `~/.cursor/mcp.json` instead of a committed file.

### Codex

`~/.codex/config.toml` (or `.codex/config.toml` in a trusted project):

```toml
[mcp_servers.codeintent]
url = "https://YOUR-HOST/mcp"
bearer_token_env_var = "CODEINTENT_MCP_TOKEN"
tool_timeout_sec = 300
```

The CLI equivalent is
`codex mcp add codeintent --url https://YOUR-HOST/mcp --bearer-token-env-var CODEINTENT_MCP_TOKEN`.

### Devin and other clients

Add a custom MCP server with transport **streamable HTTP** (sometimes labelled "HTTP"), URL
`https://YOUR-HOST/mcp`, and the header `Authorization: Bearer <token>`.

### Python (MCP SDK)

```python
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {token}"}, timeout=httpx2.Timeout(30, read=600)) as http:
    async with Client(streamable_http_client("https://YOUR-HOST/mcp", http_client=http)) as client:
        brief = await client.call_tool("upgrade_brief", {"repo": "pallets/flask@1.1.4", "package": "itsdangerous", "to_version": "2.1.0", "from_version": "1.1.0"})
        print(brief.structured_content["steps"])
```
