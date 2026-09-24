"""Runs a campaign: discover -> score -> persist.

Failure is per lead, not per campaign. The previous version let one bad Jev
response abort the run and discard every lead already scored -- work that had
been paid for. Each lead now succeeds or fails on its own and the failure is
recorded on the lead rather than raised.
"""

import logging
from typing import Any, Callable

from agents.icp_agent import build_state_from_campaign_and_lead
from agents.prospector_agent import discover_leads
from agents.scoring_agent import score_lead_with_jev
from app.config import get_settings
from app.schemas.campaign import CampaignRead
from app.schemas.lead import STATUS_FAILED, STATUS_PERSISTED, STATUS_SCORED, LeadRead
from app.services import repository

logger = logging.getLogger(__name__)


def run_campaign(
    campaign: CampaignRead,
    client_factory: Callable[[], Any] | None = None,
) -> list[LeadRead]:
    """Score every discovered lead, persisting those that qualify.

    `client_factory` is injected so the pipeline can be tested end to end
    without a database; production passes nothing and gets the real client.
    """
    settings = get_settings()
    raw_leads = discover_leads(campaign)

    client = None
    if settings.persistence_enabled:
        factory = client_factory or _default_client_factory
        try:
            client = factory()
        except Exception as exc:  # noqa: BLE001 - degrade, do not abort
            logger.error("persistence unavailable, scoring only: %s", exc)

    results: list[LeadRead] = []
    for index, raw_lead in enumerate(raw_leads, start=1):
        results.append(_process_lead(campaign, raw_lead, index, client))
    return results


def _process_lead(
    campaign: CampaignRead,
    raw_lead: dict[str, Any],
    index: int,
    client: Any | None,
) -> LeadRead:
    try:
        state = build_state_from_campaign_and_lead(campaign, raw_lead)
        lead = score_lead_with_jev(
            state,
            campaign_id=campaign.id,
            lead_id=index,
            min_fit_score=campaign.min_fit_score,
        )
    except Exception as exc:  # noqa: BLE001 - one lead must not end the run
        logger.exception("scoring failed for lead %s", index)
        return LeadRead(
            id=index,
            college_name=str(raw_lead.get("college_name", "unknown")),
            source_campaign_id=campaign.id,
            status=STATUS_FAILED,
            error=str(exc),
        )

    if lead.status != STATUS_SCORED or client is None:
        return lead

    try:
        return _persist(client, campaign, raw_lead, lead)
    except Exception as exc:  # noqa: BLE001
        logger.exception("persistence failed for lead %s", index)
        return lead.model_copy(update={"status": STATUS_FAILED, "error": str(exc)})


def _persist(
    client: Any,
    campaign: CampaignRead,
    raw_lead: dict[str, Any],
    lead: LeadRead,
) -> LeadRead:
    college = repository.upsert_college(client, raw_lead)
    college_id = college["id"]

    repository.insert_contact(client, college_id, raw_lead)

    opportunity = repository.insert_opportunity(
        client,
        college_id=college_id,
        campaign_name=campaign.name,
        opportunity_type=campaign.opportunity_type,
        fit_score=lead.fit_score,
        rationale=lead.rationale,
    )

    return lead.model_copy(
        update={
            "status": STATUS_PERSISTED,
            "college_id": str(college_id),
            "opportunity_id": str(opportunity["id"]),
        },
    )


def _default_client_factory() -> Any:
    from app.services.supabase_client import get_client

    return get_client()
