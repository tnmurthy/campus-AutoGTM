"""Shared shape for every college source.

A source's only job is to yield raw institution records. Filtering against the
campaign, deduplication and scoring all happen downstream, so a new source is
a single function returning dicts -- nothing else has to change.
"""

from typing import Any, Iterable, Protocol

# The keys the rest of the pipeline reads. A source may emit more; anything
# outside this set is ignored rather than rejected, so an upstream schema that
# grows a column does not break ingest.
LEAD_FIELDS = (
    "college_name",
    "college_type",
    "city",
    "state",
    "website",
    "departments",
    "signals",
    "contact_name",
    "contact_role",
    "email",
)


class Source(Protocol):
    def fetch(self) -> Iterable[dict[str, Any]]: ...


def normalise(record: dict[str, Any]) -> dict[str, Any] | None:
    """Coerce a source record into the pipeline's lead shape.

    Returns None for a record with no usable institution name: a nameless
    college cannot be deduplicated or written, so it is dropped here rather
    than failing later inside a transaction.
    """
    name = _clean(record.get("college_name"))
    if not name:
        return None

    lead: dict[str, Any] = {
        "college_name": name,
        "college_type": _clean(record.get("college_type")),
        "city": _clean(record.get("city")),
        "state": _clean(record.get("state")),
        "website": _clean(record.get("website")),
        "departments": _as_list(record.get("departments")),
        "signals": _as_list(record.get("signals")),
        "contact_name": _clean(record.get("contact_name")),
        "contact_role": _clean(record.get("contact_role")),
        "email": _clean(record.get("email")),
    }
    # `type` is what icp_agent and the ingest payload read.
    lead["type"] = lead["college_type"]
    return lead


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(v).strip() for v in value if str(v).strip()]
    # Sources commonly pack these into one delimited cell.
    return [part.strip() for part in str(value).replace("|", ",").split(",") if part.strip()]
