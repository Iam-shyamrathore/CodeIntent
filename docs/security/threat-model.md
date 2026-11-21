# CodeIntent threat model

Scope: the GitHub App (webhooks, checks, comments), the API and worker on Heroku, the web dashboard on
Vercel, the Telegram bot, the MCP endpoint, and the analysis engine. Last reviewed 21 Nov 2026.

## Assets

| Asset | Where it lives | Why it matters |
| --- | --- | --- |
| Customers' private source code | Downloaded per analysis into a temporary folder, deleted afterwards | Read access to private repositories is the most sensitive thing the App holds |
| GitHub App private key, webhook secret | Heroku config only | The key mints installation tokens for every customer |
| Installation tokens | In memory, cached until 5 minutes before expiry | One hour of read access to an installation's repositories |
| Verdicts, scans, pin origins | PostgreSQL, scoped by `installation_id` | Reveal dependency and code structure of private repositories |
| Telegram bot token, MCP tokens | Heroku config; MCP tokens only as SHA-256 | Send messages as the bot; read a workspace's verdicts and repositories |
| Service secret, operator key, session secret | Heroku and Vercel config | The web server's authority over the API |

## Trust boundaries

1. **GitHub → API** (`/github/webhook`): anyone can POST. Only HMAC-SHA256-signed bodies are accepted.
2. **Browser → web server**: users authenticate with GitHub OAuth (state + PKCE). Sessions are signed
   HttpOnly cookies listing the installations GitHub says the user can access.
3. **Web server → API** (`/app/*`): only the web server holds the service secret; it adds the session's
   installation scope to every read and checks access again on the result.
4. **Agents → API** (`/mcp`): bearer tokens, each bound to one installation.
5. **Telegram → API** (`/telegram/webhook`): Telegram's `secret_token` header, compared in constant time.
6. **Engine → third-party code**: library releases and customer repositories are untrusted input.

## Threats and mitigations

| # | Threat | Mitigation | Tested by |
| --- | --- | --- | --- |
| T1 | Forged or replayed webhooks queue work or poison the ledger | HMAC over the raw body, constant-time compare; one row per `X-GitHub-Delivery`, duplicates ignored | `tests/test_github_app.py` (GitHub's documented vector, tampering cases) |
| T2 | Code execution through a malicious repository or library release | Nothing is installed, built, imported or run: LibCST and griffe read source statically (`allow_inspection=False`); tarballs are size-capped and unpacked with the `data` filter; PyPI artifacts are SHA-256 checked | `tests/upgrades/*`, artifact checks |
| T3 | User of installation A reads installation B's verdicts, scans or reports | Every `/app/*` read takes the session's installation list; repositories resolve only through live installations; unknown and forbidden both return 404 | `tests/test_dashboard_api.py`, `tests/test_scans.py::test_scan_results_are_scoped_to_the_callers_installations` |
| T4 | An MCP token reads another workspace's private code | A workspace token uses its installation token only for repositories that installation watches; anything else is fetched as the public sees it, so GitHub refuses private code | `tests/test_mcp_workspaces.py` |
| T5 | Stolen MCP token | Stored only as SHA-256, shown once, revocable from the dashboard, last use recorded; revoked tokens get 401 at once | `tests/test_mcp_workspaces.py` |
| T6 | Telegram chat linked to the wrong workspace | One-time 8-character codes, stored hashed, valid 15 minutes, created only for an installation in the user's session | `tests/test_telegram.py` |
| T7 | Secrets leak through logs or stored errors | Failures store and log only the exception class name; the bot token is never in exception text; webhook payloads are not logged | `tests/test_telegram.py::test_transport_errors_never_carry_the_token` |
| T7b | A report link from a private repository's PR comment is opened by someone outside the workspace | `/pulls/{id}` shows reports on private repositories only to sessions that include the installation; signed out, private and unknown reports get the same sign-in prompt; private PR titles stay out of link-preview metadata | `app/pulls/[id]/page.tsx` |
| T8 | CSRF on dashboard actions (Telegram codes, scans, MCP tokens) | Same-origin check on every POST/DELETE route, JSON bodies, SameSite cookies | Route code in `app/api/*` |
| T9 | Supply chain of CI itself | Actions pinned by commit; read-only job token; checkout keeps no credentials | `.github/workflows/ci.yml` |
| T10 | A missed webhook leaves access to deselected repositories recorded | The daily sweep and any scan that gets a 404 re-read the installation's repositories from GitHub and drop what is gone, with their scans | `tests/test_scans.py::test_a_repository_gone_on_github_reconciles_the_installation` |
| T11 | Resource exhaustion from huge repositories or many scans | 300 MB tarball cap, 40 packages and 8 projects per scan, scans one at a time in a child process, MCP concurrency 1 on the web dyno | Production run: 1.1 GB before isolation, no R14/R15 after |

## Residual risks

| Risk | Why it is accepted for now | Next step |
| --- | --- | --- |
| Access is per installation, not per repository: in an organisation, anyone who can reach one installed repository sees verdicts for all of that installation's repositories | Matches how GitHub scopes the App; acceptable for single-team installations | Check repository access per user via `GET /user/installations/{id}/repositories` |
| The GitHub response cache on the worker's disk can hold data from private repositories | Cache entries are only reached after an authenticated read of the same repository succeeded; the disk is ephemeral and single-tenant | Key cache entries by installation, or skip the cache for private repositories |
| Credentials pasted into chat during setup (webhook secret, Telegram token, a client secret) and the App private key printed in an operator session | Exposure was limited to the setup conversation | Rotate all four (see the remediation log) |
