"""Turns a campaign+lead state into a typed Jev judgement.

The question shapes follow the TypeSafe primitive contract:

  choice  criteria is a MAP of option -> what that option means; the answer
          carries `choice` plus a probability distribution.
  score   criteria is an ORDERED LIST of level descriptions; the answer carries
          `score`, a position along those levels, not a 0-100 number.
  noul    a yes/no probability; the answer carries `noul` in 0..1.

There is no free-text primitive, so the CRM rationale is composed in code from
the judgements rather than asked for. Code owns the workflow; the model supplies
the judgement.
"""

from typing import Any

from app.schemas.lead import STATUS_SCORED, STATUS_SKIPPED, LeadRead
from app.services.jev_client import answers, call_jev, value

# Ordered worst -> best. The index of the chosen level is the raw score, so the
# count matters: it defines the scale that gets normalised to 0-100 below.
FIT_LEVELS = [
    "No fit: wrong region, wrong institution type, or no relevant departments.",
    "Weak fit: nominally eligible but little sign of student demand or capacity.",
    "Moderate fit: relevant departments, but no evidence of training or event activity.",
    "Strong fit: relevant departments plus an active training or placement cell.",
    "Excellent fit: large relevant cohort and a track record of hosting events.",
]

SEND_NOW_THRESHOLD = 0.5

# Below this much crawled text the score is not reproducible. In one
# calibration slice, 50 characters of evidence produced the highest score of
# the run (98.8) and 72 characters produced nearly the lowest (49.5), while
# every college above 1,000 characters landed in a tight, sensible band. A
# boolean "has any evidence" gate let both through.
MIN_EVIDENCE_CHARS = 400

QUESTIONS: dict[str, Any] = {
    "fit_label": {
        "type": "choice",
        "instructions": "How well does this college match the campaign's ideal customer profile?",
        "criteria": {
            "strong_fit": "Clearly in the target segment and ready to engage now.",
            "medium_fit": "Plausible target, but something material is missing or unclear.",
            "weak_fit": "Technically eligible, unlikely to convert this campaign.",
            "reject": "Outside the campaign's region, institution type, or departments.",
        },
    },
    "fit_score": {
        "type": "score",
        "instructions": "Rate how strongly this college fits the campaign's ideal customer profile.",
        "criteria": FIT_LEVELS,
    },
    "send_now": {
        "type": "noul",
        "instructions": (
            "Should outreach be sent to this college now, rather than held back "
            "for more research or a later campaign?"
        ),
    },
}


def score_lead_with_jev(
    state: dict[str, Any],
    campaign_id: int,
    lead_id: int,
    min_fit_score: float,
) -> LeadRead:
    result = answers(call_jev(state, QUESTIONS))

    fit_label = value(result, "fit_label", "choice")
    raw_score = float(value(result, "fit_score", "score"))
    send_now_probability = float(value(result, "send_now", "noul"))

    fit_score = _to_percentage(raw_score)
    send_now = send_now_probability >= SEND_NOW_THRESHOLD

    # The threshold is the campaign's, not a constant: a hackathon sweep and a
    # paid-training push do not qualify a college the same way.
    qualifies = send_now and fit_label != "reject" and fit_score >= min_fit_score

    # Whether the judgement rests on crawled evidence or only on the roster row
    # is reported, not acted on: only the caller knows if enrichment was even
    # attempted, and with it switched off every lead would otherwise be held.
    has_evidence = _evidence_volume(state.get("website_evidence")) >= MIN_EVIDENCE_CHARS
    status = STATUS_SCORED if qualifies else STATUS_SKIPPED

    lead = state.get("college") or state.get("lead", {})
    return LeadRead(
        id=lead_id,
        college_name=lead["college_name"],
        contact_name=lead.get("contact_name"),
        contact_role=lead.get("contact_role"),
        email=lead.get("email"),
        fit_label=fit_label,
        fit_score=fit_score,
        rationale=_rationale(fit_label, fit_score, send_now_probability, has_evidence),
        source_campaign_id=campaign_id,
        status=status,
        has_evidence=has_evidence,
    )


def _evidence_volume(evidence: Any) -> int:
    """Total characters of crawled text backing this judgement."""
    if not isinstance(evidence, dict):
        return 0
    return sum(len(str(x)) for hits in evidence.values() for x in hits)


def _to_percentage(raw: float) -> float:
    """Map a position along FIT_LEVELS onto 0-100.

    A score answer is an index into the levels, so a five-level question tops
    out at 4. The CRM stores this as `probability`, which is 0-100, and the
    campaign threshold is expressed the same way.
    """
    top = len(FIT_LEVELS) - 1
    if top <= 0:
        return 0.0
    return round(max(0.0, min(raw, top)) / top * 100, 1)


def _rationale(fit_label: str, fit_score: float, send_now: float, has_evidence: bool = True) -> str:
    """Composed here because there is no free-text primitive to ask for it."""
    basis = "" if has_evidence else " Insufficient website evidence: judged largely on roster data."
    return (
        f"Jev: {str(fit_label).replace('_', ' ')}, fit {fit_score:.0f}/100, "
        f"send-now confidence {send_now:.0%}.{basis}"
    )
