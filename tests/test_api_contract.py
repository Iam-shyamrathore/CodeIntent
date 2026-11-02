import pytest
from fastapi.testclient import TestClient

from codeintent.api import app


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("CODEINTENT_ENV", "test")
    monkeypatch.setenv("CODEINTENT_API_SECRET", "test-service-secret")
    monkeypatch.setenv("CODEINTENT_OPERATOR_TOKEN", "test-operator-secret")
    # Test auth/validation without opening database connections.
    return TestClient(app, headers={"X-Api-Key": "test-service-secret"})


def test_health_has_no_secrets(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": "1.0.0"}


def test_service_requires_authentication(client):
    response = client.get("/repositories", headers={"X-Api-Key": "wrong"})
    assert response.status_code == 401


def test_import_requires_operator(client):
    response = client.post("/imports", json={"repository": "encode/httpx"})
    assert response.status_code == 403


def test_bad_repository_is_rejected_before_queue_submission(client):
    response = client.post(
        "/imports",
        headers={"X-Operator-Key": "test-operator-secret"},
        json={"repository": "https://127.0.0.1/private"},
    )
    assert response.status_code == 422


def test_blank_question_is_rejected(client):
    assert client.post("/investigate", json={"question": " " * 20}).status_code == 422


def test_invalid_scope_is_rejected(client):
    assert (
        client.post(
            "/investigate",
            json={"question": "Why did this change?", "index_id": "../../other"},
        ).status_code
        == 422
    )


def test_missing_index_does_not_call_model(client, monkeypatch):
    monkeypatch.setattr("codeintent.store.get_index", lambda *args: None)
    assert (
        client.post(
            "/investigate", json={"question": "Why did this change?"}
        ).status_code
        == 409
    )


def test_cached_answer_does_not_spend_model_quota(client, monkeypatch):
    monkeypatch.setattr("codeintent.store.get_index", lambda *args: {"id": "a" * 24})
    monkeypatch.setattr(
        "codeintent.store.get_cached",
        lambda *args: {"report_id": "existing", "answer": {"status": "supported"}},
    )
    monkeypatch.setattr(
        "codeintent.store.consume_quota",
        lambda *args: pytest.fail("cache must not use quota"),
    )
    response = client.post("/investigate", json={"question": "Why did this change?"})
    assert response.json()["cached"] is True


def test_cloud_question_returns_job_without_waiting_for_model(client, monkeypatch):
    monkeypatch.setenv("CODEINTENT_ASYNC_QUESTIONS", "1")
    monkeypatch.setattr("codeintent.store.get_index", lambda *args: {"id": "a" * 24})
    monkeypatch.setattr("codeintent.store.get_cached", lambda *args: None)
    monkeypatch.setattr(
        "codeintent.questions.submit",
        lambda *args: {"job_id": "durable", "status": "queued"},
    )
    response = client.post("/investigate", json={"question": "Why did this change?"})
    assert response.status_code == 202
    assert response.json()["job_id"] == "durable"
