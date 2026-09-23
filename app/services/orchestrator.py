from app.schemas.campaign import CampaignRead
from app.schemas.lead import LeadRead
from app.api.leads import add_leads
from agents.icp_agent import build_state_from_campaign_and_lead
from agents.prospector_agent import discover_leads
from agents.scoring_agent import score_lead_with_jev


def run_campaign(campaign: CampaignRead) -> list[LeadRead]:
    raw_leads = discover_leads(campaign)
    results: list[LeadRead] = []
    for idx, lead in enumerate(raw_leads, start=1):
        state = build_state_from_campaign_and_lead(campaign, lead)
        scored = score_lead_with_jev(state, campaign_id=campaign.id, lead_id=idx)
        if scored.status in ("approved", "discovered"):
            results.append(scored)
    add_leads(results)
    return results
