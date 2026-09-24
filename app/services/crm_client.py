"""Calls the two BrainOpsHub functions this service is allowed to reach.

There is no Supabase SDK here and no service role key. The agent signs a
short-lived token for the `autogtm_writer` role and posts to PostgREST's RPC
endpoint; that role holds execute on ingest_lead and ingest_preflight and no
table grants whatsoever, so a bug in this process cannot touch payouts,
contacts or anything else.

Schema knowledge lives in the database function, not here. This module only
knows two function names and how to authenticate.
"""

import time
from typing import Any

import jwt
import requests

from app.config import get_settings

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
BACKOFF_BASE_SECONDS = 0.5
MAX_ATTEMPTS = 3
TIMEOUT_SECONDS = 30.0


class CrmError(RuntimeError):
    """The CRM call failed or returned something unusable."""


def _scoped_token(secret: str, role: str, ttl: int) -> str:
    now = int(time.time())
    return jwt.encode(
        {"role": role, "iat": now, "exp": now + ttl},
        secret,
        algorithm="HS256",
    )


def _rpc(name: str, payload: dict[str, Any] | list[Any]) -> Any:
    settings = get_settings()
    url, anon_key, jwt_secret = settings.require_crm()
    token = _scoped_token(jwt_secret, settings.crm_role, settings.crm_token_ttl_seconds)

    endpoint = f"{url.rstrip('/')}/rest/v1/rpc/{name}"
    body = {"payload": payload}

    last_error: Exception | None = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            resp = requests.post(
                endpoint,
                headers={
                    "apikey": anon_key,
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=TIMEOUT_SECONDS,
            )
        except requests.RequestException as exc:
            last_error = exc
        else:
            if resp.status_code not in RETRY_STATUS:
                if resp.status_code >= 400:
                    # Surfaced verbatim: these are our own function's
                    # validation messages, not user data.
                    raise CrmError(f"{name} failed with {resp.status_code}: {resp.text[:400]}")
                try:
                    return resp.json()
                except ValueError as exc:
                    raise CrmError(f"{name} returned a non-JSON body") from exc
            last_error = CrmError(f"{name} returned {resp.status_code}")

        if attempt < MAX_ATTEMPTS:
            time.sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))

    raise CrmError(f"{name} unreachable after {MAX_ATTEMPTS} attempts: {last_error}")


def preflight(campaign_ref: str, external_keys: list[str], college_names: list[str]) -> dict[str, Any]:
    """Which leads the CRM has already seen, so they need not be scored."""
    result = _rpc(
        "ingest_preflight",
        {
            "campaign_ref": campaign_ref,
            "external_keys": external_keys,
            "college_names": college_names,
        },
    )
    if not isinstance(result, dict):
        raise CrmError(f"ingest_preflight returned {type(result).__name__}, expected an object")
    return result


def ingest(leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Write a batch. Atomic per lead, idempotent on (campaign_ref, external_key)."""
    if not leads:
        return []
    result = _rpc("ingest_lead", leads)
    if not isinstance(result, list):
        raise CrmError(f"ingest_lead returned {type(result).__name__}, expected an array")
    return result
