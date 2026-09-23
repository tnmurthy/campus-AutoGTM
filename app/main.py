from fastapi import FastAPI
from app.api import health, campaigns, leads

app = FastAPI(
    title="Campus AutoGTM",
    version="0.1.0",
    description="Agentic GTM engine for campuses and training providers.",
)

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
app.include_router(leads.router, prefix="/leads", tags=["leads"])
