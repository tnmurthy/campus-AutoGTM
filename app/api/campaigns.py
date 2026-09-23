from fastapi import APIRouter, HTTPException
from app.schemas.campaign import CampaignCreate, CampaignRead
from app.schemas.lead import LeadRead
from app.services.orchestrator import run_campaign

router = APIRouter()

_campaigns_db: list[CampaignRead] = []
_campaign_id_counter = 1

@router.post("/", response_model=CampaignRead)
async def create_campaign(payload: CampaignCreate):
    global _campaign_id_counter
    campaign = CampaignRead(id=_campaign_id_counter, **payload.dict())
    _campaigns_db.append(campaign)
    _campaign_id_counter += 1
    return campaign

@router.get("/", response_model=list[CampaignRead])
async def list_campaigns():
    return _campaigns_db

@router.post("/{campaign_id}/run", response_model=list[LeadRead])
async def run_campaign_endpoint(campaign_id: int):
    campaign = next((c for c in _campaigns_db if c.id == campaign_id), None)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    leads = run_campaign(campaign)
    return leads
