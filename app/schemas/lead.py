from typing import Optional

from pydantic import BaseModel

# Set by the scoring agent, then by persistence.
STATUS_SCORED = "scored"      # Jev answered; above threshold, not yet written
STATUS_SKIPPED = "skipped"    # below threshold or rejected -- deliberately not written
STATUS_PERSISTED = "persisted"  # rows exist in colleges/contacts/opportunities
STATUS_FAILED = "failed"      # scoring or persistence raised
# Enrichment found nothing, so the score rests on the roster row alone. Such a
# judgement has been seen to land anywhere from 41 to 99 for comparable
# colleges, so it is not trusted to auto-qualify.
STATUS_NEEDS_EVIDENCE = "needs_evidence"


class LeadRead(BaseModel):
    id: int
    college_name: str
    contact_name: Optional[str] = None
    contact_role: Optional[str] = None
    email: Optional[str] = None
    fit_label: Optional[str] = None
    fit_score: float = 0.0
    rationale: Optional[str] = None
    source_campaign_id: str
    status: str

    # Populated once the lead reaches Postgres.
    college_id: Optional[str] = None
    opportunity_id: Optional[str] = None
    error: Optional[str] = None
    # False when enrichment returned nothing for this college.
    has_evidence: bool = True
