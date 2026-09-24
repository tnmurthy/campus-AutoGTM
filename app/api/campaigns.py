from fastapi import APIRouter, HTTPException

from app.api.leads import add_leads
from app.schemas.campaign import OPPORTUNITY_TYPES, CampaignCreate, CampaignRead
from app.schemas.lead import LeadRead
from app.services.orchestrator import run_campaign

router = APIRouter()

# In-process store. Campaigns do not survive a restart and are not shared
# between workers -- acceptable while a run is driven by hand, and the reason
# to run this with a single uvicorn worker until campaigns get their own table.
_campaigns_db: list[CampaignRead] = []
_campaign_id_counter = 1


@router.post("/", response_model=CampaignRead)
async def create_campaign(payload: CampaignCreate):
    global _campaign_id_counter

    if payload.opportunity_type not in OPPORTUNITY_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"opportunity_type must be one of {', '.join(OPPORTUNITY_TYPES)}; "
                f"got {payload.opportunity_type!r}"
            ),
        )

    campaign = CampaignRead(id=_campaign_id_counter, **payload.model_dump(exclude={"config_path"}))
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

    # run_campaign is blocking: it makes one synchronous Jev call per lead.
    # Off the event loop, or a run of any size stalls every other request.
    from starlette.concurrency import run_in_threadpool

    leads = await run_in_threadpool(run_campaign, campaign)
    add_leads(leads)
    return leads
