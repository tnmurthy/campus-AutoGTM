import pytest
from fastapi.testclient import TestClient

from app.config import get_settings


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    get_settings.cache_clear()
    from app.main import app

    return TestClient(app)


def test_app_imports_and_health_answers_with_no_credentials():
    # The whole point of moving the credential check off import.
    get_settings.cache_clear()
    from app.main import app

    body = TestClient(app).get("/health/").json()
    assert body["status"] == "ok"
    assert body["jev_configured"] is False
    assert body["persistence_enabled"] is False


def test_health_never_leaks_the_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "super-secret-value")
    get_settings.cache_clear()
    from app.main import app

    raw = TestClient(app).get("/health/").text
    assert "super-secret-value" not in raw
    assert '"jev_configured":true' in raw.replace(" ", "")


def test_campaign_rejects_an_opportunity_type_postgres_would_reject(client):
    response = client.post("/campaigns/", json=_payload(opportunity_type="webinar"))
    assert response.status_code == 422
    assert "opportunity_type" in response.json()["detail"]


def test_campaign_defaults_threshold_to_seventy(client):
    body = client.post("/campaigns/", json=_payload()).json()
    assert body["min_fit_score"] == 70.0
    assert body["opportunity_type"] == "training"


def test_run_unknown_campaign_is_404(client):
    assert client.post("/campaigns/999/run").status_code == 404


def _payload(**overrides):
    base = {
        "name": "Degree College Training Push",
        "segment_states": ["Telangana"],
        "college_types": ["Degree"],
        "departments": ["BCA"],
        "objective": "Book training weeks",
        "target_meetings_per_week": 4,
    }
    base.update(overrides)
    return base


def test_run_endpoint_executes_the_pipeline_off_the_event_loop(client, monkeypatch):
    # Exercises the threadpool hand-off in the run route, which the unit tests
    # bypass by calling run_campaign directly.
    monkeypatch.setattr(
        "agents.scoring_agent.call_jev",
        lambda state, questions: {
            "fit_label": {"value": "strong_fit"},
            "fit_score": {"value": 91},
            "send_now": {"value": True},
            "rationale": {"value": "Strong CSE cohort."},
        },
    )
    # Targeting that matches the stub lead; this test is about the threadpool
    # hand-off, not about the prospector's campaign filter.
    campaign_id = client.post(
        "/campaigns/",
        json=_payload(college_types=["Engineering"], departments=["CSE"]),
    ).json()["id"]

    leads = client.post(f"/campaigns/{campaign_id}/run").json()

    assert len(leads) == 1
    assert leads[0]["fit_score"] == 91
    assert leads[0]["status"] == "scored"  # no Supabase configured in this fixture
    assert client.get("/leads/").json()[0]["college_name"] == leads[0]["college_name"]
