"""Discovers candidate colleges for a campaign.

Replaces the stub that returned one hardcoded institution and ignored the
campaign entirely. Discovery is now source-backed and the campaign's targeting
is actually applied: a Telangana engineering sweep no longer sees Andhra degree
colleges.

Sources are selected by PROSPECTOR_SOURCE:

    file     a local CSV or JSON roster -- an AICTE export, a state directory,
             or a curated list. Works offline and is the default.
    datagov  the documented data.gov.in resource API.
    stub     the original single fake lead, kept so the pipeline can be
             demonstrated with nothing configured.

Filtering is deliberately forgiving. Source vocabularies do not match a
campaign's wording -- "Engineering Autonomous" against a campaign asking for
"engineering" -- so matching is substring-based on normalised text. A strict
equality match silently returns nothing, which is the worse failure: it looks
like there are no candidates rather than like the filter is wrong.
"""

import logging
from typing import Any, Iterable

from agents.sources.base import normalise
from app.config import get_settings
from app.schemas.campaign import CampaignRead

logger = logging.getLogger(__name__)

MAX_LEADS_PER_RUN = 200

STUB_LEAD = {
    "college_name": "Example Engineering College",
    "city": "Hyderabad",
    "state": "Telangana",
    "college_type": "Autonomous Engineering College",
    "departments": ["CSE", "ECE", "EEE"],
    "signals": [
        "AICTE-approved",
        "Hosted hackathon in 2025",
        "Active training & placement cell",
    ],
    "contact_name": "Training Coordinator",
    "contact_role": "Coordinator",
    "email": "training@example.edu",
}


def discover_leads(campaign: CampaignRead) -> list[dict[str, Any]]:
    """Candidate colleges matching the campaign, capped and deduplicated."""
    settings = get_settings()

    # The collection loop is inside the guard, not just the source lookup.
    # Sources are generators: a missing file or a dead endpoint raises on the
    # first iteration, which is after any try wrapped only around the lookup.
    try:
        leads = _collect(_source_records(settings), campaign)
    except Exception as exc:  # noqa: BLE001 - a dead source must not kill the run
        logger.error("prospector source unavailable, falling back to stub: %s", exc)
        leads = _collect([normalise(dict(STUB_LEAD))], campaign)

    logger.info("prospector found %s candidates for campaign %s", len(leads), campaign.id)
    return leads


def _collect(
    records: Iterable[dict[str, Any] | None], campaign: CampaignRead
) -> list[dict[str, Any]]:
    seen: set[str] = set()
    leads: list[dict[str, Any]] = []
    for record in records:
        if record is None or not _matches(campaign, record):
            continue
        key = str(record["college_name"]).strip().lower()
        if key in seen:
            continue
        seen.add(key)
        leads.append(record)
        if len(leads) >= MAX_LEADS_PER_RUN:
            logger.info("prospector capped at %s leads", MAX_LEADS_PER_RUN)
            break
    return leads


def _source_records(settings: Any) -> Iterable[dict[str, Any] | None]:
    kind = settings.prospector_source

    if kind == "file":
        from agents.sources.file_source import FileSource

        return FileSource(settings.require_prospector_file()).fetch()

    if kind == "datagov":
        from agents.sources.datagov_source import DataGovSource

        resource_id, api_key = settings.require_datagov()
        return DataGovSource(resource_id, api_key).fetch()

    if kind == "stub":
        return [normalise(dict(STUB_LEAD))]

    raise ValueError(f"unknown PROSPECTOR_SOURCE {kind!r}")


def _matches(campaign: CampaignRead, record: dict[str, Any]) -> bool:
    return (
        _any_match(campaign.segment_states, record.get("state"))
        and _any_match(campaign.college_types, record.get("college_type"))
        and _any_match(campaign.departments, record.get("departments"))
    )


def _any_match(wanted: list[str], value: Any) -> bool:
    """True when the campaign asks for nothing, or any term matches the value.

    Matching is on word sets, not substrings. Source vocabularies and campaign
    wording describe the same institution differently and in a different order
    -- a campaign asking for "Engineering Autonomous" against a college typed
    "Autonomous Engineering College" is the same target, and neither string
    contains the other. A term matches when every one of its words appears in
    the value.

    An empty criterion means "no constraint", not "match nothing": a campaign
    that names no departments should see every college, not none.
    """
    terms = [_words(t) for t in wanted if t and t.strip()]
    terms = [t for t in terms if t]
    if not terms:
        return True

    if isinstance(value, (list, tuple, set)):
        haystack = _words(" ".join(str(v) for v in value))
    else:
        haystack = _words(str(value or ""))

    if not haystack:
        # The source did not populate this field. Excluding the college would
        # hide real candidates because of a gap in someone else's data.
        return True

    return any(term <= haystack for term in terms)


def _words(text: str) -> set[str]:
    """Lowercased alphanumeric words, punctuation and separators discarded."""
    cleaned = "".join(ch if ch.isalnum() else " " for ch in text.lower())
    return {w for w in cleaned.split() if w}
