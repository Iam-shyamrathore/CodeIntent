"""The pull request review: three agents run after CodeIntent's deterministic check of a dependency PR.

- **patcher**: drafts the edit for each break. CodeIntent then applies the edits to a copy of the
  repository, checks that it still parses and runs its own analysis again; only an edit that removes the
  break is marked checked (after Agentless: localise, repair, then validate).
- **investigator**: follows the uses static analysis could not, with the code and graph tools.
- **behaviour**: reads the release notes between the two versions for behaviour changes that touch names
  this repository uses.

Their answers are stored in ``ci_agent_reviews`` beside the check, added to the PR comment in a section of
their own, and handed to coding agents through ``fix_brief``. They never change a verdict.
"""

from __future__ import annotations

import ast
import logging
import re
import shutil
import tempfile
from functools import partial
from pathlib import Path
from typing import Literal

from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from codeintent import runs, store
from codeintent.agent import harness
from codeintent.agent.tools import Session, toolbox
from codeintent.upgrades.manifests import files
from codeintent.upgrades.upstream import verified

logger = logging.getLogger(__name__)

MAX_UPGRADES = 5
MAX_UNCHECKED = 6
START = "<!-- codeintent:agent -->"
END = "<!-- /codeintent:agent -->"


# --- Answers ---------------------------------------------------------------------------------------


class Patch(BaseModel):
    file: str
    line: int = Field(description="The line CodeIntent reported.")
    before: str = Field(
        description="Whole lines copied exactly from the file, indentation included."
    )
    after: str = Field(description="What replaces them.")
    explanation: str = Field(description="One or two sentences: what changes and why.")


class Patches(BaseModel):
    patches: list[Patch]
    skipped: list[str] = Field(
        default=[], description="Places left out, each with why."
    )


class Evidence(BaseModel):
    file: str
    line: int
    quote: str = Field(
        description="Copied exactly from that line or the lines around it."
    )


class Assessment(BaseModel):
    file: str
    line: int
    assessment: Literal["likely-breaks", "likely-fine", "unclear"]
    reason: str
    evidence: list[Evidence] = []
    check: str = Field(
        default="", description="What a person should check, when unclear."
    )


class Assessments(BaseModel):
    items: list[Assessment]


class Change(BaseModel):
    symbol: str = Field(
        description="The name this repository uses, as uses_of shows it."
    )
    version: str
    what_changed: str
    why_it_matters: str
    quote: str = Field(description="The release note sentence, copied exactly.")
    severity: Literal["likely-breaks", "review"]


class Behaviour(BaseModel):
    items: list[Change]


# --- Checks: what makes an answer acceptable ------------------------------------------------------


def _text(root: Path, file: str) -> str | None:
    try:
        return files.read(root, files.confined(root, root / file))
    except (files.Unreadable, OSError):
        return None


def _near(text: str, quote: str, line: int, window: int) -> bool:
    lines = text.splitlines()
    low, high = max(0, line - 1 - window), min(len(lines), line + window)
    return verified(quote, "\n".join(lines[low:high]))


NUMBERED = re.compile(r"^\s*\d+  ")


def _lines(text: str) -> list[str]:
    """Lines of an agent's snippet, without the read_file line numbers if it copied them."""
    lines = text.strip("\n").splitlines()
    if lines and all(NUMBERED.match(ln) or not ln.strip() for ln in lines):
        lines = [NUMBERED.sub("", ln, count=1) for ln in lines]
    return lines


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip())


def apply(text: str, patch: Patch) -> str | None:
    """``text`` with ``patch.before`` replaced near its line, or None if it is not there.

    Lines must match exactly or, failing that, apart from indentation; then ``after`` is shifted by the
    same amount, so a snippet copied without its leading spaces still lands correctly.
    """
    lines = text.splitlines(keepends=True)
    want, after = _lines(patch.before), _lines(patch.after)
    if not want:
        return None
    order = sorted(range(len(lines)), key=lambda i: abs(i + 1 - patch.line))
    for exact in (True, False):
        for start in order:
            if abs(start + 1 - patch.line) > 15:
                break
            chunk = [ln.rstrip("\r\n") for ln in lines[start : start + len(want)]]
            if len(chunk) < len(want):
                continue
            if exact:
                same = chunk == want
            else:
                same = [c.strip() for c in chunk] == [w.strip() for w in want]
            if not same:
                continue
            shift = _indent(chunk[0]) - _indent(want[0]) if not exact else 0
            if shift > 0:
                after = [(" " * shift + a) if a.strip() else a for a in after]
            elif shift < 0:
                after = [a[min(-shift, _indent(a)) :] for a in after]
            ending = "\n" if lines[start + len(want) - 1].endswith("\n") else ""
            return (
                "".join(lines[:start])
                + "\n".join(after)
                + ending
                + "".join(lines[start + len(want) :])
            )
    return None


