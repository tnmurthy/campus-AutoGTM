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
DEFAULT_CRM_ROLE = "autogtm_writer"
DEFAULT_CRM_TOKEN_TTL = 300


class ConfigError(RuntimeError):
    """A required setting is absent. Raised on use, never on import."""


@dataclass(frozen=True)
class Settings:
    jev_api_url: str
    jev_api_key: str | None
    jev_timeout_seconds: float
    jev_max_attempts: int
    supabase_url: str | None
    supabase_anon_key: str | None
    supabase_jwt_secret: str | None
    crm_role: str
    crm_token_ttl_seconds: int
    min_fit_score: float

    def require_jev(self) -> str:
        if not self.jev_api_key:
            raise ConfigError("TYPESAFE_API_KEY is not set")
        return self.jev_api_key

    def require_crm(self) -> tuple[str, str, str]:
        """URL, anon key and JWT secret, or explain what is missing.

        Deliberately not the service role key. That credential bypasses row
        level security on every table; this service needs exactly two
        functions. It signs a short-lived token for the autogtm_writer role
        instead, which can reach nothing else.
        """
        missing = [
            name
            for name, value in (
                ("SUPABASE_URL", self.supabase_url),
                ("SUPABASE_ANON_KEY", self.supabase_anon_key),
                ("SUPABASE_JWT_SECRET", self.supabase_jwt_secret),
            )
            if not value
        ]
        if missing:
            raise ConfigError(
                f"{', '.join(missing)} must be set to persist leads",
            )
        return (
            self.supabase_url,  # type: ignore[return-value]
            self.supabase_anon_key,  # type: ignore[return-value]
            self.supabase_jwt_secret,  # type: ignore[return-value]
        )

    @property
    def persistence_enabled(self) -> bool:
        return bool(
            self.supabase_url and self.supabase_anon_key and self.supabase_jwt_secret
        )


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
        supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY"),
        supabase_jwt_secret=os.environ.get("SUPABASE_JWT_SECRET"),
        crm_role=os.environ.get("CRM_ROLE", DEFAULT_CRM_ROLE),
        crm_token_ttl_seconds=_int("CRM_TOKEN_TTL_SECONDS", DEFAULT_CRM_TOKEN_TTL),
        min_fit_score=_float("MIN_FIT_SCORE", DEFAULT_MIN_FIT_SCORE),
    )
