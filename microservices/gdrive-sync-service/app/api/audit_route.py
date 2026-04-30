from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.settings import get_settings
from app.db.repositories.files_repo import FileRepository
from app.services.drives_config import DriveConfig, load_drives_config
from app.services.minio_client import MinioObjectStore
from app.services.quality_audit import AuditReport, run_audit

router = APIRouter(tags=["audit"])
logger = logging.getLogger(__name__)


def _get_drive_cfg(drive_name: str) -> DriveConfig:
    settings = get_settings()
    drives = load_drives_config(settings.drives_config_path)
    for cfg in drives:
        if cfg.name == drive_name:
            return cfg
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Drive '{drive_name}' not found in drives config.",
    )


def _make_store() -> MinioObjectStore:
    settings = get_settings()
    return MinioObjectStore(
        endpoint=settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        bucket=settings.minio_bucket,
        secure=settings.minio_secure,
    )


@router.get(
    "/audit",
    response_model=AuditReport,
    summary="Compare Google Drive files with MinIO objects",
    description=(
        "Returns a data-quality report for a single drive: counts missing files, "
        "size mismatches, orphaned MinIO objects, and DB inconsistencies. "
        "Set `full=true` to also fetch MinIO user-metadata and compare MD5 checksums "
        "(makes one extra HTTP request per Drive file — slower for large libraries)."
    ),
)
async def audit_drive(
    drive_name: str = Query(..., description="Name of the drive as defined in drives.yaml"),
    full: bool = Query(
        default=False,
        description="Fetch MinIO stat_object per file to compare MD5 checksums (slower but thorough)",
    ),
    session: AsyncSession = Depends(get_db_session),
    request: Request = None,  # type: ignore[assignment]
) -> AuditReport:
    drive_cfg = _get_drive_cfg(drive_name)
    store = _make_store()
    repo = FileRepository(session)

    logger.info(
        "audit request drive=%s full=%s remote=%s",
        drive_name,
        full,
        getattr(request, "client", None),
    )

    return await run_audit(
        drive_cfg=drive_cfg,
        store=store,
        repo=repo,
        full=full,
    )
