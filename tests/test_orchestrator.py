import pytest

from app.config import get_settings
from app.schemas.campaign import CampaignRead
from app.schemas.lead import (
    STATUS_FAILED,
    STATUS_PERSISTED,
    STATUS_SCORED,
    STATUS_SKIPPED,
)
from app.services import orchestrator
from app.services.jev_client import JevError
from tests.fakes import FakeSupabase


def make_campaign(**overrides) -> CampaignRead:
    base = dict(
        id=1,
        name="Telangana AI Hackathon Sweep",
        segment_states=["Telangana"],
        college_types=["Engineering Autonomous"],
        departments=["CSE"],
        objective="Book 10 hackathons",
        target_meetings_per_week=5,
        opportunity_type="hackathon",
        min_fit_score=70.0,
    )
    base.update(overrides)
    return CampaignRead(**base)


def stub_decision(score: float, label="strong_fit", send=True):
    return {
        "fit_label": {"value": label},
        "fit_score": {"value": score},
        "send_now": {"value": send},
        "rationale": {"value": "Active T&P cell and recent hackathon."},
    }


@pytest.fixture
def persisting(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "service-key")
    get_settings.cache_clear()


def patch_jev(monkeypatch, decision):
    monkeypatch.setattr(
        "agents.scoring_agent.call_jev", lambda state, questions: decision
    )


def test_qualifying_lead_is_written_to_all_three_tables(persisting, monkeypatch):
    patch_jev(monkeypatch, stub_decision(88))
    client = FakeSupabase()

    leads = orchestrator.run_campaign(make_campaign(), client_factory=lambda: client)

    assert [lead.status for lead in leads] == [STATUS_PERSISTED]
    written = [table for table, _ in client.writes]
    assert written == ["colleges", "contacts", "opportunities"]

    opportunity = client.rows["opportunities"][0]
    assert opportunity["stage"] == "enquiry"
    assert opportunity["opportunity_type"] == "hackathon"
    assert opportunity["probability"] == 88
    assert opportunity["notes"] == "Active T&P cell and recent hackathon."
    assert leads[0].college_id and leads[0].opportunity_id


def test_lead_below_threshold_is_skipped_and_never_written(persisting, monkeypatch):
    patch_jev(monkeypatch, stub_decision(65))
    client = FakeSupabase()

    leads = orchestrator.run_campaign(make_campaign(), client_factory=lambda: client)

    assert leads[0].status == STATUS_SKIPPED
    assert client.writes == []


def test_threshold_is_per_campaign_not_global(persisting, monkeypatch):
    patch_jev(monkeypatch, stub_decision(65))
    client = FakeSupabase()

    leads = orchestrator.run_campaign(
        make_campaign(min_fit_score=60.0), client_factory=lambda: client
    )

    assert leads[0].status == STATUS_PERSISTED


def test_send_now_false_blocks_a_high_score(persisting, monkeypatch):
    patch_jev(monkeypatch, stub_decision(95, send=False))
    client = FakeSupabase()

    leads = orchestrator.run_campaign(make_campaign(), client_factory=lambda: client)

    assert leads[0].status == STATUS_SKIPPED
    assert client.writes == []


def test_reject_label_blocks_a_high_score(persisting, monkeypatch):
    patch_jev(monkeypatch, stub_decision(95, label="reject"))
    client = FakeSupabase()

    leads = orchestrator.run_campaign(make_campaign(), client_factory=lambda: client)

    assert leads[0].status == STATUS_SKIPPED


def test_existing_college_is_reused_not_duplicated(persisting, monkeypatch):
    patch_jev(monkeypatch, stub_decision(88))
    client = FakeSupabase()

    orchestrator.run_campaign(make_campaign(), client_factory=lambda: client)
    orchestrator.run_campaign(make_campaign(), client_factory=lambda: client)

    assert len(client.rows["colleges"]) == 1
    assert len(client.rows["opportunities"]) == 2


def test_scoring_failure_is_recorded_on_the_lead_not_raised(persisting, monkeypatch):
    def boom(state, questions):
        raise JevError("Jev unreachable after 3 attempts")

    monkeypatch.setattr("agents.scoring_agent.call_jev", boom)
    client = FakeSupabase()

    leads = orchestrator.run_campaign(make_campaign(), client_factory=lambda: client)

    assert leads[0].status == STATUS_FAILED
    assert "unreachable" in leads[0].error
    assert client.writes == []


def test_persistence_failure_keeps_the_score(persisting, monkeypatch):
    patch_jev(monkeypatch, stub_decision(88))
    client = FakeSupabase(fail_on={"opportunities"})

    leads = orchestrator.run_campaign(make_campaign(), client_factory=lambda: client)

    assert leads[0].status == STATUS_FAILED
    assert leads[0].fit_score == 88  # the paid-for judgement is not discarded
    assert "opportunities" in leads[0].error


def test_runs_without_supabase_configured(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    get_settings.cache_clear()
    patch_jev(monkeypatch, stub_decision(88))

    leads = orchestrator.run_campaign(make_campaign())

    assert leads[0].status == STATUS_SCORED
    assert leads[0].college_id is None


def test_unreachable_database_degrades_to_scoring_only(persisting, monkeypatch):
    patch_jev(monkeypatch, stub_decision(88))

    def broken_factory():
        raise RuntimeError("connection refused")

    leads = orchestrator.run_campaign(make_campaign(), client_factory=broken_factory)

    assert leads[0].status == STATUS_SCORED
