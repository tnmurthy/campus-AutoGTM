from app.schemas.campaign import CampaignRead


def discover_leads(campaign: CampaignRead) -> list[dict]:
    """STUB. Returns one fixed fake lead, ignoring the campaign entirely.

    Real signal discovery (AICTE directory ingest, hackathon and T&P-cell
    signals) is not implemented. Every downstream stage -- scoring, threshold,
    persistence -- is real and runs against whatever this returns, so replacing
    this function is the only work left to make the pipeline live.
    """
    return [
        {
            "college_name": "Example Engineering College",
            "city": "Hyderabad",
            "state": "Telangana",
            "type": "Autonomous Engineering College",
            "departments": ["CSE", "ECE", "EEE"],
            "signals": [
                "AICTE-approved",
                "Hosted hackathon in 2025",
                "Active training & placement cell",
            ],
            "contact_name": "Training Coordinator",
            "contact_role": "Coordinator",
            "email": "training@example.edu",
        }
    ]
