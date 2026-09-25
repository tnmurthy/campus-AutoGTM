from fastapi import FastAPI

# Before any module reads os.environ.
from app.bootstrap import load_env

load_env()

from app.api import health, campaigns  # noqa: E402

app = FastAPI(
    title="Campus AutoGTM",
    version="0.1.0",
    description="Agentic GTM engine for campuses and training providers.",
)

app.include_router(health.router, prefix="/health", tags=["health"])
app.include_router(campaigns.router, prefix="/campaigns", tags=["campaigns"])