def _as_applied(root: Path, patch: Patch) -> dict:
    """``before`` and ``after`` as they are in the file, with its own indentation."""
    text = _text(root, patch.file)
    patched = apply(text, patch) if text is not None else None
    if patched is None:
        return {}
    old, new = text.splitlines(), patched.splitlines()
    head = 0
    while head < min(len(old), len(new)) and old[head] == new[head]:
        head += 1
    tail = 0
    while tail < min(len(old), len(new)) - head and old[-1 - tail] == new[-1 - tail]:
        tail += 1
    return {
        "before": "\n".join(old[head : len(old) - tail]),
        "after": "\n".join(new[head : len(new) - tail]),
    }


def _around(text: str, line: int) -> str:
    rows = text.splitlines()
    low, high = max(1, line - 3), min(len(rows), line + 4)
    return "\n".join(f"{n:>5}  {rows[n - 1]}" for n in range(low, high + 1))


def check_patches(root: Path, places: set[tuple[str, int]]):
    def check(answer: Patches) -> list[str]:
        problems = []
        for p in answer.patches:
            if not any(f == p.file and abs(ln - p.line) <= 3 for f, ln in places):
                problems.append(
                    f"{p.file}:{p.line} is not one of the places CodeIntent reported"
                )
                continue
            text = _text(root, p.file)
            patched = apply(text, p) if text is not None else None
            if patched is None:
                problems.append(
                    f"`before` for {p.file}:{p.line} is not in the file near that line. Copy whole "
                    "lines (without the line numbers) from what is there:\n"
                    + (
                        _around(text, p.line)
                        if text is not None
                        else "(file not found)"
                    )
                )
                continue
            if p.before.strip() == p.after.strip():
                problems.append(f"the edit for {p.file}:{p.line} changes nothing")
            elif p.file.endswith(".py"):
                try:
                    ast.parse(patched)
                except SyntaxError as error:
                    problems.append(
                        f"the edit for {p.file}:{p.line} does not parse: {error.msg}"
                    )
        return problems

    return check


def check_assessments(root: Path, asked: set[tuple[str, int]]):
    def check(answer: Assessments) -> list[str]:
        problems = []
        for item in answer.items:
            if (item.file, item.line) not in asked:
                problems.append(
                    f"{item.file}:{item.line} is not one of the uses you were asked about"
                )
            for e in item.evidence:
                text = _text(root, e.file)
                if text is None or not _near(text, e.quote, e.line, 3):
                    problems.append(
                        f"the quote for {e.file}:{e.line} is not in that file near that line"
                    )
            if item.assessment != "unclear" and not item.evidence:
                problems.append(
                    f"{item.file}:{item.line}: '{item.assessment}' needs quoted evidence"
                )
        return problems

    return check


def check_behaviour(session: Session, used: set[str]):
    def check(answer: Behaviour) -> list[str]:
        problems = []
        for item in answer.items:
            if not any(verified(item.quote, seen) for seen in session.seen):
                problems.append(
                    f"the quote for {item.symbol} is not in the release notes you read"
                )
            if not any(
                item.symbol == u
                or u.startswith(item.symbol + ".")
                or item.symbol.startswith(u + ".")
                for u in used
            ):
                problems.append(
                    f"{item.symbol} is not a name this repository uses (see uses_of)"
                )
        return problems

    return check


# --- What the patcher is told about the new release ----------------------------------------------


