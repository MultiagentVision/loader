from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_db_session
from app.db.models import File
from app.db.repositories.files_repo import FileRepository

router = APIRouter(tags=["files"])


class FileOut(BaseModel):
    id: int
    drive_name: str
    file_id: str
    file_name: str
    checksum: str | None
    size: int
    status: str
    minio_path: str | None
    attempt_count: int
    last_error: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class FilesPage(BaseModel):
    items: list[FileOut]
    next_cursor: dict | None


@router.get("/files", response_model=FilesPage)
async def list_files(
    session: AsyncSession = Depends(get_db_session),
    drive_name: str | None = None,
    status_filter: str | None = Query(default=None, alias="status"),
    name_contains: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    cursor_updated_at: datetime | None = None,
    cursor_id: int | None = None,
) -> FilesPage:
    repo = FileRepository(session)
    rows: list[File] = await repo.list_files_page(
        drive_name=drive_name,
        status=status_filter,
        name_contains=name_contains,
        cursor_updated_at=cursor_updated_at,
        cursor_id=cursor_id,
        limit=limit + 1,
    )
    has_more = len(rows) > limit
    page_rows = rows[:limit]
    next_cursor = None
    if has_more and page_rows:
        tail = page_rows[-1]
        next_cursor = {"updated_at": tail.updated_at.isoformat(), "id": tail.id}
    return FilesPage(items=[FileOut.model_validate(r) for r in page_rows], next_cursor=next_cursor)
