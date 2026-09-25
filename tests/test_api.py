import pytest
from fastapi.testclient import TestClient

from app.config import get_settings

# One client for the module rather than one per test. Each TestClient spins up
# its own portal thread and socket machinery, and on a machine whose ephemeral
# port pool is already under pressure that churn is what turns a fast suite
# into a hung one. Settings are read per request, so a single client serves
# tests with and without credentials.
_client: TestClient | None = None


def _app_client() -> TestClient:
    global _client
    if _client is None:
        from app.main import app

        _client = TestClient(app)
    return _client


@pytest.fixture
def client(monkeypatch):
    """A client whose campaign store is a fake, not the real database.

    Campaigns are rows in BrainOpsHub now, so the endpoints need a CRM. The
    fake mirrors campaign_upsert and campaign_fetch, including their
    validation, so these tests exercise the route rather than the network.
    """
    from tests.fakes import FakeCrm

    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "jwt-secret")
    get_settings.cache_clear()

    from app.api import campaigns as campaigns_api
    from app.services import orchestrator

    # Both modules hold their own reference. Patching only the route left the
    # orchestrator reaching the real host, which failed slowly through DNS
    # retries and read as a hung test rather than a wrong one.
    fake = FakeCrm()
    monkeypatch.setattr(campaigns_api, "crm_client", fake)
    monkeypatch.setattr(orchestrator, "crm_client", fake)
    test_client = _app_client()
    test_client.fake_crm = fake  # type: ignore[attr-defined]
    return test_client


@pytest.fixture
def client_without_crm(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    get_settings.cache_clear()
    return _app_client()


def test_campaigns_say_so_when_the_database_is_not_configured(client_without_crm):
    # Half-working is worse than refusing: campaigns live in BrainOpsHub.
    response = client_without_crm.post("/campaigns/", json=_payload())
    assert response.status_code == 503
    assert "SUPABASE_URL" in response.json()["detail"]


def test_app_imports_and_health_answers_with_no_credentials():
    # The whole point of moving the credential check off import.
    get_settings.cache_clear()
    body = _app_client().get("/health/").json()
    assert body["status"] == "ok"
    assert body["jev_configured"] is False
    assert body["persistence_enabled"] is False


def test_health_never_leaks_the_key(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "super-secret-value")
    get_settings.cache_clear()
    raw = _app_client().get("/health/").text
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


def test_a_created_campaign_survives_and_is_listed(client):
    created = client.post("/campaigns/", json=_payload(name="Persisted Sweep")).json()

    listed = client.get("/campaigns/").json()

    assert [c["id"] for c in listed] == [created["id"]]
    assert listed[0]["name"] == "Persisted Sweep"


def test_run_unknown_campaign_is_404(client):
    assert client.post("/campaigns/33333333-3333-3333-3333-333333333333/run").status_code == 404


def test_an_inactive_campaign_will_not_run(client):
    created = client.post("/campaigns/", json=_payload()).json()
    client.fake_crm.campaigns[created["id"]]["is_active"] = False

    assert client.post(f"/campaigns/{created['id']}/run").status_code == 409


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
    from tests.fakes import jev_response

    monkeypatch.setattr(
        "agents.scoring_agent.call_jev",
        lambda state, questions: jev_response(level=4.0),
    )
    # Targeting that matches the stub lead; this test is about the threadpool
    # hand-off, not about the prospector's campaign filter.
    campaign_id = client.post(
        "/campaigns/",
        json=_payload(college_types=["Engineering"], departments=["CSE"]),
    ).json()["id"]

    leads = client.post(f"/campaigns/{campaign_id}/run").json()

    assert len(leads) == 1
    assert leads[0]["fit_score"] == 100.0
    # The fixture configures a CRM, so a qualifying lead goes all the way in.
    assert leads[0]["status"] == "persisted"
    assert client.fake_crm.ingest_calls, "the run never reached the CRM"
    assert client.get("/leads/").json()[0]["college_name"] == leads[0]["college_name"]
