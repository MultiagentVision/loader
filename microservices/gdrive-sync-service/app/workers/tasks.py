from __future__ import annotations

import asyncio
import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.settings import get_settings
from app.db.repositories.files_repo import FileRepository
from app.db.session import create_engine as make_async_engine
from app.services.drives_config import load_drives_config
from app.services.upload_pipeline import run_sync_for_drive, run_upload_for_file
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="app.workers.tasks.sync_all_drives")
def sync_all_drives() -> dict[str, list[str]]:
    settings = get_settings()
    drives = load_drives_config(settings.drives_config_path)
    ids: list[str] = []
    for d in drives:
        res = sync_drive.delay(d.name)
        ids.append(res.id)
    logger.info("scheduled sync_drive tasks count=%s", len(ids))
    return {"sync_drive_task_ids": ids}


@celery_app.task(name="app.workers.tasks.sync_drive")
def sync_drive(drive_name: str) -> dict:
    settings = get_settings()
    drives = load_drives_config(settings.drives_config_path)
    drive_cfg = next((d for d in drives if d.name == drive_name), None)
    if drive_cfg is None:
        logger.error("unknown drive_name=%s", drive_name)
        return {"drive": drive_name, "error": "unknown_drive"}

    def enqueue_upload(d: str, file_id: str) -> None:
        upload_file.apply_async(args=[d, file_id], queue="upload")

    discovered = asyncio.run(
        run_sync_for_drive(
            settings=settings,
            drive_cfg=drive_cfg,
            enqueue_upload=enqueue_upload,
        )
    )
    logger.info("sync_drive finished drive=%s discovered=%s", drive_name, discovered)
    return {"drive": drive_name, "discovered": discovered}


@celery_app.task(
    name="app.workers.tasks.upload_file",
    bind=True,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=900,
    retry_kwargs={"max_retries": 4},
)
def upload_file(self, drive_name: str, file_id: str) -> None:
    settings = get_settings()
    drives = load_drives_config(settings.drives_config_path)
    drive_cfg = next((d for d in drives if d.name == drive_name), None)
    if drive_cfg is None:
        logger.error("upload_file unknown drive_name=%s", drive_name)
        return
    asyncio.run(
        run_upload_for_file(
            settings=settings,
            drive_cfg=drive_cfg,
            drive_name=drive_name,
            file_id=file_id,
        )
    )


@celery_app.task(name="app.workers.tasks.reconcile_stale_processing")
def reconcile_stale_processing() -> dict:
    settings = get_settings()

    async def _run() -> int:
        engine = make_async_engine(settings, null_pool=True)
        session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
        try:
            async with session_maker() as session:
                async with session.begin():
                    repo = FileRepository(session)
                    return await repo.reset_stale_processing(
                        older_than_seconds=settings.stale_processing_seconds,
                    )
        finally:
            await engine.dispose()

    updated = asyncio.run(_run())
    logger.info("reconcile_stale_processing updated_rows=%s", updated)
    return {"updated_rows": updated}
