from app.schemas.lead import LeadRead
from app.services.jev_client import call_jev


def score_lead_with_jev(state: dict, campaign_id: int, lead_id: int) -> LeadRead:
    questions = {
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
    }
    decision = call_jev(state, questions)
    fit_label = decision["fit_label"]["value"]
    fit_score = float(decision["fit_score"]["value"])
    send_now = decision["send_now"]["value"]
    status = "discovered" if send_now and fit_label != "reject" else "skipped"
    lead_state = state["lead"]
    return LeadRead(
        id=lead_id,
        college_name=lead_state["college_name"],
        contact_name=lead_state.get("contact_name"),
        contact_role=lead_state.get("contact_role"),
        email=lead_state.get("email"),
        fit_label=fit_label,
        fit_score=fit_score,
        source_campaign_id=campaign_id,
        status=status,
    )
