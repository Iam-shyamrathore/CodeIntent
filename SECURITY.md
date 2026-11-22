# Security policy

## Reporting a vulnerability

Please report vulnerabilities privately through GitHub's **Report a vulnerability** (Security
advisories) on this repository, not in a public issue. Include the affected URL or file, steps to
reproduce, and the impact you observed. We acknowledge reports within 72 hours and aim to fix
high-severity issues within 7 days.

Please do not access other users' data, degrade the service, or run automated scans against the
production endpoints beyond what is needed to demonstrate an issue.

## Supported versions

Only the `main` branch, which is what is deployed, receives security fixes.

## How CodeIntent protects your code

- Customer repositories and library releases are **only parsed, never installed, imported, built or
  executed**. Downloads are size-capped, hash-checked and extracted with Python's `data` filter.
- The GitHub App asks for read access to contents and metadata, and write access only to checks and
  pull requests, for its own check run and comment. Installation tokens are short-lived and kept in
  memory.
- Every dashboard, API, MCP and graph read is scoped to one GitHub App installation.
- MCP tokens are per workspace, shown once, stored only as SHA-256 digests, and revocable.
- LLM agents have only read-only tools. Untrusted text (web pages, release notes, PR text) cannot
  trigger a write, a post or an outbound request with data. Agent output is validated against a
  schema and its sources before it is shown, and it never changes a verdict.
- Webhooks from GitHub and Telegram are authenticated (an HMAC signature and a secret token),
  compared in constant time and de-duplicated.
- Logs and stored errors hold exception class names, not payloads or secrets.

Details, with the test that covers each control, are in
[docs/security/threat-model.md](docs/security/threat-model.md). Fixes and open items are tracked in
[docs/security/remediation-log.md](docs/security/remediation-log.md).
