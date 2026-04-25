from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.settings import Settings
from app.db.models import File, FileStatus
from app.db.repositories.files_repo import FileRepository
from app.db.session import create_engine as make_async_engine
from app.services.dedupe import (
    checksum_changed_on_drive,
    extract_minio_checksum,
    should_skip_from_db,
    should_skip_from_minio,
)
from app.services.drive_client import GoogleDriveClient
from app.services.minio_client import MinioObjectStore
from app.services.mime_utils import is_video_like
from app.services.paths import build_object_key
from app.services.drives_config import DriveConfig

logger = logging.getLogger(__name__)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _processing_is_fresh(row: File, stale_seconds: int) -> bool:
    if row.status != FileStatus.PROCESSING.value:
        return False
    updated = row.updated_at
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=timezone.utc)
    age = (_utcnow() - updated).total_seconds()
    return age < stale_seconds


async def run_upload_for_file(
    *,
    settings: Settings,
    drive_cfg: DriveConfig,
    drive_name: str,
    file_id: str,
) -> None:
    engine = make_async_engine(settings, null_pool=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    try:
        drive = GoogleDriveClient(str(drive_cfg.credentials_path), drive_cfg.folder_id)
        store = MinioObjectStore(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
        await asyncio.to_thread(store.ensure_bucket)

        async with session_maker() as session:
            async with session.begin():
                repo = FileRepository(session)
                row = await repo.lock_file_row(drive_name, file_id)
                if row is None:
                    logger.warning("upload skipped: no DB row drive=%s file_id=%s", drive_name, file_id)
                    return

                if row.status == FileStatus.PROCESSING.value and _processing_is_fresh(
                    row, settings.stale_processing_seconds
                ):
                    logger.info(
                        "upload skipped: row already PROCESSING (fresh) drive=%s file_id=%s",
                        drive_name,
                        file_id,
                    )
                    return

                meta = await asyncio.to_thread(drive.get_file_metadata, file_id)
                mime = meta.get("mimeType") or ""
                file_name = meta.get("name") or row.file_name
                if not is_video_like(mime, file_name):
                    logger.info("skip non-video mime=%s name=%s drive=%s file_id=%s", mime, file_name, drive_name, file_id)
                    return

                incoming_checksum = meta.get("md5Checksum")
                size = int(meta.get("size") or row.size or 0)
                if size <= 0:
                    logger.info("skip zero-size drive=%s file_id=%s", drive_name, file_id)
                    return
                canonical_path = build_object_key(
                    drive_name,
                    file_id,
                    file_name,
                    object_prefix=drive_cfg.object_prefix,
                )

                if should_skip_from_db(row, incoming_checksum=incoming_checksum, canonical_path=canonical_path):
                    logger.info("SKIP (DB): drive=%s file_id=%s name=%s", drive_name, file_id, file_name)
                    return

                stat = await asyncio.to_thread(store.stat_object, canonical_path)
                if stat is not None:
                    object_checksum = extract_minio_checksum(dict(stat.metadata or {}))
                    if should_skip_from_minio(
                        object_checksum=object_checksum, incoming_checksum=incoming_checksum
                    ):
                        if row.status != FileStatus.UPLOADED.value:
                            logger.warning(
                                "reconcile DB from MinIO: drive=%s file_id=%s object=%s",
                                drive_name,
                                file_id,
                                canonical_path,
                            )
                            await repo.mark_uploaded(
                                row,
                                checksum=incoming_checksum,
                                size=size,
                                minio_path=canonical_path,
                            )
                        else:
                            logger.info(
                                "SKIP (MinIO): drive=%s file_id=%s name=%s",
                                drive_name,
                                file_id,
                                file_name,
                            )
                        return

                    if row.status == FileStatus.UPLOADED.value and object_checksum and incoming_checksum:
                        logger.warning(
                            "MinIO object checksum mismatch; overwriting drive=%s file_id=%s",
                            drive_name,
                            file_id,
                        )

                if stat is None and row.status == FileStatus.UPLOADED.value:
                    logger.warning(
                        "DB says UPLOADED but MinIO missing object; will reupload drive=%s file_id=%s key=%s",
                        drive_name,
                        file_id,
                        canonical_path,
                    )

                if row.attempt_count >= settings.max_upload_attempts:
                    logger.error(
                        "max attempts exceeded drive=%s file_id=%s attempts=%s",
                        drive_name,
                        file_id,
                        row.attempt_count,
                    )
                    return

                row.status = FileStatus.PROCESSING.value
                row.file_name = file_name
                row.checksum = incoming_checksum
                row.size = size
                row.minio_path = canonical_path
                row.updated_at = _utcnow()
                await session.flush()

            metadata = {
                "checksum": incoming_checksum or "",
                "drive_file_id": file_id,
            }

            def _transfer() -> None:
                resp = drive.open_media_stream(file_id)
                try:
                    raw = resp.raw
                    if size >= settings.multipart_threshold_bytes:
                        store.put_object_multipart_stream(
                            canonical_path,
                            raw,
                            part_size=settings.multipart_part_size,
                            metadata=metadata,
                        )
                    else:
                        store.put_object_stream(
                            canonical_path,
                            raw,
                            length=size,
                            metadata=metadata,
                        )
                finally:
                    resp.close()

            try:
                await asyncio.to_thread(_transfer)
            except Exception as exc:  # noqa: BLE001
                logger.exception("upload failed drive=%s file_id=%s", drive_name, file_id)
                async with session.begin():
                    repo = FileRepository(session)
                    row2 = await repo.lock_file_row(drive_name, file_id)
                    if row2 is not None:
                        await repo.mark_failed(row2, str(exc))
                raise

            async with session.begin():
                repo = FileRepository(session)
                row3 = await repo.lock_file_row(drive_name, file_id)
                if row3 is None:
                    return
                await repo.mark_uploaded(
                    row3,
                    checksum=incoming_checksum,
                    size=size,
                    minio_path=canonical_path,
                )
            logger.info("UPLOADED drive=%s file_id=%s key=%s", drive_name, file_id, canonical_path)
    finally:
        await engine.dispose()


async def run_sync_for_drive(
    *,
    settings: Settings,
    drive_cfg: DriveConfig,
    enqueue_upload,
) -> int:
    """Upsert metadata from Drive; return number of discovered files."""
    engine = make_async_engine(settings, null_pool=True)
    session_maker = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    drive = GoogleDriveClient(str(drive_cfg.credentials_path), drive_cfg.folder_id)
    try:
        remote_files = await asyncio.to_thread(drive.list_videos)
        async with session_maker() as session:
            async with session.begin():
                repo = FileRepository(session)
                for f in remote_files:
                    file_id = f["id"]
                    file_name = f.get("name") or "unnamed"
                    checksum = f.get("md5Checksum")
                    size = int(f.get("size") or 0)
                    await repo.upsert_discovered(
                        drive_name=drive_cfg.name,
                        file_id=file_id,
                        file_name=file_name,
                        checksum=checksum,
                        size=size,
                    )
                    row = await repo.get_by_drive_file(drive_cfg.name, file_id)
                    if (
                        row
                        and row.status == FileStatus.UPLOADED.value
                        and checksum_changed_on_drive(row, incoming_checksum=checksum)
                    ):
                        row.status = FileStatus.NEW.value
                        row.updated_at = _utcnow()
                        await session.flush()
                        logger.info(
                            "checksum changed; queued for reupload drive=%s file_id=%s",
                            drive_cfg.name,
                            file_id,
                        )

        for f in remote_files:
            enqueue_upload(drive_cfg.name, f["id"])
        return len(remote_files)
    finally:
        await engine.dispose()
