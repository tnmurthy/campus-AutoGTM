from fastapi import APIRouter, HTTPException

from app.api.leads import add_leads
from app.config import ConfigError, get_settings
from app.schemas.campaign import OPPORTUNITY_TYPES, CampaignCreate, CampaignRead
from app.schemas.lead import LeadRead
from app.services import crm_client
from app.services.orchestrator import run_campaign

router = APIRouter()

# Campaigns used to live in a module-level list. They vanished on restart and
# were invisible to anyone but this process, so a campaign could not survive a
# deploy, be resumed after a crash, or be seen by the ops team whose pipeline
# it fills. They are rows in `campaigns` now, reached through the same two-
# function pattern as ingest: autogtm_writer holds no table grants.


def _require_crm() -> None:
    """Campaigns need the database. Say so plainly rather than half-working."""
    if not get_settings().persistence_enabled:
        raise HTTPException(
            status_code=503,
            detail=(
                "Campaigns are stored in BrainOpsHub. Set SUPABASE_URL, "
                "SUPABASE_ANON_KEY and SUPABASE_JWT_SECRET to use them."
            ),
        )


@router.post("/", response_model=CampaignRead)
async def create_campaign(payload: CampaignCreate):
    _require_crm()

    if payload.opportunity_type not in OPPORTUNITY_TYPES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"opportunity_type must be one of {', '.join(OPPORTUNITY_TYPES)}; "
                f"got {payload.opportunity_type!r}"
            ),
        )

    body = payload.model_dump(exclude={"config_path"})
    try:
        row = crm_client.campaign_upsert(body)
    except ConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - surfaced, not swallowed
        raise HTTPException(status_code=502, detail=f"Could not save campaign: {exc}") from exc

    return CampaignRead.from_row(row)


@router.get("/", response_model=list[CampaignRead])
async def list_campaigns():
    _require_crm()
    try:
        rows = crm_client.campaign_fetch()
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not read campaigns: {exc}") from exc
    return [CampaignRead.from_row(r) for r in rows]


@router.post("/{campaign_id}/run", response_model=list[LeadRead])
async def run_campaign_endpoint(campaign_id: str):
    _require_crm()

    try:
        rows = crm_client.campaign_fetch(campaign_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not read campaign: {exc}") from exc

    if not rows:
        raise HTTPException(status_code=404, detail="Campaign not found")

    campaign = CampaignRead.from_row(rows[0])
    if not campaign.is_active:
        raise HTTPException(status_code=409, detail="That campaign is not active")

    # run_campaign is blocking: it crawls and makes one synchronous Jev call
    # per lead. Off the event loop, or a run of any size stalls every other
    # request. A queue is the real answer once runs get long.
    from starlette.concurrency import run_in_threadpool

    leads = await run_in_threadpool(run_campaign, campaign)
    add_leads(leads)
    return leads