def describe(package: str, version: str, symbols: list[str], http) -> str:
    """Each symbol's call signature in ``version`` (parameters, annotations, defaults), read statically,
    with the definitions of type aliases its annotations name, so a replacement gets the right type."""
    import griffe

    from codeintent.upgrades import artifacts
    from codeintent.upgrades.surface import Found, Surface, signature

    try:
        surface = Surface.fetch(package, version, http)
    except artifacts.ArtifactError:
        return ""
    out, aliases = [], {}
    for symbol in dict.fromkeys(symbols):
        found = surface.lookup(symbol)
        if not isinstance(found, Found) or found.obj is None:
            continue
        sig = signature(found.obj)
        if sig is None:
            continue
        params = []
        for param in sig.owner.parameters:
            if param.name in ("self", "cls"):
                continue
            text = {
                griffe.ParameterKind.var_positional: f"*{param.name}",
                griffe.ParameterKind.var_keyword: f"**{param.name}",
            }.get(param.kind, param.name)
            if param.annotation is not None:
                text += f": {param.annotation}"
                if isinstance(param.annotation, griffe.Expr):
                    for part in param.annotation.iterate(flat=True):
                        path = getattr(part, "canonical_path", None)
                        if (
                            isinstance(path, str)
                            and path.startswith(package)
                            and path not in aliases
                        ):
                            obj = getattr(surface.lookup(path), "obj", None)
                            if (
                                obj is not None
                                and obj.is_attribute
                                and obj.value is not None
                            ):
                                aliases[path] = str(obj.value)[:300]
            if param.default is not None:
                text += f" = {param.default}"
            params.append(text)
        out.append(f"{symbol}({', '.join(params)})")
    if aliases:
        out.append("Type aliases used above:")
        out += [f"{name} = {value}" for name, value in list(aliases.items())[:12]]
    return "\n".join(out)


# --- CodeIntent checks the patcher's work ---------------------------------------------------------


def recheck(
    package: str, start: str, end: str, root: Path, patches: list[Patch]
) -> list[bool]:
    """Whether each edit removes its break: apply them all to a copy and run the analysis again.

    An edit counts only if it was applied (its ``before`` text was still there) and no break remains
    around it."""
    import httpx

    from codeintent.upgrades.verdict import evaluate

    with tempfile.TemporaryDirectory() as scratch:
        copy = Path(scratch) / "repo"
        shutil.copytree(root, copy, symlinks=True)
        applied = []
        for p in patches:
            target = copy / p.file
            patched = apply(target.read_text(encoding="utf-8", errors="replace"), p)
            if patched is not None:
                target.write_text(patched, encoding="utf-8")
            applied.append(patched is not None)
        with httpx.Client(timeout=60, follow_redirects=True) as pypi:
            after = evaluate(
                package,
                start,
                end,
                copy,
                pypi,
                release=False,
                advisory=False,
                upstream=False,
            )
    remaining = {
        (loc.file, loc.line or 0) for f in after.findings for loc in f.locations
    }
    out = []
    for p, done in zip(patches, applied, strict=True):
        span = len(p.after.strip("\n").splitlines()) + 3
        out.append(
            done
            and not any(
                f == p.file and p.line - 3 <= ln <= p.line + span for f, ln in remaining
            )
        )
    return out


# --- Rendering: the agent section of the PR comment -----------------------------------------------

LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
URL = re.compile(r"https?://\S+")


def plain(text: str, limit: int = 400) -> str:
    """Agent prose for a comment: no links, images or HTML (nothing an attacker could plant), clipped."""
    text = LINK.sub(r"\1", text or "")
    text = URL.sub("(link removed)", text)
    text = text.replace("<", "\u2039").replace(">", "\u203a").replace("`", "'")
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _fence(text: str) -> str:
    return text.replace("```", "'''")


