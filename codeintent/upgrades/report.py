"""Render verdicts as the GitHub PR comment and check run. Pure functions over verdict records."""

from __future__ import annotations

from codeintent.upgrades.advisories import AdvisoryCheck
from codeintent.upgrades.verdict import LABELS, Finding, UpgradeVerdict

MARKER = "<!-- codeintent:dependency-report -->"
CHECK_NAME = "CodeIntent dependency check"
ORDER = ["breaks", "not-checked", "needs-change", "no-known-impact"]
CONCLUSIONS = {
    "breaks": "failure",
    "not-checked": "neutral",
    "needs-change": "neutral",
    "no-known-impact": "success",
}
MAX_ROWS = 12
MAX_BODY = 60_000
WHAT = {
    "removed": "removed",
    "parameter-removed": "no longer accepts this argument",
    "parameter-required": "now requires an argument you don't pass",
    "parameter-moved": "positional arguments changed order",
    "deprecated": "deprecated",
    "default-changed": "default changed",
}


def worst(verdicts: list[UpgradeVerdict]) -> str:
    return min(
        (v.verdict for v in verdicts), key=ORDER.index, default="no-known-impact"
    )


def _code(text: str) -> str:
    return "`" + text.replace("`", "'") + "`"


def _target(finding: Finding) -> str:
    """``httpx.Client(proxies=)``: the symbol without private module segments, as users import it."""
    change = finding.change
    parts = change.symbol.split(".")
    public = [
        p
        for i, p in enumerate(parts)
        if i == 0 or not p.startswith("_") or p.startswith("__")
    ]
    name = ".".join(public)
    return _code(f"{name}({change.parameter}=)" if change.parameter else name)


def _advisories(
    checks: tuple[AdvisoryCheck, ...] | list[AdvisoryCheck], version: str
) -> str:
    check = next((c for c in checks if c.version == version), None)
    if check is None:
        return "not looked up"
    if check.status == "not-checked":
        return f"not checked ({check.detail})"
    active = [a for a in check.advisories if not a.withdrawn]
    if not active:
        return "no known advisories"
    shown = ", ".join(
        f"[{a.id}]({a.url})" + (f" (fixed in {a.fixed})" if a.fixed else "")
        for a in active[:3]
    )
    more = f" and {len(active) - 3} more" if len(active) > 3 else ""
    return f"{len(active)} known: {shown}{more}"


def _why(verdict: UpgradeVerdict) -> list[str]:
    """One line per upstream pull request behind the findings, with one checked quote each."""
    lines, seen = [], set()
    for decision in verdict.decisions:
        if not decision.pr_url or decision.pr_url in seen:
            continue
        seen.add(decision.pr_url)
        key = decision.change_key
        name = _code(
            f"{key.parameter}=" if key.parameter else key.symbol.split(".")[-1]
        )
        line = f"**Why:** {name} changed in [#{decision.pr_number} {decision.pr_title}]({decision.pr_url})"
        origin = decision.deprecation
        if origin and origin.pr_url and origin.pr_url != decision.pr_url:
            line += f", deprecated earlier in [#{origin.pr_number}]({origin.pr_url})"
        if decision.reversal:
            line += f". Later restored: {decision.reversal}"
        lines.append(line + ".")
        quote = next((q for q in decision.quotes if q.source_kind != "pr-title"), None)
        if quote:
            lines.append(f"> “{quote.text.strip()}” ([source]({quote.source_url}))")
        if len(seen) == 3:
            break
    return lines


def _listed(names: list[str], limit: int = 3) -> str:
    shown = ", ".join(_code(n) for n in names[:limit])
    return shown + (f" and {len(names) - limit} more" if len(names) > limit else "")


def traced(package: str, found: dict | None) -> list[str]:
    """From the workspace graph: where the package reaches the code, and what each broken line takes down."""
    if not found:
        return []
    lines: list[str] = []
    reach = found.get("reach") or {}
    if reach.get("uses"):
        files = reach.get("files") or []
        lines.append(
            f"**Where {_code(package)} reaches your code:** {reach['uses']} use(s) in "
            f"{len(files)} file(s): {_listed(files, 4)}."
        )
    through = reach.get("through") or []
    if through:
        chains = [
            " → ".join(_code(c.split("@")[0]) for c in t["chain"])
            + (
                f" ({t['uses']} use(s) of {_code(t['via'])} in your code)"
                if t.get("uses")
                else ""
            )
            for t in through[:3]
        ]
        lines.append(
            (
                "**Also pulled in through:** "
                if reach.get("uses")
                else "**Reaches you through:** "
            )
            + "; ".join(chains)
            + "."
        )
    hits = [
        b for b in found.get("blast") or [] if b.get("function") or b.get("importers")
    ]
    if hits:
        lines.append("**What else this breaks:**")
        for b in hits[:5]:
            bits = []
            if b.get("function"):
                bits.append(f"in {_code(b['function'] + '()')}")
            callers = [c["function"] + "()" for c in b.get("callers") or []]
            if callers:
                bits.append(f"called by {_listed(callers)}")
            entries = [
                e["name"]
                for e in b.get("entry_points") or []
                if e.get("name") != "script"
            ]
            if entries:
                bits.append(f"reached from {_listed(sorted(set(entries)))}")
            if b.get("importers"):
                bits.append(f"{len(b['importers'])} file(s) import it")
            if b.get("tests"):
                bits.append(f"tests: {_listed(b['tests'])}")
            where = _code(f"{b['file']}:{b['line']}")
            lines.append(f"- {where} " + ", ".join(bits) + ".")
        if len(hits) > 5:
            lines.append(f"- and {len(hits) - 5} more place(s)")
    return lines + [""] if lines else []


