"""Runs a campaign: discover -> preflight -> score only what is new -> ingest.

Two orderings here are deliberate.

Preflight comes before scoring. Jev is the cost in this pipeline and the
database is nearly free, so asking which leads have already been ingested
before paying to judge them makes a re-run almost free. Scoring first and
deduplicating afterwards -- the original order -- paid for every lead every
time.

Persistence is one batched call to ingest_lead, not three inserts per lead.
Atomicity, idempotency and least privilege all live in that function; this
module no longer knows the schema.
"""

import hashlib
import logging
from typing import Any

from agents.icp_agent import build_state_from_campaign_and_lead
from agents.prospector_agent import discover_leads
from agents.scoring_agent import score_lead_with_jev
from app.config import get_settings
from app.schemas.campaign import CampaignRead
from app.schemas.lead import (
    STATUS_FAILED,
    STATUS_NEEDS_EVIDENCE,
    STATUS_PERSISTED,
    STATUS_SCORED,
    STATUS_SKIPPED,
    LeadRead,
)
from app.services import crm_client

logger = logging.getLogger(__name__)


def campaign_ref(campaign: CampaignRead) -> str:
    return f"campaign-{campaign.id}"


def external_key(raw_lead: dict[str, Any]) -> str:
    """A stable identifier for a discovered lead.

    Derived from the college name rather than a random id, so the same college
    rediscovered next week resolves to the row already written instead of
    opening a duplicate deal.
    """
    basis = str(raw_lead.get("college_name", "")).strip().lower()
    return hashlib.sha256(basis.encode("utf-8")).hexdigest()[:32]


def run_campaign(campaign: CampaignRead, crm: Any = crm_client) -> list[LeadRead]:
    """Score and persist a campaign's leads.

    `crm` is injected so the pipeline is testable without a database; callers
    pass nothing and get the real client.
    """
    settings = get_settings()
    raw_leads = discover_leads(campaign)
    ref = campaign_ref(campaign)

    keyed = [(external_key(raw), raw) for raw in raw_leads]

    known_keys = _already_ingested(crm, ref, keyed) if settings.persistence_enabled else set()

    # Enrich only what will actually be scored. Enrichment is the one stage
    # that touches someone else's servers, so a college already ingested for
    # this campaign is neither crawled nor judged.
    to_score = [(k, raw) for k, raw in keyed if k not in known_keys]
    if settings.enrichment_enabled and to_score:
        from agents.enrichment.enricher import enrich_all

        enriched = enrich_all(
            [raw for _, raw in to_score],
            cache_dir=settings.enrichment_cache_dir,
            timeout=settings.enrichment_timeout_seconds,
            max_pages=settings.enrichment_max_pages,
        )
        by_key = {k: e for (k, _), e in zip(to_score, enriched)}
        keyed = [(k, by_key.get(k, raw)) for k, raw in keyed]

    results: list[LeadRead] = []
    pending: list[tuple[int, dict[str, Any], LeadRead]] = []

    for index, (key, raw) in enumerate(keyed, start=1):
        if key in known_keys:
            # Already in the CRM for this campaign. Skipping the Jev call is
            # the entire point of preflight.
            results.append(
                LeadRead(
                    id=index,
                    college_name=str(raw.get("college_name", "unknown")),
                    source_campaign_id=campaign.id,
                    status=STATUS_PERSISTED,
                )
            )
            continue

        lead = _score(campaign, raw, index)

        # Enrichment ran and found nothing, so the score rests on a name, a
        # type and a city. In one calibration slice that produced 41.2 and
        # 99.5 for comparable institutions, and every label/score disagreement
        # sat here. Held for a person rather than auto-qualified either way.
        if settings.enrichment_enabled and not lead.has_evidence:
            lead = lead.model_copy(update={"status": STATUS_NEEDS_EVIDENCE})

        results.append(lead)
        if lead.status == STATUS_SCORED:
            pending.append((index, raw, lead))

    if pending and settings.persistence_enabled:
        _ingest(crm, campaign, ref, pending, results)

    return results


def _already_ingested(
    crm: Any, ref: str, keyed: list[tuple[str, dict[str, Any]]]
) -> set[str]:
    if not keyed:
        return set()
    try:
        answer = crm.preflight(
            campaign_ref=ref,
            external_keys=[k for k, _ in keyed],
            college_names=[str(raw.get("college_name", "")) for _, raw in keyed],
        )
        return {str(k) for k in answer.get("known_keys", [])}
    except Exception as exc:  # noqa: BLE001 - degrade to scoring everything
        logger.warning("preflight unavailable, scoring every lead: %s", exc)
        return set()


def _score(campaign: CampaignRead, raw: dict[str, Any], index: int) -> LeadRead:
    try:
        state = build_state_from_campaign_and_lead(campaign, raw)
        return score_lead_with_jev(
            state,
            campaign_id=campaign.id,
            lead_id=index,
            min_fit_score=campaign.min_fit_score,
        )
    except Exception as exc:  # noqa: BLE001 - one lead must not end the run
        logger.exception("scoring failed for lead %s", index)
        return LeadRead(
            id=index,
            college_name=str(raw.get("college_name", "unknown")),
            source_campaign_id=campaign.id,
            status=STATUS_FAILED,
            error=str(exc),
        )


def _ingest(
    crm: Any,
    campaign: CampaignRead,
    ref: str,
    pending: list[tuple[int, dict[str, Any], LeadRead]],
    results: list[LeadRead],
) -> None:
    payload = [
        {
            "campaign_ref": ref,
            "external_key": external_key(raw),
            "campaign_name": campaign.name,
            "college_name": raw.get("college_name"),
            "college_type": raw.get("type"),
            "city": raw.get("city"),
            "state": raw.get("state"),
            "notes": _signals_note(raw),
            "contact_name": raw.get("contact_name"),
            "contact_role": raw.get("contact_role"),
            "email": raw.get("email"),
            "opportunity_type": campaign.opportunity_type,
            "fit_score": lead.fit_score,
            "rationale": lead.rationale,
        }
        for _, raw, lead in pending
    ]

    try:
        written = crm.ingest(payload)
    except Exception as exc:  # noqa: BLE001
        logger.exception("ingest failed for %s leads", len(payload))
        for index, _, lead in pending:
            results[index - 1] = lead.model_copy(
                update={"status": STATUS_FAILED, "error": str(exc)}
            )
        return

    by_key = {str(row.get("external_key")): row for row in written}
    for index, raw, lead in pending:
        row = by_key.get(external_key(raw))
        if row is None:
            results[index - 1] = lead.model_copy(
                update={"status": STATUS_FAILED, "error": "no ingest result for lead"}
            )
            continue
        results[index - 1] = lead.model_copy(
            update={
                "status": STATUS_PERSISTED,
                "college_id": str(row.get("college_id")) if row.get("college_id") else None,
                "opportunity_id": (
                    str(row.get("opportunity_id")) if row.get("opportunity_id") else None
                ),
            }
        )


def _signals_note(raw: dict[str, Any]) -> str | None:
    """What the CRM records about where this college came from."""
    parts: list[str] = []
    if raw.get("notes"):
        parts.append(str(raw["notes"]))
    if raw.get("signals"):
        parts.append("Signals: " + "; ".join(str(s) for s in raw["signals"]))
    return " | ".join(parts) or None


__all__ = ["run_campaign", "campaign_ref", "external_key", "STATUS_SKIPPED"]
