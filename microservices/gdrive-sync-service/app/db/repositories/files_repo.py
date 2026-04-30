from __future__ import annotations

from datetime import datetime, timedelta, timezone
from sqlalchemy import Select, func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import File, FileStatus
from app.services.paths import build_object_key


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class FileRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def upsert_discovered(
        self,
        *,
        drive_name: str,
        file_id: str,
        file_name: str,
        checksum: str | None,
        size: int,
        object_prefix: str | None = None,
    ) -> None:
        minio_path = build_object_key(
            drive_name,
            file_id,
            file_name,
            object_prefix=object_prefix,
        )
        now = _utcnow()
        stmt = (
            insert(File)
            .values(
                drive_name=drive_name,
                file_id=file_id,
                file_name=file_name,
                checksum=checksum,
                size=size,
                status=FileStatus.NEW.value,
                minio_path=minio_path,
                attempt_count=0,
                last_error=None,
                created_at=now,
                updated_at=now,
            )
            .on_conflict_do_update(
                index_elements=[File.drive_name, File.file_id],
                set_={
                    "file_name": file_name,
                    "checksum": checksum,
                    "size": size,
                    "minio_path": minio_path,
                    "updated_at": now,
                },
            )
        )
        await self._session.execute(stmt)

    async def get_by_drive_file(self, drive_name: str, file_id: str) -> File | None:
        res = await self._session.execute(
            select(File).where(File.drive_name == drive_name, File.file_id == file_id)
        )
        return res.scalar_one_or_none()

    async def find_by_drive_name_and_file_name(self, drive_name: str, file_name: str) -> list[File]:
        res = await self._session.execute(
            select(File)
            .where(File.drive_name == drive_name, File.file_name == file_name)
            .order_by(File.updated_at.desc(), File.id.desc())
        )
        return list(res.scalars().all())

    async def claim_next_upload_row(
        self,
        *,
        drive_name: str | None,
    ) -> File | None:
        q: Select[tuple[File]] = (
            select(File)
            .where(
                File.status.in_([FileStatus.NEW.value, FileStatus.FAILED.value]),
            )
            .order_by(File.updated_at.asc())
            .with_for_update(skip_locked=True)
        )
        if drive_name:
            q = q.where(File.drive_name == drive_name)
        res = await self._session.execute(q.limit(1))
        row = res.scalar_one_or_none()
        if row is None:
            return None
        row.status = FileStatus.PROCESSING.value
        row.updated_at = _utcnow()
        await self._session.flush()
        return row

    async def lock_file_row(self, drive_name: str, file_id: str) -> File | None:
        res = await self._session.execute(
            select(File)
            .where(File.drive_name == drive_name, File.file_id == file_id)
            .with_for_update()
        )
        return res.scalar_one_or_none()

    async def mark_uploaded(
        self,
        file_row: File,
        *,
        checksum: str | None,
        size: int,
        minio_path: str,
    ) -> None:
        file_row.status = FileStatus.UPLOADED.value
        file_row.checksum = checksum
        file_row.size = size
        file_row.minio_path = minio_path
        file_row.last_error = None
        file_row.attempt_count = 0
        file_row.updated_at = _utcnow()
        await self._session.flush()

    async def mark_failed(self, file_row: File, message: str) -> None:
        file_row.status = FileStatus.FAILED.value
        file_row.last_error = message[:4000]
        file_row.attempt_count = file_row.attempt_count + 1
        file_row.updated_at = _utcnow()
        await self._session.flush()

    async def mark_corrupted(self, file_row: File, reason: str) -> None:
        file_row.status = FileStatus.CORRUPTED.value
        file_row.last_error = reason[:4000]
        file_row.updated_at = _utcnow()
        await self._session.flush()

    async def reset_stale_processing(self, *, older_than_seconds: int) -> int:
        threshold = _utcnow() - timedelta(seconds=older_than_seconds)
        stmt = (
            update(File)
            .where(File.status == FileStatus.PROCESSING.value, File.updated_at < threshold)
            .values(
                status=FileStatus.FAILED.value,
                last_error="stale_processing_reset",
                updated_at=_utcnow(),
            )
        )
        res = await self._session.execute(stmt)
        return int(res.rowcount or 0)

    async def list_files_page(
        self,
        *,
        drive_name: str | None,
        status: str | None,
        name_contains: str | None,
        cursor_updated_at: datetime | None,
        cursor_id: int | None,
        limit: int,
    ) -> list[File]:
        q = select(File).order_by(File.updated_at.desc(), File.id.desc())
        if drive_name:
            q = q.where(File.drive_name == drive_name)
        if status:
            q = q.where(File.status == status)
        if name_contains:
            q = q.where(File.file_name.ilike(f"%{name_contains}%"))
        if cursor_updated_at is not None and cursor_id is not None:
            q = q.where(
                (File.updated_at < cursor_updated_at)
                | ((File.updated_at == cursor_updated_at) & (File.id < cursor_id))
            )
        q = q.limit(limit)
        res = await self._session.execute(q)
        return list(res.scalars().all())

    async def count_files(self) -> int:
        res = await self._session.execute(select(func.count()).select_from(File))
        return int(res.scalar_one())

    async def list_all_by_drive(self, drive_name: str) -> list[File]:
        """Return all file rows for *drive_name* — used by the quality audit."""
        res = await self._session.execute(
            select(File).where(File.drive_name == drive_name)
        )
        return list(res.scalars().all())
