# Agents

CodeIntent's verdicts come from static analysis and never from a model. Agents add what static analysis
cannot see, on top of those facts and the code graph, and are always shown as an agent's, beside the verdict.

| Agent | When | Reads | Adds |
| --- | --- | --- | --- |
| `patcher` | After a PR check with breaks | the repository, the code graph | An edit per break. CodeIntent applies the edits to a copy, checks it parses and runs its analysis again: only an edit that removes the break is marked "checked by CodeIntent". |
| `investigator` | After a PR check with uses it could not follow | the repository, the code graph | `likely-breaks`, `likely-fine` or `unclear` per use, with quotes checked against the file. |
| `behaviour` | After a PR check | the library's GitHub release notes, the code graph | Behaviour changes that touch names the repository uses, with the release note quoted exactly. |
| `news` | Daily, per workspace | the web, through Serper | Security reports for locked packages, from pages it read. CodeIntent decides whether the locked version is in range, whether OSV.dev lists it, and alerts Telegram. |

Their output goes to the PR comment (its own section), the run page, the **Security news** page, and the
MCP tool `fix_brief` (`agent_patch`, `agent_assessments`, `agent_behaviour`, `security_news`).

## Harness (`codeintent/agent/harness.py`)

- **The loop** (after Codex CLI): every turn the model must call tools; results are appended, so the
  prompt only grows at the end and prompt caching applies; the turn ends when it calls `submit`. Several
  calls in a turn run in parallel and return in order. Tool output is cut to 8,000 characters (head and
  tail); an empty result says so.
- **Toolsets and budgets** (after Hermes Agent): a registry of read-only tools in groups (`code`,
  `graph`, `upstream`, `web`); each agent gets only its groups. Each agent has a turn budget, is warned as
  it runs out, and on its last turn may only submit. Rate limits and server errors are retried, then the
  fallback model (`CODEINTENT_AGENT_FALLBACK_MODEL`) is tried. The transcript summary (tools, turns, tokens,
  answers sent back, outcome, prompt hash) is stored with the output.
- **Prompts in tiers** (after Hermes Agent's `SOUL.md`): `prompts/SOUL.md` is the identity every agent
  shares, then the safety rules (fixed in code), then the role file. The specifics (repository, package,
  versions) go in the task, so the prefix is stable. Prompts ship with CodeIntent; nothing in a reviewed
  repository can become an instruction.
- **Validated answers**: `submit` must match the agent's schema and pass deterministic checks (quotes
  found in the source, `before` text found in the file, links that were actually read). Problems go back to
  the model as the result of its `submit`, until its last turn.
- **Graph tools** (after CodexGraph and LocAgent): `callers` and `uses_of` answer "who calls this" and
  "where is this used" from Neo4j, multi-hop, instead of text search.
- **File tools** (after SWE-agent's agent-computer interface): a 100-line numbered viewer and a short
  search that lists `file:line: line`.
- **Validate the repair** (after Agentless): localisation is CodeIntent's own analysis; the agent repairs;
  CodeIntent validates by analysing the patched copy.

## Untrusted input

Following "Design Patterns for Securing LLM Agents against Prompt Injections" (Beurer-Kellner et al.,
2025) and CaMeL (Debenedetti et al., 2025): once an agent has read untrusted text it must not be able to
cause anything with consequences.

- Every tool only reads; there is no tool to write, post or call out with data.
- `read_page` opens only links a `web_search` returned in the same session, and never private addresses,
  so a page cannot point the agent at an address of an attacker's choosing.
- Only validated fields are used, by CodeIntent's code. Agent prose shown in PR comments has links, images
  and HTML removed; diffs are fenced.
- Agents run in their own queue and child process; they never block or change a check.

## Sources

- Codex CLI, "Unrolling the Codex agent loop" (OpenAI, 2026) and https://github.com/openai/codex
- Hermes Agent, https://github.com/NousResearch/hermes-agent (agent loop, tools runtime, SOUL.md)
- CodexGraph (Liu et al., NAACL 2025), arXiv:2408.03910
- LocAgent (Chen et al., ACL 2025), arXiv:2503.09089
- Agentless (Xia et al., FSE 2025), arXiv:2407.01489
- SWE-agent (Yang et al., NeurIPS 2024)
- Design Patterns for Securing LLM Agents against Prompt Injections, arXiv:2506.08837
- CaMeL: Defeating Prompt Injections by Design, arXiv:2503.18813
