"""Runtime configuration, read from the environment exactly once.

Nothing here raises at import time. A missing credential must not stop the
process from starting -- /health has to answer so an orchestrator can tell the
difference between "misconfigured" and "dead".
"""

import os
from dataclasses import dataclass
from functools import lru_cache

DEFAULT_JEV_API_URL = "https://api.typesafe.ai/v1/systemone"
DEFAULT_MIN_FIT_SCORE = 70.0
DEFAULT_JEV_TIMEOUT_SECONDS = 15.0
DEFAULT_JEV_MAX_ATTEMPTS = 3


class ConfigError(RuntimeError):
    """A required setting is absent. Raised on use, never on import."""


@dataclass(frozen=True)
class Settings:
    jev_api_url: str
    jev_api_key: str | None
    jev_timeout_seconds: float
    jev_max_attempts: int
    supabase_url: str | None
    supabase_service_key: str | None
    min_fit_score: float

    def require_jev(self) -> str:
        if not self.jev_api_key:
            raise ConfigError("TYPESAFE_API_KEY is not set")
        return self.jev_api_key

    def require_supabase(self) -> tuple[str, str]:
        if not self.supabase_url or not self.supabase_service_key:
            raise ConfigError(
                "SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY must both be set "
                "to persist leads",
            )
        return self.supabase_url, self.supabase_service_key

    @property
    def persistence_enabled(self) -> bool:
        return bool(self.supabase_url and self.supabase_service_key)


def _float(name: str, fallback: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return fallback
    try:
        return float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc


def _int(name: str, fallback: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return fallback
    try:
        return int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        jev_api_url=os.environ.get("JEV_API_URL", DEFAULT_JEV_API_URL),
        jev_api_key=os.environ.get("TYPESAFE_API_KEY"),
        jev_timeout_seconds=_float("JEV_TIMEOUT_SECONDS", DEFAULT_JEV_TIMEOUT_SECONDS),
        jev_max_attempts=_int("JEV_MAX_ATTEMPTS", DEFAULT_JEV_MAX_ATTEMPTS),
        supabase_url=os.environ.get("SUPABASE_URL"),
        supabase_service_key=os.environ.get("SUPABASE_SERVICE_ROLE_KEY"),
        min_fit_score=_float("MIN_FIT_SCORE", DEFAULT_MIN_FIT_SCORE),
    )
