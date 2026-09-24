from fastapi import APIRouter

from app.config import get_settings

router = APIRouter()


@router.get("/")
async def health_check():
    """Liveness plus a readiness hint.

    Answers even when nothing is configured -- that distinction is the point:
    a caller must be able to tell a misconfigured service from a dead one.
    Reports whether each credential is present, never any part of its value.
    """
    settings = get_settings()
    return {
        "status": "ok",
        "service": "campus-autogtm",
        "jev_configured": bool(settings.jev_api_key),
        "persistence_enabled": settings.persistence_enabled,
        "crm_role": settings.crm_role,
        "prospector_source": settings.prospector_source,
        "min_fit_score": settings.min_fit_score,
    }
