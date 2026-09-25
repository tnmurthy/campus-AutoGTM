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
    # Lifetime cap on colleges scored for this campaign. None means uncapped.
    # Scoring is what gets billed, so this is where a sweep whose targeting
    # matches far more than intended stops costing money.
    max_jev_calls: Optional[int] = Field(default=None, gt=0)


class CampaignCreate(CampaignBase):
    config_path: Optional[str] = None


class CampaignRead(CampaignBase):
    # A uuid from the campaigns table, not a counter. Campaigns are rows now,
    # so their identity comes from the database rather than from however many
    # happened to be created since the process started.
    id: str
    is_active: bool = True
    # Summed from this campaign's runs by the database, not tracked here.
    jev_calls_used: int = 0

    @classmethod
    def from_row(cls, row: dict) -> "CampaignRead":
        """Build from a campaigns row as campaign_fetch returns it."""
        return cls(
            id=str(row["id"]),
            name=row["name"],
            objective=row.get("objective") or "",
            segment_states=list(row.get("segment_states") or []),
            college_types=list(row.get("college_types") or []),
            departments=list(row.get("departments") or []),
            opportunity_type=row.get("opportunity_type") or "training",
            min_fit_score=float(row.get("min_fit_score") or DEFAULT_MIN_FIT_SCORE),
            target_meetings_per_week=int(row.get("target_meetings_per_week") or 0),
            is_active=bool(row.get("is_active", True)),
            max_jev_calls=row.get("max_jev_calls"),
            jev_calls_used=int(row.get("jev_calls_used") or 0),
        )

    def to_payload(self) -> dict:
        """The shape campaign_upsert expects."""
        return {
            "id": self.id,
            "name": self.name,
            "objective": self.objective,
            "segment_states": self.segment_states,
            "college_types": self.college_types,
            "departments": self.departments,
            "opportunity_type": self.opportunity_type,
            "min_fit_score": self.min_fit_score,
            "target_meetings_per_week": self.target_meetings_per_week,
            "is_active": self.is_active,
            "max_jev_calls": self.max_jev_calls,
        }
