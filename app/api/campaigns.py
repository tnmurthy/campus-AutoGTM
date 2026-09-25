from fastapi import APIRouter, HTTPException

from app.config import ConfigError, get_settings
from app.schemas.campaign import OPPORTUNITY_TYPES, CampaignCreate, CampaignRead
from app.schemas.run import CampaignRun
from app.services import crm_client

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


@router.post("/{campaign_id}/run", response_model=CampaignRun, status_code=202)
async def run_campaign_endpoint(campaign_id: str):
    """Queue a run. The work happens in the worker, not in this request.

    A run crawls every candidate college before scoring it, and polite
    crawling is slow -- a forty-college sweep is roughly twenty minutes. No
    HTTP request should hold that open, so this returns 202 with a run to poll.
    """
    _require_crm()

    try:
        rows = crm_client.campaign_fetch(campaign_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not read campaign: {exc}") from exc

    if not rows:
        raise HTTPException(status_code=404, detail="Campaign not found")
    if not CampaignRead.from_row(rows[0]).is_active:
        raise HTTPException(status_code=409, detail="That campaign is not active")

    try:
        run = crm_client.run_enqueue(campaign_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not queue the run: {exc}") from exc

    return CampaignRun.from_row(run)


@router.get("/runs/{run_id}", response_model=CampaignRun)
async def get_run(run_id: str):
    _require_crm()
    try:
        run = crm_client.run_fetch(run_id)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=502, detail=f"Could not read the run: {exc}") from exc
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return CampaignRun.from_row(run)
