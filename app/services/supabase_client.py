"""Supabase access for the GTM engine.

This process writes with the SERVICE ROLE key, which bypasses row level
security entirely. That is deliberate -- AutoGTM is an unattended ingest with
no end user to scope rows to -- and it is why the key must never reach a
browser, a log line, or this repository (which is public).
"""

from functools import lru_cache
from typing import Protocol

from app.config import get_settings


class SupabaseLike(Protocol):
    """The slice of the client the repository actually uses."""

    def table(self, name: str): ...


@lru_cache(maxsize=1)
def get_client() -> SupabaseLike:
    # Imported lazily so the package remains importable -- and /health
    # answerable -- on a host that has no Supabase credentials configured.
    from supabase import create_client

    url, key = get_settings().require_supabase()
    return create_client(url, key)
