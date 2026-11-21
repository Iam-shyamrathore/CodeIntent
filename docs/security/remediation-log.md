# Security remediation log

Target: https://code-intent-tawny.vercel.app (web) and https://codeintent-api-ded80aad7f4b.herokuapp.com (API).

## Fixed before the baseline scan

| Date | Finding | Severity | Source | Fix | Verified |
| --- | --- | --- | --- | --- | --- |
| 21 Nov | Next.js 16.4.3: cache leak across root params in `use cache`, nested `use cache` stream leak, SVG rejection bypass in image optimisation | Moderate ×3 | `npm audit` | Upgraded to `next@16.4.6` (commit `9d5ba9a`) | `npm audit` reports 0 vulnerabilities |
| 21 Nov | Public demo unavailable after Aura Free auto-pause (risk of instance deletion after 30 paused days) | Availability | Heroku logs | Resumed instance; six-hourly read keep-alive (commit `57860d9`) | `/ready` returns 200 |

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
