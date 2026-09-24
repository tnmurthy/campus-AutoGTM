"""Writes discovered leads into the BrainOpsHub schema.

Mapping, in one place so the contract is reviewable:

    lead            -> colleges      (one row per institution)
    lead contact    -> contacts      (one row per named person)
    scored lead     -> opportunities (one row per campaign x college)

`probability` carries the Jev fit score directly: both are 0-100 integers, so
the pipeline shows the model's confidence without a second column.
"""

from typing import Any

DEFAULT_STATE = "Telangana"
OPPORTUNITY_STAGE_NEW = "enquiry"


def _first(response: Any) -> dict[str, Any] | None:
    data = getattr(response, "data", None)
    if not data:
        return None
    return data[0]


def find_college_by_name(client, name: str) -> dict[str, Any] | None:
    response = (
        client.table("colleges").select("id, name").eq("name", name).limit(1).execute()
    )
    return _first(response)


def insert_college(client, lead: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "name": lead["college_name"],
        "college_type": lead.get("type"),
        "city": lead.get("city"),
        "state": lead.get("state") or DEFAULT_STATE,
        "notes": _signals_note(lead),
    }
    row = _first(client.table("colleges").insert(payload).execute())
    if row is None:
        raise RepositoryError(f"insert into colleges returned no row for {payload['name']!r}")
    return row


def upsert_college(client, lead: dict[str, Any]) -> dict[str, Any]:
    """Return the existing college of that name, else create one.

    Lookup-then-insert, not a true upsert: `colleges.name` carries no unique
    constraint, so ON CONFLICT has nothing to target. Two concurrent ingests of
    the same institution would therefore produce two rows. Single-worker ingest
    makes that unreachable today; adding `unique (colleges.name)` upstream is
    the real fix and would let this collapse into one statement.
    """
    existing = find_college_by_name(client, lead["college_name"])
    if existing:
        return existing
    return insert_college(client, lead)


def insert_contact(client, college_id: str, lead: dict[str, Any]) -> dict[str, Any] | None:
    full_name = lead.get("contact_name")
    if not full_name:
        return None
    payload = {
        "college_id": college_id,
        "full_name": full_name,
        "contact_role": lead.get("contact_role"),
        "email": lead.get("email"),
    }
    return _first(client.table("contacts").insert(payload).execute())


def insert_opportunity(
    client,
    college_id: str,
    campaign_name: str,
    opportunity_type: str,
    fit_score: float,
    rationale: str | None,
) -> dict[str, Any]:
    payload = {
        "college_id": college_id,
        "name": campaign_name,
        "opportunity_type": opportunity_type,
        "stage": OPPORTUNITY_STAGE_NEW,
        "probability": int(round(fit_score)),
        "notes": rationale,
    }
    row = _first(client.table("opportunities").insert(payload).execute())
    if row is None:
        raise RepositoryError(f"insert into opportunities returned no row for {campaign_name!r}")
    return row


def _signals_note(lead: dict[str, Any]) -> str | None:
    signals = lead.get("signals")
    if not signals:
        return None
    return "Discovery signals: " + "; ".join(str(s) for s in signals)


class RepositoryError(RuntimeError):
    """A write returned success but no row -- treat as a failure, not a no-op."""
