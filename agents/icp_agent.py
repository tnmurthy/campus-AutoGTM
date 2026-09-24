"""Builds the state a scoring question is judged against.

Shaped deliberately rather than dumping the raw lead: the questions ask about
departments, a training and placement cell, and event history, so those are
named fields the model can find. Bookkeeping the model cannot use -- which
pages the crawler happened to read -- is left out; it belongs in the CRM note,
not in a judgement.
"""

from typing import Any

from app.schemas.campaign import CampaignRead

# Copied verbatim into `college` when present.
LEAD_FACTS = ("college_name", "college_type", "city", "state", "segment", "website", "notes")


def build_state_from_campaign_and_lead(campaign: CampaignRead, lead: dict) -> dict:
    college: dict[str, Any] = {
        key: lead[key] for key in LEAD_FACTS if lead.get(key) not in (None, "", [])
    }
    if lead.get("departments"):
        college["departments"] = lead["departments"]

    state: dict[str, Any] = {
        "campaign": {
            "name": campaign.name,
            "objective": campaign.objective,
            "target_states": campaign.segment_states,
            "target_college_types": campaign.college_types,
            "target_departments": campaign.departments,
        },
        "college": college,
    }

    # Quoted from the college's own website. Named separately so the model can
    # tell verified evidence from roster metadata.
    evidence = lead.get("evidence")
    if evidence:
        state["website_evidence"] = evidence

    if lead.get("signals"):
        state["signals"] = lead["signals"]

    return state


def lead_for(state: dict[str, Any]) -> dict[str, Any]:
    """The college facts, for code that needs the name back out of a state."""
    return state.get("college", {})
