"""Attaches website evidence to a lead before it is scored.

Runs after preflight, never before: a college already ingested for this
campaign is skipped, so it is neither crawled nor scored. Enrichment is the
expensive stage in wall-clock terms and the only one that touches someone
else's servers, so it happens to the smallest possible set of leads.

Any failure returns the lead unchanged. A slow or blocked site must cost the
campaign a weaker score, never the run.
"""

import logging
from pathlib import Path
from typing import Any

from agents.enrichment import evidence as ev
from agents.enrichment.fetcher import Fetcher

logger = logging.getLogger(__name__)


def enrich_lead(lead: dict[str, Any], fetcher: Fetcher, max_pages: int = 4) -> dict[str, Any]:
    website = (lead.get("website") or "").strip()
    if not website:
        return lead
    if not website.startswith(("http://", "https://")):
        website = f"https://{website}"

    home = fetcher.get(website)
    if home is None:
        logger.info("no homepage for %s", lead.get("college_name"))
        return lead

    found = ev.Evidence()
    try:
        text = ev.page_text(home.html)
        ev.merge(found, text, home.url)

        for url in ev.candidate_links(home.html, home.url, limit=max_pages - 1):
            page = fetcher.get(url)
            if page is None:
                continue
            ev.merge(found, ev.page_text(page.html), page.url)
    except Exception as exc:  # noqa: BLE001 - malformed markup must not end the run
        logger.warning("could not read %s: %s", website, exc)

    if found.is_empty:
        return lead

    # A new dict: the caller's lead is not mutated.
    enriched = dict(lead)
    enriched["evidence"] = found.excerpts
    enriched["pages_read"] = found.pages_read
    if found.departments and not enriched.get("departments"):
        enriched["departments"] = found.departments
    return enriched


def enrich_all(
    leads: list[dict[str, Any]], cache_dir: str | Path, timeout: float, max_pages: int
) -> list[dict[str, Any]]:
    fetcher = Fetcher(Path(cache_dir), timeout=timeout)
    enriched: list[dict[str, Any]] = []
    for lead in leads:
        try:
            enriched.append(enrich_lead(lead, fetcher, max_pages=max_pages))
        except Exception as exc:  # noqa: BLE001
            logger.warning("enrichment failed for %s: %s", lead.get("college_name"), exc)
            enriched.append(lead)
    return enriched