def section(review: dict, model: str) -> str:
    lines = [START, f"#### Agent review ({model}; not part of the verdict)", ""]
    for upgrade in review.get("upgrades") or []:
        name = upgrade["package"]
        for p in upgrade.get("patches") or []:
            status = (
                "CodeIntent re-analysed the edited code and no longer finds this break; review it"
                if p.get("verified")
                else "CodeIntent still finds the break with this edit; review it"
            )
            lines += [
                f"**Suggested fix for `{p['file']}:{p['line']}`** ({status})",
                "",
                "```diff",
                *[f"- {_fence(ln)}" for ln in p["before"].strip("\n").splitlines()],
                *[f"+ {_fence(ln)}" for ln in p["after"].strip("\n").splitlines()],
                "```",
                plain(p["explanation"]),
                "",
            ]
        for a in upgrade.get("assessments") or []:
            label = {
                "likely-breaks": "likely breaks",
                "likely-fine": "likely fine",
                "unclear": "unclear",
            }[a["assessment"]]
            lines.append(
                f"**`{a['file']}:{a['line']}`** ({name}, could not be followed statically): "
                f"{label}. {plain(a['reason'])}"
                + (f" Check: {plain(a['check'], 200)}" if a.get("check") else "")
            )
            lines.append("")
        changes = upgrade.get("behaviour") or []
        if changes:
            lines += [
                f"**Behaviour changes in {name}'s release notes that touch code you use:**",
                "",
            ]
            for c in changes[:6]:
                tag = "likely breaks" if c["severity"] == "likely-breaks" else "review"
                lines.append(
                    f"- `{plain(c['symbol'], 120)}` ({tag}, {plain(c['version'], 30)}): "
                    f"{plain(c['what_changed'], 240)} {plain(c['why_it_matters'], 240)}"
                )
                lines.append(f"  > “{plain(c['quote'], 300)}”")
            lines.append("")
    if len(lines) == 3:
        return ""
    lines += [
        (
            "<sub>Drafted by an agent from the code, the workspace graph and the release notes. Quotes are "
            "checked against their source; suggested fixes are applied to a copy and re-analysed by "
            "CodeIntent.</sub>"
        ),
        END,
    ]
    return "\n".join(lines)


def merged(body: str, block: str) -> str:
    """The PR comment with the agent section replaced or inserted before the agent hint and footer."""
    if START in body and END in body:
        head, rest = body.split(START, 1)
        body = head.rstrip("\n") + "\n\n" + rest.split(END, 1)[1].lstrip("\n")
    if not block:
        return body
    for anchor in ("**Fix it with your AI agent:**", "<sub>"):
        at = body.rfind(anchor)
        if at != -1:
            return body[:at] + block + "\n\n" + body[at:]
    return body + "\n\n" + block


# --- The review ------------------------------------------------------------------------------------


def _task(header: dict, body: str) -> str:
    facts = "\n".join(f"{k}: {v}" for k, v in header.items())
    return f"{facts}\n\n{body}"


def _attempt(run, name: str, fn):
    """One agent as a step; a failure is recorded and the others still run."""
    try:
        with run.step(name) as note:
            out, detail = fn()
            note["detail"] = detail
            return out
    except Exception as error:
        logger.warning("Agent step %r failed (%s)", name, type(error).__name__)
        run.failed_step = None
        return None


