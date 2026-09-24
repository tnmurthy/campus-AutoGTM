import pytest

from app.config import get_settings
from app.services import jev_client
from app.services.jev_client import JevError, answer


class StubResponse:
    def __init__(self, status_code: int, body=None, raises=False):
        self.status_code = status_code
        self._body = body
        self._raises = raises

    def json(self):
        if self._raises:
            raise ValueError("not json")
        return self._body


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("JEV_MAX_ATTEMPTS", "3")
    get_settings.cache_clear()
    monkeypatch.setattr(jev_client.time, "sleep", lambda _: None)


def test_retries_then_succeeds_on_transient_error(configured, monkeypatch):
    calls = []

    def fake_post(*_args, **_kwargs):
        calls.append(1)
        if len(calls) < 3:
            return StubResponse(503)
        return StubResponse(200, {"fit_score": {"value": 81}})

    monkeypatch.setattr(jev_client.requests, "post", fake_post)
    assert jev_client.call_jev({}, {})["fit_score"]["value"] == 81
    assert len(calls) == 3


def test_client_error_is_not_retried(configured, monkeypatch):
    calls = []

    def fake_post(*_args, **_kwargs):
        calls.append(1)
        return StubResponse(400)

    monkeypatch.setattr(jev_client.requests, "post", fake_post)
    with pytest.raises(JevError, match="400"):
        jev_client.call_jev({}, {})
    assert len(calls) == 1


def test_error_message_does_not_echo_the_request_body(configured, monkeypatch):
    monkeypatch.setattr(jev_client.requests, "post", lambda *a, **k: StubResponse(403))
    with pytest.raises(JevError) as exc:
        jev_client.call_jev({"lead": {"email": "secret@college.edu"}}, {})
    assert "secret@college.edu" not in str(exc.value)


def test_non_json_body_is_reported_clearly(configured, monkeypatch):
    monkeypatch.setattr(
        jev_client.requests, "post", lambda *a, **k: StubResponse(200, raises=True)
    )
    with pytest.raises(JevError, match="non-JSON"):
        jev_client.call_jev({}, {})


def test_answer_names_the_missing_field():
    with pytest.raises(JevError, match="fit_label"):
        answer({"fit_score": {"value": 10}}, "fit_label")
