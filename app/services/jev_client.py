"""Client for the Jev System One decision API.

Two behaviours matter here and are not incidental:

1. The key is read at call time, not import time. Raising during import makes
   the whole FastAPI app unimportable, so a missing key takes down /health too
   and the service looks dead rather than misconfigured.
2. Transport failures retry; a malformed answer does not. A 502 is worth
   another attempt, a response whose shape we do not recognise never is.
"""

import time
from typing import Any

import requests

from app.config import get_settings

RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
BACKOFF_BASE_SECONDS = 0.5


class JevError(RuntimeError):
    """The decision could not be obtained or could not be understood."""


def call_jev(state: dict[str, Any], questions: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    api_key = settings.require_jev()
    payload = {"model": "jev-latest", "state": state, "questions": questions}

    last_error: Exception | None = None
    for attempt in range(1, settings.jev_max_attempts + 1):
        try:
            resp = requests.post(
                settings.jev_api_url,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
                timeout=settings.jev_timeout_seconds,
            )
        except requests.RequestException as exc:
            last_error = exc
        else:
            if resp.status_code not in RETRY_STATUS:
                if resp.status_code >= 400:
                    # A 4xx is our fault and will not improve on retry. The
                    # body is not echoed: it can quote the request, which
                    # carries the campaign state.
                    raise JevError(f"Jev rejected the request with {resp.status_code}")
                return _parse(resp)
            last_error = JevError(f"Jev returned {resp.status_code}")

        if attempt < settings.jev_max_attempts:
            time.sleep(BACKOFF_BASE_SECONDS * 2 ** (attempt - 1))

    raise JevError(f"Jev unreachable after {settings.jev_max_attempts} attempts: {last_error}")


def _parse(resp: "requests.Response") -> dict[str, Any]:
    try:
        body = resp.json()
    except ValueError as exc:
        raise JevError("Jev returned a non-JSON body") from exc
    if not isinstance(body, dict):
        raise JevError(f"Jev returned {type(body).__name__}, expected an object")
    return body


def answer(decision: dict[str, Any], key: str) -> Any:
    """Pull one question's value, naming the key when the shape is wrong.

    Indexing the raw response inline turns any upstream change into a bare
    KeyError and a 500 with no indication of which field moved.
    """
    slot = decision.get(key)
    if not isinstance(slot, dict) or "value" not in slot:
        raise JevError(f"Jev response has no usable {key!r} answer")
    return slot["value"]
