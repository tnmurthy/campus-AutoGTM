"""Turns a campaign+lead state into a typed Jev judgement."""

from typing import Any

from app.schemas.lead import STATUS_SCORED, STATUS_SKIPPED, LeadRead
from app.services.jev_client import answer, call_jev

QUESTIONS: dict[str, Any] = {
    "fit_label": {
        "type": "choice",
        "options": ["strong_fit", "medium_fit", "weak_fit", "reject"],
        "instructions": "Classify how well this college fits the campaign ICP.",
    },
    "fit_score": {
        "type": "score",
        "min": 0,
        "max": 100,
        "instructions": "Score overall fit from 0 (terrible) to 100 (perfect).",
    },
    "send_now": {
        "type": "choice",
        "options": [True, False],
        "instructions": "Decide whether we should send outreach now for this lead.",
    },
    "rationale": {
        "type": "text",
        "instructions": "One sentence explaining the score, for the CRM record.",
    },
}


def score_lead_with_jev(
    state: dict[str, Any],
    campaign_id: int,
    lead_id: int,
    min_fit_score: float,
) -> LeadRead:
    decision = call_jev(state, QUESTIONS)

    fit_label = answer(decision, "fit_label")
    fit_score = float(answer(decision, "fit_score"))
    send_now = bool(answer(decision, "send_now"))
    rationale = _optional_text(decision, "rationale")

    # The threshold is the campaign's, not a constant: a hackathon sweep and a
    # paid-training push do not qualify a college the same way.
    qualifies = send_now and fit_label != "reject" and fit_score >= min_fit_score

    lead = state["lead"]
    return LeadRead(
        id=lead_id,
        college_name=lead["college_name"],
        contact_name=lead.get("contact_name"),
        contact_role=lead.get("contact_role"),
        email=lead.get("email"),
        fit_label=fit_label,
        fit_score=fit_score,
        rationale=rationale,
        source_campaign_id=campaign_id,
        status=STATUS_SCORED if qualifies else STATUS_SKIPPED,
    )


def _optional_text(decision: dict[str, Any], key: str) -> str | None:
    """Rationale is commentary. A model that omits it must not fail the lead."""
    slot = decision.get(key)
    if isinstance(slot, dict) and slot.get("value") is not None:
        return str(slot["value"])
    return None
