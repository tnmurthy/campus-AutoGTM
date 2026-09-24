"""Colleges from a data.gov.in resource.

Uses the documented, key-authenticated resource API rather than scraping the
AICTE dashboard. That dashboard is an AngularJS front end over undocumented
internal endpoints with no published contract and no robots policy; building
on it would mean a scraper that breaks silently whenever they redeploy.

Set PROSPECTOR_SOURCE=datagov with DATAGOV_RESOURCE_ID and DATAGOV_API_KEY.
"""

import time
from typing import Any, Iterator

import requests

from agents.sources.base import normalise

BASE_URL = "https://api.data.gov.in/resource"
PAGE_SIZE = 100
MAX_PAGES = 100
TIMEOUT_SECONDS = 30.0
RETRY_STATUS = frozenset({429, 500, 502, 503, 504})
MAX_ATTEMPTS = 3


class SourceError(RuntimeError):
    """The upstream dataset could not be read."""


class DataGovSource:
    def __init__(self, resource_id: str, api_key: str, filters: dict[str, str] | None = None):
        self.resource_id = resource_id
        self.api_key = api_key
        self.filters = filters or {}

    def fetch(self) -> Iterator[dict[str, Any]]:
        offset = 0
        for _ in range(MAX_PAGES):
            records = self._page(offset)
            if not records:
                return
            for record in records:
                lead = normalise(self._remap(record))
                if lead is not None:
                    yield lead
            if len(records) < PAGE_SIZE:
                return
            offset += PAGE_SIZE

    def _page(self, offset: int) -> list[dict[str, Any]]:
        params = {
            "api-key": self.api_key,
            "format": "json",
            "limit": PAGE_SIZE,
            "offset": offset,
            **{f"filters[{k}]": v for k, v in self.filters.items()},
        }

        last_error: Exception | None = None
        for attempt in range(1, MAX_ATTEMPTS + 1):
            try:
                resp = requests.get(
                    f"{BASE_URL}/{self.resource_id}", params=params, timeout=TIMEOUT_SECONDS
                )
            except requests.RequestException as exc:
                last_error = exc
            else:
                if resp.status_code not in RETRY_STATUS:
                    if resp.status_code >= 400:
                        # The key travels in the query string, so the URL is
                        # never echoed into the error.
                        raise SourceError(
                            f"data.gov.in returned {resp.status_code} for resource "
                            f"{self.resource_id}"
                        )
                    return self._records(resp)
                last_error = SourceError(f"data.gov.in returned {resp.status_code}")

            if attempt < MAX_ATTEMPTS:
                time.sleep(0.5 * 2 ** (attempt - 1))

        raise SourceError(f"data.gov.in unreachable after {MAX_ATTEMPTS} attempts: {last_error}")

    @staticmethod
    def _records(resp: Any) -> list[dict[str, Any]]:
        try:
            body = resp.json()
        except ValueError as exc:
            raise SourceError("data.gov.in returned a non-JSON body") from exc
        records = body.get("records") if isinstance(body, dict) else None
        if not isinstance(records, list):
            raise SourceError("data.gov.in response has no records array")
        return [r for r in records if isinstance(r, dict)]

    @staticmethod
    def _remap(record: dict[str, Any]) -> dict[str, Any]:
        # Field names vary per dataset; the common AICTE/AISHE spellings are
        # tried in order and the first present one wins.
        def pick(*names: str) -> Any:
            for name in names:
                if record.get(name) not in (None, ""):
                    return record[name]
            return None

        return {
            "college_name": pick("institution_name", "college_name", "name", "institute_name"),
            "college_type": pick("institution_type", "college_type", "type", "category"),
            "city": pick("city", "district", "location"),
            "state": pick("state", "state_name"),
            "website": pick("website", "url"),
            "departments": pick("programmes", "programs", "courses", "departments"),
        }
