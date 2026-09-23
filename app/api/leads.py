from fastapi import APIRouter
from app.schemas.lead import LeadRead

router = APIRouter()

_leads_db: list[LeadRead] = []

@router.get("/", response_model=list[LeadRead])
async def list_leads():
    return _leads_db

def add_leads(leads: list[LeadRead]) -> None:
    _leads_db.extend(leads)
