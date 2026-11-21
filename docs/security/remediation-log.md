# Security remediation log

Target: https://code-intent-tawny.vercel.app (web) and https://codeintent-api-ded80aad7f4b.herokuapp.com (API).

## Fixed before the baseline scan

| Date | Finding | Severity | Source | Fix | Verified |
| --- | --- | --- | --- | --- | --- |
| 21 Nov | Next.js 16.4.3: cache leak across root params in `use cache`, nested `use cache` stream leak, SVG rejection bypass in image optimisation | Moderate ×3 | `npm audit` | Upgraded to `next@16.4.6` (commit `9d5ba9a`) | `npm audit` reports 0 vulnerabilities |
| 21 Nov | Public demo unavailable after Aura Free auto-pause (risk of instance deletion after 30 paused days) | Availability | Heroku logs | Resumed instance; six-hourly read keep-alive (commit `57860d9`) | `/ready` returns 200 |

## Production hardening

| Date | Finding | Severity | Source | Fix | Verified |
| --- | --- | --- | --- | --- | --- |
| 21 Nov | CI had failed on every push since the backtest landed (formatting, stale migration count), so nothing was gating `main` | High (process) | GitHub Actions | Fixed both (`94f5f65`); CI now also runs Neo4j and live engine tests | 157 passed, 0 skipped in CI |
| 21 Nov | Release and upstream lookups called GitHub unauthenticated (60 requests/hour) because no `GITHUB_TOKEN` is set in production | Medium (availability) | Code review | Engine uses the installation token for the duration of each job (`a207e10`) | `tests/upgrades/test_repository.py` |
| 21 Nov | Missed `installation_repositories` webhook left 41 deselected repositories recorded as watched | Medium (data scope) | Production data vs `GET /installation/repositories` | Reconcile with GitHub daily and on any 404 (`abb4baa`) | Production now records exactly the 1 selected repository |
| 21 Nov | Worker exceeded memory (1.1 GB on a 512 MB dyno, R15) during the first repository sweep and was killed | High (availability) | Heroku logs | Scans run one at a time in a spawned child process (`fb7d894`) | Production scan completed with no R14/R15 |
| 21 Nov | Third-party Actions referenced by mutable tags; default job token permissions | Medium (supply chain) | Actions review | Pinned by commit, `contents: read`, `persist-credentials: false` | `.github/workflows/ci.yml` |
| 21 Nov | Secrets exposed in the setup conversation: webhook secret, Telegram bot token, a GitHub client secret; the App private key was printed in an operator terminal session | High | Operator review | **Open: rotate all four** (App settings → generate a new private key and webhook secret; @BotFather `/revoke`; new client secret), then update Heroku and Vercel config | Pending |

## ArgosX baseline scan

Report: `argosx-baseline.pdf` (to be added).

| ID | Finding | Severity | Status | Fix / justification |
| --- | --- | --- | --- | --- |

## ArgosX final scan

Report: `argosx-final.pdf` (to be added).

| ID | Finding | Severity | Status | Fix / justification |
| --- | --- | --- | --- | --- |

## Accepted risks

| Risk | Why it is acceptable | Review date |
| --- | --- | --- |
