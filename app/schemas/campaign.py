from typing import List, Optional

from pydantic import BaseModel, Field

from app.config import DEFAULT_MIN_FIT_SCORE

# Mirrors the opportunity_type enum in BrainOpsHub 0001_enums.sql. A value
# outside this set is rejected by Postgres at write time, so it is rejected
# here first, where the error can name the field.
OPPORTUNITY_TYPES = ("hackathon", "training", "internship", "seminar")


class CampaignBase(BaseModel):
    name: str
    segment_states: List[str]
    college_types: List[str]
    departments: List[str]
    objective: str
    target_meetings_per_week: int

    opportunity_type: str = Field(
        default="training",
        description=f"One of {', '.join(OPPORTUNITY_TYPES)}.",
    )
    min_fit_score: float = Field(
        default=DEFAULT_MIN_FIT_SCORE,
        ge=0,
        le=100,
        description="Leads scoring below this are recorded as skipped, not written.",
    )


class CampaignCreate(CampaignBase):
    config_path: Optional[str] = None


class CampaignRead(CampaignBase):
    id: int
