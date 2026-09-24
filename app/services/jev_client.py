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


def answers(body: dict[str, Any]) -> dict[str, Any]:
    """The `answers` map from a response envelope.

    The API returns {"model": ..., "answers": {...}, "usage": {...}}; the
    judgements are nested, not top level.
    """
    slot = body.get("answers")
    if not isinstance(slot, dict):
        raise JevError("Jev response has no answers object")
    return slot


def value(answers_map: dict[str, Any], key: str, primitive: str) -> Any:
    """One judgement, read under its primitive's own field name.

    Each primitive names its result after itself -- a choice answer carries
    `choice`, a score `score`, a noul `noul`. Indexing inline turns any
    upstream change into a bare KeyError with no indication of what moved.
    """
    slot = answers_map.get(key)
    if not isinstance(slot, dict):
        raise JevError(f"Jev returned no {key!r} answer")
    if primitive not in slot:
        raise JevError(
            f"Jev {key!r} answer has no {primitive!r} field "
            f"(got {', '.join(sorted(slot)) or 'nothing'})"
        )
    return slot[primitive]
