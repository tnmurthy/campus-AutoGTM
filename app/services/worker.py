"""Executes queued campaign runs, one at a time.

A run crawls each candidate college before scoring it, and polite crawling is
slow: a forty-college sweep is roughly twenty minutes of mostly waiting. That
cannot live inside an HTTP request, so the request queues a run and this
claims it.

Deliberately a plain loop rather than a task framework. One worker, polling a
table, is enough for this volume, and it keeps the operational surface to a
process that can be restarted without ceremony.
"""

import logging
import socket
import threading
import time
from typing import Any

from app.schemas.campaign import CampaignRead
from app.schemas.lead import (
    STATUS_FAILED,
    STATUS_NEEDS_EVIDENCE,
    STATUS_PERSISTED,
    STATUS_SCORED,
    STATUS_SKIPPED,
)
from app.services import crm_client
from app.services.orchestrator import run_campaign

logger = logging.getLogger(__name__)

POLL_SECONDS = 5.0
HEARTBEAT_SECONDS = 30.0
STALE_AFTER = "10 minutes"


def worker_name() -> str:
    """Identifies which process holds a run, for when one stops reporting."""
    return f"{socket.gethostname()}:{threading.get_ident()}"


class _Heartbeat:
    """Reports liveness while a run is in progress.

    A separate thread rather than a callback threaded through the pipeline:
    the crawl blocks inside requests, so there is no convenient moment to call
    back from, and the point is to distinguish slow from dead.
    """

    def __init__(self, crm: Any, run_id: str, every: float = HEARTBEAT_SECONDS):
        self._crm = crm
        self._run_id = run_id
        self._every = every
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> "_Heartbeat":
        self._thread = threading.Thread(target=self._beat, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *_exc: object) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)

    def _beat(self) -> None:
        while not self._stop.wait(self._every):
            try:
                self._crm.run_heartbeat(self._run_id)
            except Exception as exc:  # noqa: BLE001 - a missed beat is not fatal
                logger.warning("heartbeat failed for run %s: %s", self._run_id, exc)


def _counts(leads: list[Any], jev_calls: int) -> dict[str, int]:
    status_of = [lead.status for lead in leads]
    return {
        "leads_found": len(leads),
        "leads_scored": sum(1 for s in status_of if s in (STATUS_SCORED, STATUS_PERSISTED)),
        "leads_persisted": status_of.count(STATUS_PERSISTED),
        "leads_skipped": sum(
            1 for s in status_of if s in (STATUS_SKIPPED, STATUS_NEEDS_EVIDENCE)
        ),
        "leads_failed": status_of.count(STATUS_FAILED),
        "jev_calls": jev_calls,
    }


def execute_run(run: dict[str, Any], crm: Any = None) -> dict[str, int]:
    """Run one claimed campaign run to completion and record the outcome."""
    client = crm if crm is not None else crm_client
    run_id = str(run["id"])

    rows = client.campaign_fetch(str(run["campaign_id"]))
    if not rows:
        client.run_finish(run_id, "failed", {}, "campaign no longer exists")
        raise RuntimeError(f"run {run_id} references a missing campaign")

    campaign = CampaignRead.from_row(rows[0])
    stats: dict[str, int] = {"jev_calls": 0}

    try:
        with _Heartbeat(client, run_id):
            leads = run_campaign(campaign, crm=client, stats=stats)
    except Exception as exc:  # noqa: BLE001 - the run fails, the worker does not
        logger.exception("run %s failed", run_id)
        client.run_finish(run_id, "failed", {"jev_calls": stats["jev_calls"]}, str(exc)[:500])
        raise

    counts = _counts(leads, stats["jev_calls"])
    client.run_finish(run_id, "succeeded", counts)
    logger.info("run %s finished: %s", run_id, counts)
    return counts


def run_once(crm: Any = None) -> dict[str, Any] | None:
    """Claim and execute one run. Returns None when the queue is empty."""
    client = crm if crm is not None else crm_client
    run = client.run_claim(worker_name(), STALE_AFTER)
    if run is None:
        return None

    try:
        counts = execute_run(run, crm=client)
    except Exception:  # noqa: BLE001 - already recorded against the run
        return {"id": run["id"], "status": "failed"}
    return {"id": run["id"], "status": "succeeded", **counts}


def serve(poll_seconds: float = POLL_SECONDS, max_iterations: int | None = None) -> None:
    """Poll until stopped. `max_iterations` bounds it for tests."""
    logger.info("worker %s polling every %ss", worker_name(), poll_seconds)
    iterations = 0
    while max_iterations is None or iterations < max_iterations:
        iterations += 1
        try:
            if run_once() is None:
                time.sleep(poll_seconds)
        except Exception as exc:  # noqa: BLE001 - a bad run must not end the worker
            logger.exception("worker loop error: %s", exc)
            time.sleep(poll_seconds)


if __name__ == "__main__":  # pragma: no cover - operational entry point
    from app.bootstrap import load_env

    load_env()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    serve()