def review(run_id: str) -> dict | None:
    """Review one finished pull request check; returns the stored review, or None if there is nothing to do."""
    import httpx

    from codeintent import github_app as gh
    from codeintent.upgrades import repository
    from codeintent.upgrades.verdict import UpgradeVerdict

    with store.connection() as conn:
        check = conn.execute(
            """SELECT id,installation_id,repository,ref,subject,result,analysis_id FROM ci_runs
            WHERE id=%s AND kind='pull' AND status IN ('succeeded','partial')""",
            (run_id,),
        ).fetchone()
    if not check or not harness.configured():
        return None
    result = check["result"] or {}
    raw = [
        v
        for v in result.get("verdicts") or []
        if v.get("verdict") != "not-checked" or v.get("unchecked")
    ]
    if not raw:
        return None
    ws, repo, head = check["installation_id"], check["repository"], check["ref"]
    number = int(str(check["subject"]).lstrip("#"))
    client = gh.Client.for_installation(ws)
    upgrades, traces = [], []
    try:
        with (
            runs.recorded(
                "agent",
                installation_id=ws,
                repository=repo,
                ref=head,
                subject=f"review #{number}",
                analysis_id=check["analysis_id"],
                input={"check": str(run_id)},
            ) as run,
            httpx.Client(timeout=60, follow_redirects=True) as http,
            repository.using(client.token),
            repository.temporary() as folder,
        ):
            with run.step("download the repository"):
                root = repository.download(repo, head, Path(folder), client.token())
            for data in raw[:MAX_UPGRADES]:
                fields = (
                    "package",
                    "start",
                    "end",
                    "verdict",
                    "label",
                    "reason",
                    "findings",
                    "unchecked",
                    "release",
                )
                verdict = UpgradeVerdict.model_validate(
                    {k: data[k] for k in fields if k in data}
                )
                upgrade = {
                    "package": verdict.package,
                    "start": verdict.start,
                    "end": verdict.end,
                }
                header = {
                    "Repository": repo,
                    "Package": verdict.package,
                    "Upgrade": f"{verdict.start} → {verdict.end}",
                    "CodeIntent's verdict": f"{verdict.label}: {verdict.reason}",
                }
                if verdict.findings:
                    upgrade["patches"] = _attempt(
                        run,
                        f"draft fixes for {verdict.package}",
                        partial(_patch, verdict, header, root, ws, repo, traces),
                    )
                if verdict.unchecked:
                    upgrade["assessments"] = _attempt(
                        run,
                        f"follow uses of {verdict.package} CodeIntent could not",
                        partial(_investigate, verdict, header, root, ws, repo, traces),
                    )
                source = verdict.release.repository if verdict.release else None
                if source:
                    from codeintent.workspace_graph import public

                    used = {
                        u["symbol"]
                        for u in (result.get("usages") or {}).get(verdict.package, [])
                    }
                    used |= {public(u) for u in used}
                    upgrade["behaviour"] = _attempt(
                        run,
                        f"read {verdict.package} release notes",
                        partial(
                            _behaviour,
                            verdict,
                            header,
                            source,
                            used,
                            ws,
                            repo,
                            http,
                            traces,
                        ),
                    )
                upgrades.append(upgrade)
            stored = {"upgrades": upgrades}
            model = next(
                (t["model"] for t in traces if t.get("model")), harness.models()[0]
            )
            with store.connection() as conn:
                conn.execute(
                    """INSERT INTO ci_agent_reviews(run_id,installation_id,repository,pull_number,model,result,trace)
                    VALUES(%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(run_id) DO UPDATE
                    SET model=EXCLUDED.model,result=EXCLUDED.result,trace=EXCLUDED.trace,created_at=now()""",
                    (
                        run_id,
                        ws,
                        repo,
                        number,
                        model,
                        Jsonb(stored),
                        Jsonb({"agents": traces, "run": run.id}),
                    ),
                )
            block = section(stored, model)
            if block:
                with run.step("add the review to the comment"):
                    _comment(client, repo, number, block)
            counts = {
                "patches": sum(len(u.get("patches") or []) for u in upgrades),
                "checked_patches": sum(
                    1
                    for u in upgrades
                    for p in u.get("patches") or []
                    if p.get("verified")
                ),
                "assessments": sum(len(u.get("assessments") or []) for u in upgrades),
                "behaviour": sum(len(u.get("behaviour") or []) for u in upgrades),
                "tokens": sum(t.get("tokens") or 0 for t in traces),
            }
            run.finish(summary=counts, result={"review": stored, "agents": traces})
            return stored
    finally:
        client.close()


def run_isolated(run_id: str) -> None:
    """``review`` in a fresh process, so library releases loaded for the re-check are freed after it."""
    import multiprocessing
    from concurrent.futures import ProcessPoolExecutor

    with ProcessPoolExecutor(
        max_workers=1, mp_context=multiprocessing.get_context("spawn")
    ) as pool:
        pool.submit(_child, run_id).result()


def _child(run_id: str) -> None:
    try:
        review(run_id)
    except Exception as exc:
        raise RuntimeError(type(exc).__name__) from None


def _comment(client, repo: str, number: int, block: str) -> None:
    from codeintent import github_app as gh

    with store.connection() as conn:
        row = conn.execute(
            "SELECT comment_id FROM ci_pull_analyses WHERE repository=%s AND number=%s AND comment_id IS NOT NULL ORDER BY updated_at DESC LIMIT 1",
            (repo, number),
        ).fetchone()
    if not row:
        return
    current = client.json(f"/repos/{repo}/issues/comments/{row['comment_id']}")
    gh.upsert_comment(
        client,
        repo,
        number,
        merged(current.get("body") or "", block),
        row["comment_id"],
    )


