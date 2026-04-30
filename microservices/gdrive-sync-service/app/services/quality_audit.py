from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel

from app.db.models import File, FileStatus
from app.db.repositories.files_repo import FileRepository
from app.services.dedupe import (
    extract_drive_file_id,
    extract_minio_checksum,
    normalize_checksum,
)
from app.services.drive_client import GoogleDriveClient
from app.services.drives_config import DriveConfig
from app.services.minio_client import MinioObjectStore

logger = logging.getLogger(__name__)


class FileAuditItem(BaseModel):
    drive_file_id: str
    file_name: str
    drive_md5: str | None
    drive_size: int
    minio_key: str | None
    minio_size: int | None
    minio_checksum: str | None
    db_status: str | None
    issues: list[str]


class AuditReport(BaseModel):
    generated_at: datetime
    drive_name: str
    total_drive_files: int
    total_minio_objects: int
    synced_ok: int
    issues: list[FileAuditItem]
    summary: dict[str, int]


async def run_audit(
    *,
    drive_cfg: DriveConfig,
    store: MinioObjectStore,
    repo: FileRepository,
    full: bool = False,
) -> AuditReport:
    """Compare Google Drive contents with MinIO objects and the PostgreSQL DB.

    Args:
        drive_cfg: Config for the drive to audit.
        store: Initialized MinIO client.
        repo: DB repository scoped to an open async session.
        full: When True, call ``stat_object`` for every Drive file to fetch
              and compare the checksum stored in MinIO user-metadata.
              This is accurate but makes one extra HTTP request per file.
    """
    drive = GoogleDriveClient(str(drive_cfg.credentials_path), drive_cfg.folder_id)

    # -- collect data from all three sources ---------------------------------
    logger.info("audit: listing Drive files for drive=%s", drive_cfg.name)
    drive_files_list: list[dict[str, Any]] = await asyncio.to_thread(drive.list_videos)
    drive_index: dict[str, dict[str, Any]] = {f["id"]: f for f in drive_files_list}

    logger.info("audit: %d Drive files found", len(drive_index))

    db_records: list[File] = await repo.list_all_by_drive(drive_cfg.name)
    db_by_file_id: dict[str, File] = {r.file_id: r for r in db_records}
    db_by_minio_path: dict[str, File] = {
        r.minio_path: r for r in db_records if r.minio_path
    }

    prefix = (drive_cfg.object_prefix or drive_cfg.name).strip("/")
    logger.info("audit: listing MinIO objects with prefix=%s", prefix)
    minio_objects_raw = await asyncio.to_thread(lambda: list(store.list_objects(prefix)))
    minio_by_name = {o.object_name: o for o in minio_objects_raw}

    logger.info("audit: %d MinIO objects found", len(minio_by_name))

    # -- cross-reference Drive files -----------------------------------------
    audit_items: list[FileAuditItem] = []
    drive_ids_with_issues: set[str] = set()
    seen_minio_keys: set[str] = set()

    for file_id, drive_file in drive_index.items():
        file_name: str = drive_file.get("name") or ""
        drive_md5: str | None = drive_file.get("md5Checksum")
        raw_size = drive_file.get("size") or "0"
        drive_size = int(raw_size) if raw_size else 0

        db_record = db_by_file_id.get(file_id)
        db_status = db_record.status if db_record else None

        # Expected MinIO key comes from the DB record (the actual uploaded path).
        expected_key = db_record.minio_path if db_record else None
        minio_obj = minio_by_name.get(expected_key) if expected_key else None
        if minio_obj is not None:
            seen_minio_keys.add(expected_key)  # type: ignore[arg-type]

        issues: list[str] = []
        minio_size: int | None = None
        minio_checksum: str | None = None

        if minio_obj is None:
            issues.append("missing_in_minio")
        else:
            minio_size = minio_obj.size
            if drive_size > 0 and minio_size is not None and minio_size != drive_size:
                issues.append("size_mismatch")

            if full and expected_key:
                stat = await asyncio.to_thread(store.stat_object, expected_key)
                if stat:
                    minio_checksum = extract_minio_checksum(stat.metadata)
                    if drive_md5 and minio_checksum:
                        if normalize_checksum(drive_md5) != normalize_checksum(minio_checksum):
                            issues.append("checksum_mismatch")

        if db_status is None:
            issues.append("not_in_db")
        elif db_status == FileStatus.UPLOADED.value and minio_obj is None:
            # DB claims uploaded but the object is absent — already flagged above;
            # add a separate db_inconsistent marker for clarity.
            issues.append("db_inconsistent")
        elif db_status not in (FileStatus.UPLOADED.value, FileStatus.PROCESSING.value) and minio_obj is not None:
            # Object is in MinIO but DB hasn't recorded it as uploaded yet.
            issues.append("db_inconsistent")

        if issues:
            drive_ids_with_issues.add(file_id)
            audit_items.append(
                FileAuditItem(
                    drive_file_id=file_id,
                    file_name=file_name,
                    drive_md5=drive_md5,
                    drive_size=drive_size,
                    minio_key=expected_key,
                    minio_size=minio_size,
                    minio_checksum=minio_checksum,
                    db_status=db_status,
                    issues=issues,
                )
            )

    # -- find orphaned MinIO objects (exist in MinIO, absent from Drive) ------
    for minio_key, minio_obj in minio_by_name.items():
        if minio_key in seen_minio_keys:
            continue

        # Resolve Drive file_id via DB index or the object key prefix convention.
        db_record = db_by_minio_path.get(minio_key)
        if db_record:
            orphan_file_id = db_record.file_id
            orphan_name = db_record.file_name
            orphan_db_status: str | None = db_record.status
        else:
            # Fall back to extracting from MinIO user-metadata (requires stat).
            orphan_file_id = "unknown"
            orphan_name = minio_key.rsplit("/", 1)[-1]
            orphan_db_status = None

        if orphan_file_id not in drive_index:
            audit_items.append(
                FileAuditItem(
                    drive_file_id=orphan_file_id,
                    file_name=orphan_name,
                    drive_md5=None,
                    drive_size=0,
                    minio_key=minio_key,
                    minio_size=minio_obj.size,
                    minio_checksum=None,
                    db_status=orphan_db_status,
                    issues=["orphaned_in_minio"],
                )
            )

    # -- summary counters ----------------------------------------------------
    summary: dict[str, int] = {}
    for item in audit_items:
        for issue in item.issues:
            summary[issue] = summary.get(issue, 0) + 1

    synced_ok = max(0, len(drive_index) - len(drive_ids_with_issues))

    logger.info(
        "audit complete drive=%s drive_files=%d minio_objects=%d synced_ok=%d issues=%s",
        drive_cfg.name,
        len(drive_index),
        len(minio_by_name),
        synced_ok,
        summary,
    )

    return AuditReport(
        generated_at=datetime.now(timezone.utc),
        drive_name=drive_cfg.name,
        total_drive_files=len(drive_index),
        total_minio_objects=len(minio_by_name),
        synced_ok=synced_ok,
        issues=audit_items,
        summary=summary,
    )
