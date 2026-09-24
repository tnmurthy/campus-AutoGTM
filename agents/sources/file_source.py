"""Colleges from a local CSV or JSON roster.

This is the source that works today: point it at an AICTE export, a state
directory, or a hand-curated roster. Column names are mapped case- and
separator-insensitively, so a file using `Name`, `name` or `College_Name` all
land on the same field without editing the file first.
"""

import csv
import json
from pathlib import Path
from typing import Any, Iterator

from agents.sources.base import normalise

# Source column -> pipeline field. Keys are compared after lowercasing and
# stripping separators, so "College_Type" matches "collegetype".
COLUMN_ALIASES = {
    "name": "college_name",
    "collegename": "college_name",
    "institutionname": "college_name",
    "institution": "college_name",
    "collegetype": "college_type",
    "type": "college_type",
    "institutiontype": "college_type",
    "city": "city",
    "district": "city",
    "state": "state",
    "segment": "segment",
    "tier": "segment",
    "website": "website",
    "url": "website",
    "departments": "departments",
    "programmes": "departments",
    "programs": "departments",
    "courses": "departments",
    "notes": "notes",
    "description": "notes",
    "signals": "signals",
    "contactname": "contact_name",
    "contactrole": "contact_role",
    "email": "email",
}


def _canonical(column: str) -> str | None:
    key = "".join(ch for ch in column.lower() if ch.isalnum())
    return COLUMN_ALIASES.get(key)


def _remap(row: dict[str, Any]) -> dict[str, Any]:
    mapped: dict[str, Any] = {}
    for column, value in row.items():
        if column is None:
            continue
        field = _canonical(str(column))
        if field and mapped.get(field) in (None, ""):
            mapped[field] = value
    return mapped


class FileSource:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    def fetch(self) -> Iterator[dict[str, Any]]:
        if not self.path.exists():
            raise FileNotFoundError(f"prospector roster not found: {self.path}")

        rows = self._read_json() if self.path.suffix.lower() == ".json" else self._read_csv()
        for row in rows:
            lead = normalise(_remap(row))
            if lead is not None:
                yield lead

    def _read_csv(self) -> Iterator[dict[str, Any]]:
        with self.path.open(newline="", encoding="utf-8-sig") as handle:
            yield from csv.DictReader(handle)

    def _read_json(self) -> Iterator[dict[str, Any]]:
        payload = json.loads(self.path.read_text(encoding="utf-8"))
        # Accept either a bare array or the common {"records": [...]} envelope.
        records = payload.get("records", []) if isinstance(payload, dict) else payload
        if not isinstance(records, list):
            raise ValueError(f"{self.path} does not contain a list of records")
        yield from (r for r in records if isinstance(r, dict))
