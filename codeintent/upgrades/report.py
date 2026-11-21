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


def section(verdict: UpgradeVerdict) -> str:
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
) -> str:
    headline = LABELS[worst(verdicts)] if verdicts else "Dependencies changed"
    parts = [MARKER, f"### CodeIntent: {headline}", ""]
    for verdict in sorted(verdicts, key=lambda v: (ORDER.index(v.verdict), v.package)):
        parts.append(section(verdict))
    for name, version, checks in added:
        parts.append(added_section(name, version, checks))
    for note in notes:
        parts.append(f"_{note}_\n")
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
