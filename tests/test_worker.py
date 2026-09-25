import pytest

from app.config import get_settings
from app.services import worker
from tests.fakes import FakeCrm, jev_response

"""
The worker that executes queued runs.

A run crawls every candidate college before scoring it, so it cannot happen
inside an HTTP request. These cover the claim-execute-record cycle and what
happens when a run fails partway.
"""


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("TYPESAFE_API_KEY", "test-key")
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")
    monkeypatch.setenv("SUPABASE_JWT_SECRET", "jwt-secret")
    get_settings.cache_clear()
    monkeypatch.setattr(
        "agents.scoring_agent.call_jev", lambda state, questions: jev_response(level=4.0)
    )


def seeded_crm() -> tuple[FakeCrm, str]:
    crm = FakeCrm()
    campaign = crm.campaign_upsert(
        {
            "name": "Worker Sweep",
            "segment_states": [],
            "college_types": ["Engineering"],
            "departments": ["CSE"],
            "objective": "book hackathons",
            "opportunity_type": "hackathon",
            "min_fit_score": 70.0,
        }
    )
    return crm, campaign["id"]


class TestRunOnce:
    def test_returns_none_when_the_queue_is_empty(self, configured):
        assert worker.run_once(crm=FakeCrm()) is None

    def test_claims_executes_and_records_the_outcome(self, configured):
        crm, campaign_id = seeded_crm()
        run = crm.run_enqueue(campaign_id)

        result = worker.run_once(crm=crm)

        assert result is not None
        assert result["status"] == "succeeded"
        stored = crm.run_fetch(run["id"])
        assert stored["status"] == "succeeded"
        assert stored["leads_found"] == 1
        assert stored["leads_persisted"] == 1
        # The cost of the run, which is the number ops will ask about.
        assert stored["jev_calls"] == 1

    def test_counts_a_skipped_lead_separately_from_a_persisted_one(self, configured, monkeypatch):
        # Below the campaign threshold: scored, deliberately not written.
        monkeypatch.setattr(
            "agents.scoring_agent.call_jev", lambda state, questions: jev_response(level=1.0)
        )
        crm, campaign_id = seeded_crm()
        crm.run_enqueue(campaign_id)

        worker.run_once(crm=crm)

        stored = next(iter(crm.runs.values()))
        assert stored["leads_persisted"] == 0
        assert stored["leads_skipped"] == 1

    def test_marks_the_run_failed_when_the_campaign_has_gone(self, configured):
        crm = FakeCrm()
        crm.runs["run-x"] = {
            "id": "run-x",
            "campaign_id": "missing",
            "status": "queued",
            "attempt": 0,
        }

        result = worker.run_once(crm=crm)

        assert result == {"id": "run-x", "status": "failed"}
        assert crm.run_fetch("run-x")["status"] == "failed"
        assert "no longer exists" in crm.run_fetch("run-x")["error"]

    def test_records_the_failure_rather_than_raising_out_of_the_loop(self, configured, monkeypatch):
        crm, campaign_id = seeded_crm()
        crm.run_enqueue(campaign_id)

        def explode(*_args, **_kwargs):
            raise RuntimeError("prospector exploded")

        monkeypatch.setattr("app.services.orchestrator.discover_leads", explode)

        result = worker.run_once(crm=crm)

        assert result["status"] == "failed"
        stored = next(iter(crm.runs.values()))
        assert stored["status"] == "failed"
        assert "exploded" in stored["error"]


class TestHeartbeat:
    def test_reports_liveness_while_a_run_is_in_progress(self):
        # Distinguishing slow from dead is the whole point: crawling is slow,
        # so silence cannot be read as failure without this.
        crm = FakeCrm()
        with worker._Heartbeat(crm, "run-1", every=0.01):
            import time

            time.sleep(0.08)

        assert crm.heartbeats, "no heartbeat was sent during the run"
        assert all(r == "run-1" for r in crm.heartbeats)

    def test_a_failed_heartbeat_does_not_end_the_run(self):
        class Flaky(FakeCrm):
            def run_heartbeat(self, run_id: str) -> None:
                raise RuntimeError("network blip")

        with worker._Heartbeat(Flaky(), "run-1", every=0.01):
            import time

            time.sleep(0.05)
        # Reaching here is the assertion: a missed beat is not fatal.


class TestServe:
    def test_stops_after_the_bounded_number_of_iterations(self, configured, monkeypatch):
        calls: list[int] = []
        monkeypatch.setattr(worker, "run_once", lambda: calls.append(1))
        monkeypatch.setattr(worker.time, "sleep", lambda _s: None)

        worker.serve(poll_seconds=0, max_iterations=3)

        assert len(calls) == 3

    def test_a_bad_run_does_not_end_the_worker(self, configured, monkeypatch):
        attempts: list[int] = []

        def sometimes_explode():
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("one bad run")

        monkeypatch.setattr(worker, "run_once", sometimes_explode)
        monkeypatch.setattr(worker.time, "sleep", lambda _s: None)

        worker.serve(poll_seconds=0, max_iterations=3)

        assert len(attempts) == 3
