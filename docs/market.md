# Market fit

## The problem

Dependabot and Renovate made it easy to *open* dependency upgrades. Deciding whether to *merge* them
is still manual. For each PR a developer has to:

- read the changelog;
- guess which of their files use the changed API;
- trust that CI covers those paths.

Many teams end up with a backlog of dependency PRs that nobody wants to own. Others merge on green CI
and find the break in production. Either way, upgrades get deferred, and known vulnerabilities stay
in production longer.

Version numbers don't solve it. In CodeIntent's labelled set of real upgrades
([`evals/upgrades.json`](../evals/upgrades.json)), 15 distinct upgrades broke real projects, and
**6 of those 15 were minor-version bumps**: click 8.0→8.1, jinja2 3.0→3.1, markupsafe 2.0→2.1,
itsdangerous 2.0→2.1, werkzeug 2.0→2.1 and httpx 0.27→0.28. A semver-based policy ("auto-merge
minors") would have shipped every one of them.

## Who it is for

| Who | Pain | What CodeIntent changes |
| --- | --- | --- |
| **Python product teams** (5–50 engineers, private services, Dependabot or Renovate on) | Dependency PRs pile up; nobody knows which are safe | Each PR says `Breaks you`, `Needs a change`, `No known impact` or `Not checked`, with the line and the fix |
| **Platform / DevEx teams** | Upgrade campaigns (pydantic 2, SQLAlchemy 2, numpy 2) across many repositories | One workspace graph shows every repository and line a library change touches (`impact`, `who_uses`) |
| **Security teams** | A CVE fix sits unmerged because the upgrade "might break something" | The advisory and the impact on the code arrive together, so the fix can merge with evidence |
| **Teams using AI coding agents** | Agents fix things well once told what's wrong, but they start every session cold | `fix_brief` hands the agent the exact edits, the evidence and the tests to run |
| **Open-source maintainers** | Same as product teams, in public | Free on public repositories |

## Alternatives, and where CodeIntent fits

| Tool | What it does well | What it doesn't answer | Relationship |
| --- | --- | --- | --- |
| **Dependabot / Renovate** | Finds new releases and opens PRs | Whether *your* code breaks, and where | Complement: CodeIntent reviews the PRs they open |
| **Dependabot compatibility score / Renovate Merge Confidence** | Aggregate signals: how other repositories' CI fared, release age, adoption | Your call sites. Other teams' green CI says nothing about the API you use | Complement: a per-repository answer instead of a crowd average |
| **AI PR reviewers** (CodeRabbit and similar) | General review of the diff | A dependency PR's diff is one line in a lock file; the breaking change is in the library, not the diff | Different input: CodeIntent compares both releases' APIs against your usage |
| **Agentic IDEs** (Claude Code, Cursor, Codex) | Fixing code when asked | Nobody asks about each of the 40 open bot PRs; the answers aren't deterministic or kept, and nothing runs before a PR exists | Customer, not competitor: CodeIntent feeds them through MCP (`fix_brief`) |
| **SCA / security scanners** (Snyk, Socket, OSV-based tools) | Known vulnerabilities and malicious packages | Whether the fixing upgrade breaks your code | Complement: CodeIntent shows the advisory and the upgrade's impact together |

## Why it's defensible

1. **Deterministic, line-level verdicts.** Both releases are parsed statically and compared against the
   APIs this repository actually calls. The same input always gives the same answer, with a file, a line
   and the upstream PR that made the change. Over 101 labelled real upgrades it raised **0 false
   `Breaks you` on 78 harmless upgrades that ran**, and caught 14 of 19 real breakages. The other 5 were
   reported as `Not checked`, never as safe ([backtest](../artifacts/backtest/latest.json)).
2. **A graph built at install, not on demand.** Every repository is mapped into Neo4j when the App is
   installed: files, imports, functions, calls, tests, entry points and dependency uses. So the blast
   radius is ready before the PR exists, and "Before you upgrade" warns ahead of the bot PR.
3. **A shared ecosystem graph that compounds.** Release API diffs, dependency edges, advisories and
   upstream PR evidence are public facts, computed once and reused by every customer. Each new
   installation and each indexed open-source project makes the next answer faster and better
   covered, while private code stays in its own workspace.
4. **Agents as a distribution channel.** As more code is written by agents, the buyer's question shifts
   from "can the agent fix it?" to "what exactly should it fix, and can I trust that?". CodeIntent's
   verdicts and `fix_brief` are built for that: exact, verifiable, machine-readable.

## Business model

Pricing is set in `lib/plans.ts`. Billing isn't live yet; every plan is free during the beta.

| Plan | Price (placeholder) | For |
| --- | --- | --- |
| Free | $0 | Public repositories: PR checks, daily "Before you upgrade", Telegram alerts |
| Team | $29 per month per GitHub account | Private repositories, AI-agent tokens over MCP, pin origins |
| Self-hosted | Custom, annual | Your own GitHub App and infrastructure; code never leaves your network |

Free public repositories are the growth loop as well as a give-back. Every CodeIntent comment on a
public Dependabot PR is visible to everyone who opens that PR. Developers who see it in open source
bring it to work, where private repositories are the paid tier.

## Go to market

1. **GitHub App install:** one click, no configuration, results within minutes on the default branch.
   Then listing on the GitHub Marketplace.
2. **Open source first:** public PR comments and the ecosystem graph, seeded from the 67 open-source
   projects in the labelled set.
3. **MCP directories and agent ecosystems** (Claude Code, Cursor, Codex, Devin): `fix_brief` as the
   reason to connect.
4. **Upgrade campaigns as a wedge into platform teams:** "show me every line pydantic 2 breaks across
   our organisation" is one query on the workspace graph.

## Where it stands

Fully working, not a mock-up:

- The GitHub App, worker and dashboard run in production (Heroku, Vercel, Neo4j Aura).
- Live PR comments on the demo repository
  ([PR #4](https://github.com/Iam-shyamrathore/codeintent-demo/pull/4)).
- Telegram alerts, the MCP server and a daily security-news agent.

There are no paying customers yet, and pricing is a placeholder. The next step is design partners:
Python teams with an existing Dependabot backlog.

**What we'll measure with design partners:**
- median time to merge for dependency PRs, and the share merged rather than closed or left open;
- the false `Breaks you` rate, reported from the field;
- how often a suggested fix (from the agent or `fix_brief`) is accepted unchanged;
- time from a security advisory to the merged fix.

## Risks

| Risk | Answer |
| --- | --- |
| GitHub builds this into Dependabot | It would need an API-surface diff engine for each library plus a code graph for each repository. The shared ecosystem graph and the verdict engine are the accumulated asset, and the MCP integration works with every agent, not one vendor |
| LLMs get good enough to just read the changelog | Changelogs are incomplete. The breaks above were found by comparing the APIs, and a verdict has to be reproducible to gate a merge. LLMs are used where they add value, with their output labelled |
| Python only | The graph model is language-neutral. JavaScript/TypeScript (via the TypeScript compiler and `.d.ts` files) is next |
| Trusting a third party with private code | Nothing is installed or executed; access is read-only and scoped per installation; a self-hosted option exists |

## Roadmap

1. JavaScript/TypeScript verdicts.
2. Fix commits on the dependency PR, verified by CodeIntent before they're proposed.
3. Slack alongside Telegram.
4. Access per repository within an organisation.
5. Organisation-wide upgrade-campaign views.
