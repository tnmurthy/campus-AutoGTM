import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings  # noqa: E402


@pytest.fixture(autouse=True)
def clean_settings(monkeypatch):
    """Settings are cached for the process; each test gets its own view."""
    for key in (
        "TYPESAFE_API_KEY", "JEV_API_URL", "JEV_TIMEOUT_SECONDS", "JEV_MAX_ATTEMPTS",
        "SUPABASE_URL", "SUPABASE_ANON_KEY", "SUPABASE_JWT_SECRET",
        "CRM_ROLE", "CRM_TOKEN_TTL_SECONDS", "MIN_FIT_SCORE",
    ):
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()