def _places(verdict) -> list[tuple[str, int]]:
    return list(
        dict.fromkeys(
            (ln.file, ln.line or 0) for f in verdict.findings for ln in f.locations
        )
    )


def _patch(verdict, header, root, ws, repo, traces):
    places = _places(verdict)
    listed = "\n".join(
        f"- {loc.file}:{loc.line}: {f.change.symbol}"
        + (f"({f.change.parameter}=)" if f.change.parameter else "")
        + f" {f.change.kind}: {f.change.detail}"
        + (f" Use instead: {f.change.replacement}." if f.change.replacement else "")
        + (
            f' The library says: "{f.change.message.strip()}"'
            if f.change.message
            else ""
        )
        for f in verdict.findings
        for loc in dict.fromkeys(f.locations)
    )
    import httpx

    with httpx.Client(timeout=60, follow_redirects=True) as http:
        signatures = describe(
            verdict.package,
            verdict.end,
            [f.change.symbol for f in verdict.findings],
            http,
        )
    session = Session(root=root, ws=ws, repo=repo)
    answer, trace = harness.run(
        "patcher",
        _task(
            header,
            f"Places CodeIntent found:\n{listed}\n\n"
            + (
                f"Signatures in {verdict.package} {verdict.end}, read from the release:\n"
                f"{signatures}\n\n"
                if signatures
                else ""
            )
            + "Draft the edit for each place.",
        ),
        tools=toolbox(session, "code", "graph"),
        answer=Patches,
        role="patcher",
        check=check_patches(root, set(places)),
    )
    traces.append(trace.as_dict())
    if answer is None:
        return [], f"no accepted answer ({trace.outcome})"
    ok = (
        recheck(verdict.package, verdict.start, verdict.end, root, answer.patches)
        if answer.patches
        else []
    )
    patches = [
        {**p.model_dump(), **_as_applied(root, p), "verified": good}
        for p, good in zip(answer.patches, ok, strict=True)
    ]
    return (
        patches,
        f"{len(patches)} edit(s), {sum(ok)} no longer break in CodeIntent's re-analysis, {len(answer.skipped)} left out",
    )


def _investigate(verdict, header, root, ws, repo, traces):
    items = verdict.unchecked[:MAX_UNCHECKED]
    asked = {(u.location.file, u.location.line or 0) for u in items}
    listed = "\n".join(
        f"- {u.location.file}:{u.location.line}: {u.reason}: {u.detail}"
        + (f" (symbol {u.symbol})" if u.symbol else "")
        for u in items
    )
    session = Session(root=root, ws=ws, repo=repo)
    answer, trace = harness.run(
        "investigator",
        _task(
            header, f"Uses CodeIntent could not follow:\n{listed}\n\nAssess each one."
        ),
        tools=toolbox(session, "code", "graph"),
        answer=Assessments,
        role="investigator",
        check=check_assessments(root, asked),
    )
    traces.append(trace.as_dict())
    if answer is None:
        return [], f"no accepted answer ({trace.outcome})"
    found = [a.model_dump() for a in answer.items]
    return found, ", ".join(
        f"{a['file']}:{a['line']} {a['assessment']}" for a in found
    ) or "none"


def _behaviour(verdict, header, source, used, ws, repo, http, traces):
    session = Session(ws=ws, repo=repo, http=http)
    answer, trace = harness.run(
        "behaviour",
        _task(
            {**header, "Library repository": source},
            "Find behaviour changes between the two versions that touch names this repository uses.",
        ),
        tools=toolbox(session, "upstream", "graph"),
        answer=Behaviour,
        role="behaviour",
        check=check_behaviour(session, used),
        budget=8,
    )
    traces.append(trace.as_dict())
    if answer is None:
        return [], f"no accepted answer ({trace.outcome})"
    found = [c.model_dump() for c in answer.items]
    return found, f"{len(found)} change(s) touching code you use"
