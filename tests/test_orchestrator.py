import pytest

from app.config import get_settings
from app.schemas.campaign import CampaignRead
from app.schemas.lead import (
    STATUS_FAILED,
    STATUS_PERSISTED,
    STATUS_SCORED,
    STATUS_SKIPPED,
    STATUS_UNBUDGETED,
)
from app.services import orchestrator
from app.services.jev_client import JevError
from tests.fakes import FakeCrm, jev_response, percentage_for


def make_campaign(**overrides) -> CampaignRead:
    base = dict(
        id="11111111-1111-1111-1111-111111111111",
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


def stub_decision(level: float, label="strong_fit", send=True):
    """`level` is a score position (0-4), not a percentage. See tests.fakes."""
    return jev_response(fit_label=label, level=level, send_now=0.9 if send else 0.1)


@pytest.fixture
def persisting(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "jwt-secret")
    get_settings.cache_clear()


def patch_jev(monkeypatch, decision):
    calls = []

    def fake(state, questions):
        calls.append(state)
        return decision

    monkeypatch.setattr("agents.scoring_agent.call_jev", fake)
    return calls


def test_qualifying_lead_is_ingested_in_one_batched_call(persisting, monkeypatch):
    patch_jev(monkeypatch, stub_decision(4.0))
    crm = FakeCrm()

    leads = orchestrator.run_campaign(make_campaign(), crm=crm)

    assert [lead.status for lead in leads] == [STATUS_PERSISTED]
    assert len(crm.ingest_calls) == 1  # batched, not one call per lead

    sent = crm.ingest_calls[0][0]
    assert sent["opportunity_type"] == "hackathon"
    assert sent["fit_score"] == percentage_for(4.0) == 100.0
    assert sent["campaign_ref"] == "campaign-11111111-1111-1111-1111-111111111111"
    # Stage and source are the database's to set, never sent from here.
    assert "stage" not in sent and "source" not in sent
    assert leads[0].college_id and leads[0].opportunity_id


def test_preflight_runs_before_scoring_and_skips_the_jev_call(persisting, monkeypatch):
    calls = patch_jev(monkeypatch, stub_decision(4.0))
    crm = FakeCrm()
    campaign = make_campaign()

    orchestrator.run_campaign(campaign, crm=crm)
    assert len(calls) == 1

    # Second run: already ingested, so nothing should be scored again.
    orchestrator.run_campaign(campaign, crm=crm)
    assert len(calls) == 1, "re-scored a lead the CRM had already ingested"
    assert len(crm.ingest_calls) == 1


def test_rerun_reports_the_lead_as_persisted(persisting, monkeypatch):
    patch_jev(monkeypatch, stub_decision(4.0))
    crm = FakeCrm()
    campaign = make_campaign()

    orchestrator.run_campaign(campaign, crm=crm)
    leads = orchestrator.run_campaign(campaign, crm=crm)

    assert [lead.status for lead in leads] == [STATUS_PERSISTED]


def test_external_key_is_stable_for_the_same_college():
    a = orchestrator.external_key({"college_name": "Vasavi College of Engineering"})
    b = orchestrator.external_key({"college_name": "  vasavi college of ENGINEERING "})
    assert a == b


def test_lead_below_threshold_is_never_sent_to_the_crm(persisting, monkeypatch):
    patch_jev(monkeypatch, stub_decision(2.0))
    crm = FakeCrm()

    leads = orchestrator.run_campaign(make_campaign(), crm=crm)

    assert leads[0].status == STATUS_SKIPPED
    assert crm.ingest_calls == []


def test_threshold_is_per_campaign(persisting, monkeypatch):
    # Level 2 of 4 normalises to 50, which clears a 40 threshold but not 70.
    patch_jev(monkeypatch, stub_decision(2.0))
    crm = FakeCrm()

    assert percentage_for(2.0) == 50.0
    leads = orchestrator.run_campaign(make_campaign(min_fit_score=40.0), crm=crm)

    assert leads[0].status == STATUS_PERSISTED


def test_send_now_false_blocks_a_high_score(persisting, monkeypatch):
    patch_jev(monkeypatch, stub_decision(4.0, send=False))
    crm = FakeCrm()

    leads = orchestrator.run_campaign(make_campaign(), crm=crm)

    assert leads[0].status == STATUS_SKIPPED
    assert crm.ingest_calls == []


def test_scoring_failure_is_recorded_on_the_lead_not_raised(persisting, monkeypatch):
    def boom(state, questions):
        raise JevError("Jev unreachable after 3 attempts")

    monkeypatch.setattr("agents.scoring_agent.call_jev", boom)
    crm = FakeCrm()

    leads = orchestrator.run_campaign(make_campaign(), crm=crm)

    assert leads[0].status == STATUS_FAILED
    assert "unreachable" in leads[0].error
    assert crm.ingest_calls == []


def test_ingest_failure_keeps_the_score(persisting, monkeypatch):
    patch_jev(monkeypatch, stub_decision(4.0))
    crm = FakeCrm(fail_ingest=True)

    leads = orchestrator.run_campaign(make_campaign(), crm=crm)

    assert leads[0].status == STATUS_FAILED
    assert leads[0].fit_score == 100.0  # the paid-for judgement is not discarded


def test_preflight_failure_degrades_to_scoring_everything(persisting, monkeypatch):
    calls = patch_jev(monkeypatch, stub_decision(4.0))
    crm = FakeCrm(fail_preflight=True)

    leads = orchestrator.run_campaign(make_campaign(), crm=crm)

    assert len(calls) == 1
    assert leads[0].status == STATUS_PERSISTED


def test_runs_without_crm_configured(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    get_settings.cache_clear()
    patch_jev(monkeypatch, stub_decision(4.0))
    crm = FakeCrm()

    leads = orchestrator.run_campaign(make_campaign(), crm=crm)

    assert leads[0].status == STATUS_SCORED
    assert crm.ingest_calls == []
    assert leads[0].college_id is None


class TestEvidenceGate:
    """A score built on no crawled evidence must not auto-qualify.

    In one calibration slice, comparable colleges with no website evidence
    scored 41.2 and 99.5, and every label/score disagreement occurred there.
    """

    @pytest.fixture
    def enriching(self, persisting, monkeypatch):
        monkeypatch.setenv("ENRICHMENT_ENABLED", "true")
        get_settings.cache_clear()
        # No network: enrichment returns each lead unchanged.
        monkeypatch.setattr(
            "agents.enrichment.enricher.enrich_all",
            lambda leads, cache_dir, timeout, max_pages: list(leads),
        )

    def test_thin_evidence_is_held_like_no_evidence(self, enriching, monkeypatch):
        # 50 characters produced the top score of a real slice; the gate is a
        # volume threshold, not a presence check.
        patch_jev(monkeypatch, stub_decision(4.0))
        crm = FakeCrm()
        monkeypatch.setattr(
            "agents.enrichment.enricher.enrich_all",
            lambda leads, cache_dir, timeout, max_pages: [
                {**l, "evidence": {"scale": ["Autonomous institution."]}} for l in leads
            ],
        )

        leads = orchestrator.run_campaign(make_campaign(), crm=crm)

        assert leads[0].status == "needs_evidence"
        assert crm.ingest_calls == []

    def test_a_high_score_with_no_evidence_is_held_not_persisted(
        self, enriching, monkeypatch
    ):
        patch_jev(monkeypatch, stub_decision(4.0))  # would be 100/100
        crm = FakeCrm()

        leads = orchestrator.run_campaign(make_campaign(), crm=crm)

        assert leads[0].status == "needs_evidence"
        assert leads[0].fit_score == 100.0  # the judgement is kept, not discarded
        assert crm.ingest_calls == [], "wrote a lead judged on no evidence"

    def test_evidence_present_qualifies_normally(self, enriching, monkeypatch):
        patch_jev(monkeypatch, stub_decision(4.0))
        crm = FakeCrm()
        monkeypatch.setattr(
            "agents.enrichment.enricher.enrich_all",
            # Realistic volume: the gate is a character threshold, and a
            # one-line excerpt is exactly the thin evidence it exists to catch.
            lambda leads, cache_dir, timeout, max_pages: [
                {**l, "evidence": {"placement": ["An active training and placement cell. " * 12],
                                   "events": ["Hosted a national hackathon last year. " * 6]}}
                for l in leads
            ],
        )

        leads = orchestrator.run_campaign(make_campaign(), crm=crm)

        assert leads[0].status == STATUS_PERSISTED

    def test_the_gate_is_off_when_enrichment_is_off(self, persisting, monkeypatch):
        # Enrichment disabled means we knowingly work from roster data; holding
        # every lead would stall the pipeline instead of protecting it.
        patch_jev(monkeypatch, stub_decision(4.0))
        crm = FakeCrm()

        leads = orchestrator.run_campaign(make_campaign(), crm=crm)

        assert leads[0].status == STATUS_PERSISTED


class TestSpendCeiling:
    """A campaign's ceiling on how many colleges it may score.

    Scoring is what gets billed, and targeting that matches ten times the
    intended pool costs ten times as much with nothing to stop it. The first
    anyone would know is the invoice.
    """

    @staticmethod
    def _five_colleges(monkeypatch) -> None:
        monkeypatch.setattr(
            orchestrator,
            "discover_leads",
            lambda campaign: [
                {"college_name": f"College {n}", "city": "Hyderabad", "state": "Telangana"}
                for n in range(1, 6)
            ],
        )

    def test_scores_only_what_the_campaign_can_still_afford(self, persisting, monkeypatch):
        self._five_colleges(monkeypatch)
        calls = patch_jev(monkeypatch, stub_decision(4.0))
        crm = FakeCrm()

        leads = orchestrator.run_campaign(
            make_campaign(max_jev_calls=2), crm=crm, stats={"jev_calls": 0}
        )

        assert len(calls) == 2, "scored past the ceiling"
        assert [lead.status for lead in leads[:2]] == [STATUS_PERSISTED, STATUS_PERSISTED]
        assert all(lead.status == STATUS_UNBUDGETED for lead in leads[2:])

    def test_counts_what_earlier_runs_already_spent(self, persisting, monkeypatch):
        # The ceiling is a lifetime count, so a second run inherits the spend
        # of the first rather than starting over.
        self._five_colleges(monkeypatch)
        calls = patch_jev(monkeypatch, stub_decision(4.0))

        orchestrator.run_campaign(
            make_campaign(max_jev_calls=4, jev_calls_used=3), crm=FakeCrm()
        )

        assert len(calls) == 1

    def test_says_so_in_the_stats_when_the_ceiling_stopped_it(self, persisting, monkeypatch):
        self._five_colleges(monkeypatch)
        patch_jev(monkeypatch, stub_decision(4.0))
        stats: dict[str, int] = {"jev_calls": 0}

        orchestrator.run_campaign(make_campaign(max_jev_calls=2), crm=FakeCrm(), stats=stats)

        assert stats["budget_exhausted"]
        assert stats["jev_calls"] == 2

    def test_a_spent_campaign_scores_nothing_rather_than_one_more(self, persisting, monkeypatch):
        self._five_colleges(monkeypatch)
        calls = patch_jev(monkeypatch, stub_decision(4.0))

        leads = orchestrator.run_campaign(
            make_campaign(max_jev_calls=2, jev_calls_used=9), crm=FakeCrm()
        )

        assert calls == []
        assert all(lead.status == STATUS_UNBUDGETED for lead in leads)

    def test_an_unbudgeted_lead_explains_itself(self, persisting, monkeypatch):
        # It was never looked at. Reading that as a low score would park a
        # college that has not been judged at all.
        self._five_colleges(monkeypatch)
        patch_jev(monkeypatch, stub_decision(4.0))

        leads = orchestrator.run_campaign(make_campaign(max_jev_calls=1), crm=FakeCrm())

        assert "ceiling" in (leads[-1].rationale or "")
        assert leads[-1].fit_score == 0.0

    def test_no_ceiling_means_no_ceiling(self, persisting, monkeypatch):
        self._five_colleges(monkeypatch)
        calls = patch_jev(monkeypatch, stub_decision(4.0))
        stats: dict[str, int] = {"jev_calls": 0}

        leads = orchestrator.run_campaign(make_campaign(), crm=FakeCrm(), stats=stats)

        assert len(calls) == 5
        assert stats.get("budget_exhausted") is None
        assert not [lead for lead in leads if lead.status == STATUS_UNBUDGETED]

    def test_the_unaffordable_are_never_crawled(self, persisting, monkeypatch):
        # Enrichment is the stage that touches someone else's servers, and it
        # is the slow one. Crawling a college the campaign cannot afford to
        # score spends the run's time for nothing.
        self._five_colleges(monkeypatch)
        patch_jev(monkeypatch, stub_decision(4.0))
        monkeypatch.setenv("ENRICHMENT_ENABLED", "1")
        get_settings.cache_clear()
        crawled: list[str] = []

        def fake_enrich(leads, cache_dir, timeout, max_pages):
            crawled.extend(lead["college_name"] for lead in leads)
            return leads

        monkeypatch.setattr("agents.enrichment.enricher.enrich_all", fake_enrich)

        orchestrator.run_campaign(make_campaign(max_jev_calls=2), crm=FakeCrm())

        assert crawled == ["College 1", "College 2"]
