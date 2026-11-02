import pytest

from codeintent.domain import (
    Answer,
    AnswerDraft,
    bind_spans,
    scoped_id,
    source_spans,
    validate_citations,
)


def test_model_selects_passages_without_rewriting_original_text():
    body = "We kept the existing API.\r\nA replacement would break downstream clients."
    docs = [{"id": "source-a", "body": body}]
    spans = source_spans(docs)
    ref = next(key for key, value in spans.items() if "downstream" in value["quote"])
    draft = AnswerDraft.model_validate(
        {
            "title": "Compatibility",
            "status": "supported",
            "claims": [
                {
                    "text": "The replacement affected downstream clients.",
                    "support": "direct",
                    "citations": [{"span_id": ref}],
                }
            ],
            "unknowns": [],
            "temporal_note": "Historical record",
        }
    )
    result = bind_spans(draft, spans)
    validate_citations(result, docs)
    citation = result.claims[0].citations[0]
    assert body[citation.start : citation.end] == citation.quote


def test_fabricated_passage_is_rejected():
    draft = AnswerDraft.model_validate(
        {
            "title": "Unknown",
            "status": "supported",
            "claims": [
                {
                    "text": "The model invented evidence",
                    "support": "direct",
                    "citations": [{"span_id": "invented"}],
                }
            ],
            "unknowns": [],
            "temporal_note": "",
        }
    )
    with pytest.raises(KeyError):
        bind_spans(draft, {})


def test_citation_from_another_bundle_is_rejected():
    answer = Answer.model_validate(
        {
            "title": "Test",
            "status": "supported",
            "claims": [
                {
                    "text": "This citation does not belong here.",
                    "support": "direct",
                    "citations": [
                        {"source_id": "other-index", "quote": "external source"}
                    ],
                }
            ],
            "unknowns": [],
            "temporal_note": "",
        }
    )
    with pytest.raises(ValueError, match="outside"):
        validate_citations(answer, [{"id": "this-index", "body": "external source"}])


def test_modified_quote_and_offsets_are_rejected():
    base = {
        "title": "Test",
        "status": "supported",
        "claims": [
            {
                "text": "A supported claim",
                "support": "direct",
                "citations": [
                    {"source_id": "s", "quote": "real passage", "start": 1, "end": 13}
                ],
            }
        ],
        "unknowns": [],
        "temporal_note": "",
    }
    with pytest.raises(ValueError, match="offsets"):
        validate_citations(
            Answer.model_validate(base), [{"id": "s", "body": "real passage"}]
        )
    base["claims"][0]["citations"][0] = {"source_id": "s", "quote": "invented quote"}
    with pytest.raises(ValueError, match="snapshot"):
        validate_citations(
            Answer.model_validate(base), [{"id": "s", "body": "real passage"}]
        )


def test_partial_status_requires_a_concrete_gap():
    answer = Answer(
        title="Partial", status="partial", claims=[], unknowns=[], temporal_note=""
    )
    with pytest.raises(ValueError, match="unanswered"):
        validate_citations(answer, [])


def test_identity_separates_repository_revision_and_path():
    ids = {
        scoped_id(1, "revision-a", "function", "client.py:send"),
        scoped_id(2, "revision-a", "function", "client.py:send"),
        scoped_id(1, "revision-b", "function", "client.py:send"),
        scoped_id(1, "revision-a", "function", "other.py:send"),
    }
    assert len(ids) == 4


def test_source_provenance_changes_index_identity():
    from codeintent.graph import index_id

    base = {
        "repository_id": 1,
        "revision": "a" * 40,
        "documents": [
            {"id": "one", "sha256": "a" * 64, "body": "same", "author": "one"}
        ],
        "links": [],
        "coverage": {"scope": "test"},
    }
    changed = {**base, "documents": [{**base["documents"][0], "author": "two"}]}
    assert index_id(base) != index_id(changed)


def test_questions_cannot_become_lucene_syntax():
    from codeintent.investigate import lexical_query

    assert (
        lexical_query("app=(value) +foo:bar -baz")
        == '"app" OR "value" OR "foo" OR "bar" OR "baz"'
    )
    assert lexical_query("????????") == '"evidence"'


def test_invalid_model_reference_gets_one_bounded_repair(monkeypatch):
    import json
    from contextlib import contextmanager
    from types import SimpleNamespace

    from codeintent.investigate import generate_answer

    calls = []
    valid = {
        "title": "A recorded decision",
        "status": "supported",
        "claims": [
            {
                "text": "The API changed for compatibility",
                "support": "direct",
                "citations": [{"span_id": "source:0"}],
            }
        ],
        "unknowns": [],
        "temporal_note": "Historical evidence",
    }
    invalid = {
        **valid,
        "claims": [
            {
                "text": "The API changed for compatibility",
                "support": "direct",
                "citations": [{"span_id": "invented"}],
            }
        ],
    }

    class Models:
        def generate_content(self, **kwargs):
            calls.append(kwargs)
            return SimpleNamespace(
                text=json.dumps(invalid if len(calls) == 1 else valid)
            )

    @contextmanager
    def fake_client():
        yield SimpleNamespace(models=Models())

    monkeypatch.setattr("codeintent.investigate.client", fake_client)
    sources = [{"id": "source", "body": "Changed for compatibility"}]
    spans = {
        "source:0": {
            "source_id": "source",
            "quote": "Changed for compatibility",
            "start": 0,
            "end": 25,
        }
    }
    answer = generate_answer("Use evidence only", "{}", spans, sources)
    assert len(calls) == 2
    assert answer.claims[0].citations[0].source_id == "source"
