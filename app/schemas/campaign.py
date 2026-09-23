from pydantic import BaseModel
from typing import List, Optional

class CampaignBase(BaseModel):
    name: str
    segment_states: List[str]
    college_types: List[str]
    departments: List[str]
    objective: str
    target_meetings_per_week: int

class CampaignCreate(CampaignBase):
    config_path: Optional[str] = None

class CampaignRead(CampaignBase):
    id: int
