"""A stand-in for the BrainOpsHub RPC surface.

Mirrors the guarantees ingest_lead actually provides -- idempotent on
(campaign_ref, external_key), all-or-nothing per batch -- so the pipeline can
be tested without a database. The database's own contract is verified against
real Postgres in BrainOpsHub's web/tests/ingest.test.ts.
"""

from typing import Any


class FakeCrm:
    def __init__(self, fail_ingest: bool = False, fail_preflight: bool = False):
        self.ledger: dict[tuple[str, str], dict[str, Any]] = {}
        self.colleges: dict[str, str] = {}
        self.ingest_calls: list[list[dict[str, Any]]] = []
        self.preflight_calls: list[dict[str, Any]] = []
        self.fail_ingest = fail_ingest
        self.fail_preflight = fail_preflight

    def preflight(
        self, campaign_ref: str, external_keys: list[str], college_names: list[str]
    ) -> dict[str, Any]:
        if self.fail_preflight:
            raise RuntimeError("simulated preflight failure")
        self.preflight_calls.append(
            {"campaign_ref": campaign_ref, "external_keys": list(external_keys)}
        )
        return {
            "campaign_ref": campaign_ref,
            "known_keys": [k for k in external_keys if (campaign_ref, k) in self.ledger],
            "known_colleges": [
                n.strip().lower()
                for n in college_names
                if n.strip().lower() in self.colleges
            ],
        }

    def ingest(self, leads: list[dict[str, Any]]) -> list[dict[str, Any]]:
        if self.fail_ingest:
            raise RuntimeError("simulated ingest failure")
        self.ingest_calls.append(list(leads))

        # Validate the whole batch first: the real function is atomic, so a
        # bad lead must leave nothing behind.
        for lead in leads:
            if lead.get("opportunity_type") not in (
                "hackathon",
                "training",
                "internship",
                "seminar",
            ):
                raise RuntimeError(
                    f"invalid input value for enum opportunity_type: "
                    f"{lead.get('opportunity_type')!r}"
                )

        results = []
        for lead in leads:
            slot = (lead["campaign_ref"], lead["external_key"])
            if slot in self.ledger:
                results.append({**self.ledger[slot], "created": False})
                continue

            name_key = str(lead["college_name"]).strip().lower()
            college_created = name_key not in self.colleges
            if college_created:
                self.colleges[name_key] = f"college-{len(self.colleges) + 1}"

            row = {
                "external_key": lead["external_key"],
                "college_id": self.colleges[name_key],
                "opportunity_id": f"opportunity-{len(self.ledger) + 1}",
            }
            self.ledger[slot] = row
            results.append({**row, "college_created": college_created, "created": True})
        return results
