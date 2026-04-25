from __future__ import annotations

from app.db.models import File, FileStatus


def normalize_checksum(value: str | None) -> str | None:
    if value is None:
        return None
    return value.strip().lower()


def should_skip_from_db(row: File, *, incoming_checksum: str | None, canonical_path: str) -> bool:
    if row.status != FileStatus.UPLOADED.value:
        return False
    if (row.minio_path or "") != canonical_path:
        return False
    return normalize_checksum(row.checksum) == normalize_checksum(incoming_checksum)


def checksum_changed_on_drive(row: File, *, incoming_checksum: str | None) -> bool:
    return normalize_checksum(row.checksum) != normalize_checksum(incoming_checksum)


def extract_minio_checksum(metadata: dict[str, str] | None) -> str | None:
    if not metadata:
        return None
    for key, value in metadata.items():
        lk = key.lower()
        if lk in ("x-amz-meta-checksum", "checksum"):
            return str(value)
    return None


def extract_drive_file_id(metadata: dict[str, str] | None) -> str | None:
    if not metadata:
        return None
    for key, value in metadata.items():
        lk = key.lower()
        if lk in ("x-amz-meta-drive_file_id", "x-amz-meta-drive-file-id", "drive_file_id"):
            return str(value)
    return None


def should_skip_from_minio(*, object_checksum: str | None, incoming_checksum: str | None) -> bool:
    if not object_checksum or not incoming_checksum:
        return False
    return normalize_checksum(object_checksum) == normalize_checksum(incoming_checksum)
