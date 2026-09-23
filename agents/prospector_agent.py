from app.schemas.campaign import CampaignRead


def discover_leads(campaign: CampaignRead) -> list[dict]:
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
