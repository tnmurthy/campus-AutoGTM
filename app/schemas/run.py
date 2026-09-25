from typing import Optional

from pydantic import BaseModel


class CampaignRun(BaseModel):
    """A queued or completed campaign run, as campaign_runs records it."""

    id: str
    campaign_id: str
    status: str
    attempt: int = 0
    claimed_by: Optional[str] = None
    queued_at: Optional[str] = None
    started_at: Optional[str] = None
    finished_at: Optional[str] = None

    leads_found: int = 0
    leads_scored: int = 0
    leads_persisted: int = 0
    leads_skipped: int = 0
    leads_failed: int = 0
    jev_calls: int = 0

    error: Optional[str] = None
    # True when the caller asked for a run that was already in flight. A double
    # click is not an error, but the caller should know it did not start a new one.
    already_queued: bool = False

    @classmethod
    def from_row(cls, row: dict) -> "CampaignRun":
        return cls(
            id=str(row["id"]),
            campaign_id=str(row["campaign_id"]),
            status=row["status"],
            attempt=int(row.get("attempt") or 0),
            claimed_by=row.get("claimed_by"),
            queued_at=_text(row.get("queued_at")),
            started_at=_text(row.get("started_at")),
            finished_at=_text(row.get("finished_at")),
            leads_found=int(row.get("leads_found") or 0),
            leads_scored=int(row.get("leads_scored") or 0),
            leads_persisted=int(row.get("leads_persisted") or 0),
            leads_skipped=int(row.get("leads_skipped") or 0),
            leads_failed=int(row.get("leads_failed") or 0),
            jev_calls=int(row.get("jev_calls") or 0),
            error=row.get("error"),
            already_queued=bool(row.get("already_queued", False)),
        )


def _text(value: object) -> Optional[str]:
    return None if value is None else str(value)
