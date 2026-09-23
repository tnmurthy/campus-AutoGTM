from pydantic import BaseModel
from typing import Optional

class LeadRead(BaseModel):
    id: int
    college_name: str
    contact_name: Optional[str]
    contact_role: Optional[str]
    email: Optional[str]
    fit_label: Optional[str]
    fit_score: float
    source_campaign_id: int
    status: str
