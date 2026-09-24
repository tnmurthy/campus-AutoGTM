import json

import jwt
import pytest

from app.config import get_settings
from app.services import crm_client
from app.services.crm_client import CrmError

SECRET = "test-jwt-secret"


class StubResponse:
    def __init__(self, status_code, body=None, text="", raises=False):
        self.status_code = status_code
        self._body = body
        self.text = text
        self._raises = raises

    def json(self):
        if self._raises:
            raise ValueError("not json")
        return self._body


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co/")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", SECRET)
    get_settings.cache_clear()
    monkeypatch.setattr(crm_client.time, "sleep", lambda _: None)


def capture(monkeypatch, response):
    sent = {}

    def fake_post(url, headers=None, json=None, timeout=None):
        sent["url"] = url
        sent["headers"] = headers
        sent["body"] = json
        return response

    monkeypatch.setattr(crm_client.requests, "post", fake_post)
    return sent


def test_signs_a_token_scoped_to_autogtm_writer(configured, monkeypatch):
    sent = capture(monkeypatch, StubResponse(200, []))
    crm_client.ingest([{"campaign_ref": "c", "external_key": "k"}])

    token = sent["headers"]["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(token, SECRET, algorithms=["HS256"])

    assert claims["role"] == "autogtm_writer"
    assert claims["exp"] > claims["iat"]


def test_token_is_short_lived(configured, monkeypatch):
    sent = capture(monkeypatch, StubResponse(200, []))
    crm_client.ingest([{"campaign_ref": "c", "external_key": "k"}])

    token = sent["headers"]["Authorization"].removeprefix("Bearer ")
    claims = jwt.decode(token, SECRET, algorithms=["HS256"])
    assert claims["exp"] - claims["iat"] <= 300


def test_never_sends_a_service_role_credential(configured, monkeypatch):
    sent = capture(monkeypatch, StubResponse(200, []))
    crm_client.ingest([{"campaign_ref": "c", "external_key": "k"}])

    blob = json.dumps({k: str(v) for k, v in sent["headers"].items()})
    assert "service_role" not in blob
    token = sent["headers"]["Authorization"].removeprefix("Bearer ")
    assert jwt.decode(token, SECRET, algorithms=["HS256"])["role"] != "service_role"


def test_posts_to_the_rpc_endpoint(configured, monkeypatch):
    sent = capture(monkeypatch, StubResponse(200, []))
    crm_client.ingest([{"campaign_ref": "c", "external_key": "k"}])
    # Trailing slash on the configured URL must not double up.
    assert sent["url"] == "https://example.supabase.co/rest/v1/rpc/ingest_lead"


def test_empty_batch_makes_no_call(configured, monkeypatch):
    called = []
    monkeypatch.setattr(
        crm_client.requests, "post", lambda *a, **k: called.append(1) or StubResponse(200, [])
    )
    assert crm_client.ingest([]) == []
    assert called == []


def test_retries_a_transient_failure(configured, monkeypatch):
    attempts = []

    def fake_post(*_a, **_k):
        attempts.append(1)
        return StubResponse(503) if len(attempts) < 3 else StubResponse(200, [{"ok": True}])

    monkeypatch.setattr(crm_client.requests, "post", fake_post)
    assert crm_client.ingest([{"campaign_ref": "c", "external_key": "k"}]) == [{"ok": True}]
    assert len(attempts) == 3


def test_does_not_retry_a_rejected_payload(configured, monkeypatch):
    attempts = []

    def fake_post(*_a, **_k):
        attempts.append(1)
        return StubResponse(400, text="each lead needs campaign_ref")

    monkeypatch.setattr(crm_client.requests, "post", fake_post)
    with pytest.raises(CrmError, match="400"):
        crm_client.ingest([{"campaign_ref": "c", "external_key": "k"}])
    assert len(attempts) == 1


def test_preflight_rejects_an_unexpected_shape(configured, monkeypatch):
    capture(monkeypatch, StubResponse(200, ["not", "an", "object"]))
    with pytest.raises(CrmError, match="expected an object"):
        crm_client.preflight("c", [], [])


def test_requires_every_credential(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    get_settings.cache_clear()
    with pytest.raises(Exception) as exc:
        crm_client.ingest([{"campaign_ref": "c", "external_key": "k"}])
    assert "SUPABASE_JWT_SECRET" in str(exc.value)
