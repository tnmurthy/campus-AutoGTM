from app.schemas.campaign import CampaignRead


def build_state_from_campaign_and_lead(campaign: CampaignRead, lead: dict) -> dict:
    return {
        "campaign": {
            "name": campaign.name,
            "objective": campaign.objective,
            "states": campaign.segment_states,
            "college_types": campaign.college_types,
            "departments": campaign.departments,
        },
        "lead": lead,
    }
