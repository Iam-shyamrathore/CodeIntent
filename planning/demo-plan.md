# Code Intent: demonstration plan

The demonstration should leave the audience with one concrete experience: they asked why code exists, followed the actual record, and saw how a later change altered the answer.

## Candidate corpus

Primary candidate: [encode/httpx](https://github.com/encode/httpx). It has inspectable Python code and real historical API decisions. The exact repository revision, paths, history window and fetched discussion coverage must be frozen in an index manifest during the feasibility stage.

This is a candidate selected from source review, not a claim that the corpus has already been indexed or evaluated. Choose a different repository if the evidence-density gate fails.

## Real source leads already checked

### Why the `app=` shortcut was deprecated

[HTTPX PR #3050](https://github.com/encode/httpx/pull/3050) introduces deprecation in favour of explicit WSGI/ASGI transports and points to an earlier rationale discussion. Its review contains an important change in approach: feedback on immediate removal led to a deprecation-first change before merge. The GitHub API reports a merge on 2 February 2024.

Candidate questions:

- Why was explicit transport configuration preferred?
- Did the merged change remove the shortcut immediately?
- Which review changed the migration approach?

Collect the linked rationale comment, review chronology, final diff, release notes and later removal sources. The source graph must distinguish an early proposal, the final merged deprecation, and later removal. A PR title alone is insufficient evidence for the design reason.

### A decision that was partly reversed

[HTTPX PR #2241](https://github.com/encode/httpx/pull/2241) removed RawURL after changes in the transport API made its original role obsolete. [PR #2481](https://github.com/encode/httpx/pull/2481) restored `URL.raw` using a named tuple and explicitly links [issue #2462](https://github.com/encode/httpx/issues/2462). The changelog describes a partial reversal in 0.23.2.

The GitHub API reports merges on 30 May 2022 and 2 December 2022 respectively. Merge dates and release dates are different; do not imply the removal shipped on the earlier merge date.

Candidate question: Why was this API removed, and why was access partly restored afterwards?

The checked issue reports that the public property was used by downstream libraries, including an older ddtrace integration. This is a recorded compatibility report, not a failure reproduced in this planning session. It adds useful context beyond simply observing that the method reappeared.

Collect the full issue discussion, both final diffs and release snapshots. Describe this as a historical reversal at the relevant releases. Make a statement about today's API only after confirming it against the current indexed revision.

### A source-linked compatibility boundary

[HTTPX PR #2074](https://github.com/encode/httpx/pull/2074) links issue #1850 and introduces an exception for authorization handling during an HTTP-to-HTTPS upgrade on default ports. It is a promising case for connecting a current branch condition to an earlier discussion and implemented tests.

Candidate question: Why is the HTTPS-upgrade exception narrower than a generic same-host redirect rule?

The PR confirms the scope of the implementation. Its linked discussion and review must be checked before asserting the reason for that exact boundary.

## Evidence-density gate

Before polishing the script:

- Establish at least 10 genuinely answerable rationale questions with exact supporting spans.
- Find a supported historical replacement/reversal and at least one meaningful alias/rename case.
- Find one question whose essential explanation requires history beyond the current documentation. Confirm this comparison; do not assume it because the answer cites a PR.
- Label missing-evidence and conflicting-evidence questions honestly. Do not choose an arbitrary negative question without inspecting the collected corpus.
- Record source IDs, comment/review IDs, dates, commit SHAs and snapshot hashes. Verify source links and scopes.
- Keep additional held-out questions out of prompt tuning and the scripted examples.

## Proposed four-minute live sequence

| Time | Experience | What it proves |
| --- | --- | --- |
| 0:00–0:25 | Open the landing, select the real repository, enter the workbench | The product is immediately usable |
| 0:25–1:20 | Ask a rationale question and select a claim | The answer has exact evidence and a visible relationship path |
| 1:20–2:15 | Examine the RawURL reversal or the proposal-to-deprecation sequence | Historical proposals and superseded decisions change the answer |
| 2:15–2:50 | Ask a verified missing-evidence question | The app states its limits and shows related known facts |
| 2:50–3:35 | Ask a held-out/paraphrased follow-up and inspect the source | The workflow generalizes beyond fixed question buttons |
| 3:35–4:00 | Show index coverage and a reproducible saved investigation | The evidence and boundaries remain inspectable after the talk |

The exact timing is a rehearsal target. The final sequence uses the strongest measured cases, not every source lead above.

## Integrity and resilience

- Index real sources beforehand; live indexing is a separate short demonstration if useful. Prepared data and hardcoded answers are different: questions use the real retrieval/validation path.
- A saved report may accelerate entry, but it is labelled as saved. Live answers must not be silently replaced by canned responses or a recording.
- Keep a local ready index and a recorded walkthrough as disclosed fallbacks. A provider/network outage is shown as such.
- Store raw sources and hashes so source inspection works when GitHub is temporarily unavailable. Preserve original links for independent checking.
- A retry after a rate limit does not wipe the usable index. Rehearse the error state and recovery once.
- Never stage fake confidence numbers, partner endorsement, latency metrics, repository coverage or benchmark results.

## Assets and handoff

Deliver a working hosted URL, tested local startup instructions, model/runtime configuration guide, source/third-party credits, the recorded walkthrough, a concise product explanation, and an evaluation report with observed limitations. Verify event submission availability separately; the original email's deadline is not evidence of an extension.

## Current status

Planning and source review only. No application backend, index, credentials test, live model answer, benchmark result or deployment exists yet for Code Intent.
