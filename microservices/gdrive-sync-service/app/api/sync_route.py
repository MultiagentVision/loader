from __future__ import annotations

import logging

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

router = APIRouter(tags=["sync"])
logger = logging.getLogger(__name__)


class SyncRequest(BaseModel):
    drive: str | None = Field(default=None, description="Optional drive name; omit to sync all drives")


@router.post("/sync", status_code=status.HTTP_202_ACCEPTED)
def trigger_sync(body: SyncRequest = SyncRequest()) -> dict:
    from app.workers import tasks  # noqa: WPS433
    from app.workers.celery_app import celery_app  # noqa: WPS433

    _ = celery_app
    if body.drive:
        async_result = tasks.sync_drive.delay(body.drive)
        logger.info("manual sync scheduled drive=%s task_id=%s", body.drive, async_result.id)
        return {"task_id": async_result.id, "task": "sync_drive", "drive": body.drive}
    async_result = tasks.sync_all_drives.delay()
    logger.info("manual sync-all scheduled task_id=%s", async_result.id)
    return {"task_id": async_result.id, "task": "sync_all_drives"}
