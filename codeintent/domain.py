from __future__ import annotations

import hashlib
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class Citation(BaseModel):
    source_id: str
    quote: str = Field(min_length=4, max_length=600)
    start: int | None = None
    end: int | None = None


class Claim(BaseModel):
    text: str = Field(min_length=5, max_length=1200)
    support: Literal["direct", "inferred"]
    citations: list[Citation] = Field(min_length=1, max_length=5)


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str
    status: Literal["supported", "partial", "insufficient", "conflicting"]
    claims: list[Claim] = Field(max_length=8)
    unknowns: list[str]
    temporal_note: str


class SpanReference(BaseModel):
    span_id: str


class DraftClaim(BaseModel):
    text: str
    support: Literal["direct", "inferred"]
    citations: list[SpanReference] = Field(min_length=1, max_length=5)


class AnswerDraft(Answer):
    claims: list[DraftClaim] = Field(max_length=8)


def source_spans(sources: list[dict]) -> dict[str, dict]:
    """Create short, exact, addressable passages before generation."""
    spans = {}
    for source in sources:
        text = source["body"][:16000]
        parts = list(re.finditer(r"[^\r\n]+", text))
        number = 0
        for part in parts:
            words = list(re.finditer(r"\S+", part.group()))
            for offset in range(0, len(words), 24):
                group = words[offset : offset + 24]
                if len(group) < 6 and offset > 0:
                    group = words[-24:]
                start, end = (
                    part.start() + group[0].start(),
                    part.start() + group[-1].end(),
                )
                if end - start < 4 or end - start > 600:
                    continue
                span_id = f"{source['id']}:{number}"
                spans[span_id] = {
                    "source_id": source["id"],
                    "quote": text[start:end],
                    "start": start,
                    "end": end,
                }
                number += 1
    return spans


def bind_spans(draft: AnswerDraft, spans: dict[str, dict]) -> Answer:
    data = draft.model_dump()
    for claim in data["claims"]:
        claim["citations"] = [spans[ref["span_id"]] for ref in claim["citations"]]
    return Answer.model_validate(data)


def scoped_id(repository_id: int, revision: str, kind: str, identity: str) -> str:
    return hashlib.sha256(
        f"{repository_id}\0{revision}\0{kind}\0{identity}".encode()
    ).hexdigest()


def validate_citations(answer: Answer, sources: list[dict]) -> None:
    """Deterministic source membership/quotation checks, not semantic proof."""
    by_id = {s["id"]: s for s in sources}
    if answer.status == "insufficient" and answer.claims:
        raise ValueError("Insufficient answers cannot contain asserted claims")
    if answer.status == "supported" and not answer.claims:
        raise ValueError("A supported answer needs at least one cited claim")
    if answer.status == "partial" and not answer.unknowns:
        raise ValueError("A partial answer must identify the unanswered aspect")
    for claim in answer.claims:
        for citation in claim.citations:
            if citation.source_id not in by_id:
                raise ValueError("Citation is outside the retrieved source bundle")
            if citation.quote not in by_id[citation.source_id]["body"]:
                raise ValueError("Citation quote does not match the source snapshot")
            if (
                citation.start is not None
                and by_id[citation.source_id]["body"][citation.start : citation.end]
                != citation.quote
            ):
                raise ValueError("Citation offsets do not match the source snapshot")
