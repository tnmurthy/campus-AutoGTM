"""A stand-in for the BrainOpsHub RPC surface.

Mirrors the guarantees ingest_lead actually provides -- idempotent on
(campaign_ref, external_key), all-or-nothing per batch -- so the pipeline can
be tested without a database. The database's own contract is verified against
real Postgres in BrainOpsHub's web/tests/ingest.test.ts.
"""

from typing import Any


class FakeCrm:
    def __init__(self, fail_ingest: bool = False, fail_preflight: bool = False):
        self.campaigns: dict[str, dict[str, Any]] = {}
        self.runs: dict[str, dict[str, Any]] = {}
        self.heartbeats: list[str] = []
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

    # -- campaigns ----------------------------------------------------------

    def campaign_upsert(self, campaign: dict[str, Any]) -> dict[str, Any]:
        """Mirrors campaign_upsert, including the validation it performs."""
        # The real function defaults this rather than demanding it. A fake that
        # is stricter than the thing it stands in for fails tests the system
        # would have passed.
        campaign = {**campaign, "opportunity_type": campaign.get("opportunity_type") or "training"}
        if campaign.get("opportunity_type") not in (
            "hackathon",
            "training",
            "internship",
            "seminar",
        ):
            raise RuntimeError(
                f"opportunity_type must be hackathon, training, internship or "
                f"seminar; got {campaign.get('opportunity_type')!r}"
            )
        if not str(campaign.get("name", "")).strip():
            raise RuntimeError("a campaign needs a name")

        campaign_id = campaign.get("id") or f"camp-{len(self.campaigns) + 1}"
        row = {**campaign, "id": campaign_id, "is_active": campaign.get("is_active", True)}
        self.campaigns[campaign_id] = row
        return row

    def campaign_fetch(self, campaign_id: str | None = None) -> list[dict[str, Any]]:
        """One campaign by id, or every active one when id is omitted."""
        if campaign_id is not None:
            row = self.campaigns.get(campaign_id)
            return [self._with_spend(row)] if row else []
        return [
            self._with_spend(r) for r in self.campaigns.values() if r.get("is_active", True)
        ]

    def _with_spend(self, row: dict[str, Any]) -> dict[str, Any]:
        """Spend is summed from the runs, as campaign_jev_calls_used does."""
        used = sum(
            int(run.get("jev_calls") or 0)
            for run in self.runs.values()
            if run["campaign_id"] == row["id"]
        )
        return {**row, "jev_calls_used": used}

    # -- run queue ----------------------------------------------------------

    def run_enqueue(self, campaign_id: str) -> dict[str, Any]:
        """Mirrors campaign_run_enqueue: a live run is returned, not duplicated."""
        for run in self.runs.values():
            if run["campaign_id"] == campaign_id and run["status"] in ("queued", "running"):
                return {**run, "already_queued": True}
        campaign = self.campaigns.get(campaign_id)
        cap = (campaign or {}).get("max_jev_calls")
        if cap is not None:
            used = self._with_spend(campaign)["jev_calls_used"]
            if used >= cap:
                raise RuntimeError(
                    f"campaign {campaign_id} has spent its ceiling of {cap} "
                    f"scored colleges ({used} used)"
                )

        run_id = f"run-{len(self.runs) + 1}"
        run = {
            "id": run_id,
            "campaign_id": campaign_id,
            "status": "queued",
            "attempt": 0,
        }
        self.runs[run_id] = run
        return {**run, "already_queued": False}

    def run_claim(self, worker: str, stale_after: str = "10 minutes") -> dict[str, Any] | None:
        for run in self.runs.values():
            if run["status"] == "queued":
                run.update(status="running", attempt=run["attempt"] + 1, claimed_by=worker)
                return dict(run)
        return None

    def run_heartbeat(self, run_id: str) -> None:
        self.heartbeats.append(run_id)

    def run_finish(
        self, run_id: str, status: str, counts: dict[str, Any], error: str | None = None
    ) -> dict[str, Any]:
        run = self.runs[run_id]
        run.update(status=status, error=error, **counts)
        return dict(run)

    def run_fetch(self, run_id: str) -> dict[str, Any] | None:
        run = self.runs.get(run_id)
        return dict(run) if run else None



# ---------------------------------------------------------------------------
# Jev responses
#
# Defined once. The previous fakes invented a flat {"key": {"value": ...}}
# shape; the real API nests under `answers` and names each result after its
# primitive. Every test passed against the invented shape, so nothing caught
# that the integration could not work. One definition, matching the documented
# contract, is the guard against repeating that.
# ---------------------------------------------------------------------------

FIT_LEVEL_COUNT = 5  # mirrors agents.scoring_agent.FIT_LEVELS


def jev_response(
    fit_label: str = "strong_fit",
    level: float = 4.0,
    send_now: float = 0.9,
) -> dict[str, Any]:
    """A response envelope shaped exactly as docs.typesafe.ai/api documents.

    `level` is a position along the score criteria (0 .. FIT_LEVEL_COUNT-1),
    not a percentage -- that distinction is what the old fakes hid.
    """
    return {
        "model": "jev-1.13.0",
        "answers": {
            "fit_label": {
                "choice": fit_label,
                "probabilities": {fit_label: 0.8},
                "confidence": 0.8,
            },
            "fit_score": {
                "score": level,
                "probabilities": [0.0] * FIT_LEVEL_COUNT,
                "confidence": 0.75,
            },
            "send_now": {"noul": send_now},
        },
        "usage": {"input_tokens": 300, "output_tokens": 20},
    }


def percentage_for(level: float) -> float:
    """What scoring_agent will report for a given score level."""
    return round(level / (FIT_LEVEL_COUNT - 1) * 100, 1)
