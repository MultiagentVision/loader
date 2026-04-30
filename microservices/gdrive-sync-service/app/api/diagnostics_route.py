from __future__ import annotations

import logging
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.core.settings import get_settings
from app.db.models import File
from app.db.repositories.files_repo import FileRepository
from app.services.drives_config import DriveConfig, load_drives_config
from app.services.minio_client import MinioObjectStore
from app.services.video_diagnostics import (
    DiagnosticMode,
    VideoDiagnosticReport,
    run_video_diagnostic,
)

router = APIRouter(tags=["diagnostics"])
logger = logging.getLogger(__name__)


class FileCandidate(BaseModel):
    file_id: str
    file_name: str
    size: int
    status: str
    minio_path: str | None
    updated_at: datetime

    model_config = {"from_attributes": True}


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


async def _resolve_file(
    *,
    repo: FileRepository,
    drive_name: str,
    file_id: str | None,
    file_name: str | None,
) -> tuple[str, File | None]:
    if file_id:
        return file_id, await repo.get_by_drive_file(drive_name, file_id)

    if not file_name:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Provide either file_id or file_name.",
        )

    matches = await repo.find_by_drive_name_and_file_name(drive_name, file_name)
    if not matches:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File '{file_name}' not found in DB for drive '{drive_name}'.",
        )
    if len(matches) > 1:
        candidates = [FileCandidate.model_validate(row).model_dump(mode="json") for row in matches]
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Multiple files found with this name. Retry with file_id.",
                "candidates": candidates,
            },
        )
    row = matches[0]
    return row.file_id, row


@router.get(
    "/diagnostics/video",
    response_model=VideoDiagnosticReport,
    summary="Compare video bytes between Google Drive and MinIO",
    description=(
        "Diagnoses a single problematic video. In chunks mode it compares SHA256 "
        "for head/middle/tail byte ranges. In full mode it streams both complete "
        "objects and compares full SHA256 hashes."
    ),
)
async def diagnose_video(
    drive_name: str = Query(..., description="Drive name as defined in drives.yaml"),
    file_id: str | None = Query(default=None, description="Google Drive file id"),
    file_name: str | None = Query(default=None, description="Exact file name in the sync DB"),
    mode: DiagnosticMode = Query(default="chunks", description="Use chunks for a fast check or full for proof"),
    session: AsyncSession = Depends(get_db_session),
) -> VideoDiagnosticReport:
    drive_cfg = _get_drive_cfg(drive_name)
    repo = FileRepository(session)
    resolved_file_id, db_row = await _resolve_file(
        repo=repo,
        drive_name=drive_name,
        file_id=file_id,
        file_name=file_name,
    )

    logger.info(
        "video diagnostics request drive=%s file_id=%s file_name=%s mode=%s",
        drive_name,
        resolved_file_id,
        file_name,
        mode,
    )

    return await run_video_diagnostic(
        drive_cfg=drive_cfg,
        store=_make_store(),
        db_row=db_row,
        file_id=resolved_file_id,
        mode=mode,
    )