def section(verdict: UpgradeVerdict, found: dict | None = None) -> str:
    lines = [
        f"#### {verdict.label}: {_code(verdict.package)} {verdict.start} → {verdict.end}",
        "",
        verdict.reason[0].upper() + verdict.reason[1:] + ".",
        "",
    ]
    if verdict.findings:
        lines += [
            "| | Where in your code | What changed | Use instead |",
            "|---|---|---|---|",
        ]
        rows = 0
        for finding in verdict.findings:
            severity = "Breaks" if finding.severity == "breaks" else "Needs change"
            what = WHAT.get(finding.change.kind, finding.change.kind)
            if finding.guarded:
                what += " (your import has a fallback)"
            instead = (
                _code(finding.change.replacement) if finding.change.replacement else "—"
            )
            if finding.change.replacement_source == "message-unverified":
                instead += " (named upstream, not verified)"
            places = sorted({(loc.file, loc.line or 0) for loc in finding.locations})
            for file, line in places:
                if rows == MAX_ROWS:
                    break
                where = _code(f"{file}:{line}")
                lines.append(
                    f"| {severity} | {where} | {_target(finding)} {what} | {instead} |"
                )
                rows += 1
        total = sum(
            len({(loc.file, loc.line) for loc in f.locations}) for f in verdict.findings
        )
        if total > rows:
            lines.append(f"| | and {total - rows} more place(s) | | |")
        lines.append("")
        why = _why(verdict)
        if why:
            lines += why + [""]
        quoted = {
            (
                f.change.message_version
                or (verdict.end if f.change.kind == "deprecated" else verdict.start),
                f.change.message.strip(),
            )
            for f in verdict.findings
            if f.change.message
        }
        for version, message in sorted(quoted)[:3]:
            lines.append(f"> {verdict.package} {version} says: “{message}”")
        if quoted:
            lines.append("")
    lines += traced(verdict.package, found)
    if verdict.unchecked:
        reasons = sorted({u.reason for u in verdict.unchecked})
        first = verdict.unchecked[0]
        lines += [
            f"**Not checked:** {len(verdict.unchecked)} use(s) touching changed code could not be "
            f"followed statically ({', '.join(reasons)}), e.g. {_code(f'{first.location.file}:{first.location.line}')}: "
            f"{first.detail}.",
            "",
        ]
    facts = []
    if verdict.coverage and verdict.coverage.usages:
        c = verdict.coverage
        facts.append(f"Compared {c.checked} of {c.usages} use(s) in {c.files} file(s)")
    if verdict.advisories:
        facts.append(f"{verdict.end}: {_advisories(verdict.advisories, verdict.end)}")
        facts.append(
            f"{verdict.start}: {_advisories(verdict.advisories, verdict.start)}"
        )
    release = verdict.release
    if release and release.repository and release.start.tag and release.end.tag:
        facts.append(
            f"[upstream changes](https://github.com/{release.repository}/compare/"
            f"{release.start.tag}...{release.end.tag})"
        )
    if facts:
        lines += [" · ".join(facts), ""]
    return "\n".join(lines)


def added_section(name: str, version: str | None, checks: list[AdvisoryCheck]) -> str:
    if not version:
        return f"#### New dependency: {_code(name)}\n\nNo exact version is pinned or locked, so advisories were not looked up.\n"
    return f"#### New dependency: {_code(name)} {version}\n\nAdvisories: {_advisories(checks, version)}.\n"


def comment(
    verdicts: list[UpgradeVerdict],
    added: list[tuple[str, str | None, list[AdvisoryCheck]]],
    report_url: str | None,
    notes: list[str] = (),
    graph: dict[str, dict] | None = None,
    pull: str | None = None,
) -> str:
    """``graph`` holds what the workspace graph traced per package; ``pull`` is ``owner/repo#number``."""
    headline = LABELS[worst(verdicts)] if verdicts else "Dependencies changed"
    parts = [MARKER, f"### CodeIntent: {headline}", ""]
    for verdict in sorted(verdicts, key=lambda v: (ORDER.index(v.verdict), v.package)):
        parts.append(section(verdict, (graph or {}).get(verdict.package)))
    for name, version, checks in added:
        parts.append(added_section(name, version, checks))
    for note in notes:
        parts.append(f"_{note}_\n")
    if pull and any(v.findings or v.unchecked for v in verdicts):
        parts.append(
            f"**Fix it with your AI agent:** connect the CodeIntent MCP server and ask it to "
            f"_fix the CodeIntent findings on {pull}_. Its `fix_brief` tool hands over every edit, "
            "the code that depends on it and the tests to run; push the fix here and CodeIntent checks it again.\n"
        )
    footer = "Verdicts come from static analysis of both releases; CodeIntent never runs your code or the library, and never calls an upgrade safe."
    if report_url:
        footer = f"[Full report]({report_url}) · " + footer
    parts.append(f"<sub>{footer}</sub>")
    body = "\n".join(parts)
    return (
        body
        if len(body) <= MAX_BODY
        else body[: MAX_BODY - 200] + "\n\n_Report truncated; see the full report._"
    )


def check_output(verdicts: list[UpgradeVerdict], body: str) -> dict:
    overall = worst(verdicts)
    names = ", ".join(f"{v.package} {v.start} → {v.end}" for v in verdicts[:3])
    title = f"{LABELS[overall]}: {names}" if verdicts else "No upgrades to compare"
    return {
        "conclusion": CONCLUSIONS[overall],
        "output": {"title": title[:250], "summary": body[:MAX_BODY]},
    }
