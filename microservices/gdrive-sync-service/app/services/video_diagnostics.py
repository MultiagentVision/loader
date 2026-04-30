from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timezone
from typing import BinaryIO, Literal

from pydantic import BaseModel

from app.db.models import File
from app.services.dedupe import extract_minio_checksum, normalize_checksum
from app.services.drive_client import GoogleDriveClient
from app.services.drives_config import DriveConfig
from app.services.minio_client import MinioObjectStore
from app.services.paths import build_object_key

DiagnosticMode = Literal["chunks", "full"]

DEFAULT_CHUNK_SIZE = 1024 * 1024


class ChunkCheck(BaseModel):
    name: str
    offset: int
    length: int
    drive_sha256: str
    minio_sha256: str
    match: bool


class VideoDiagnosticReport(BaseModel):
    generated_at: datetime
    drive_name: str
    file_id: str
    file_name: str
    mode: DiagnosticMode
    minio_key: str | None
    drive_size: int
    minio_size: int | None
    drive_md5: str | None
    minio_metadata_checksum: str | None
    size_match: bool | None
    metadata_md5_match: bool | None
    chunk_checks: list[ChunkCheck]
    full_drive_sha256: str | None
    full_minio_sha256: str | None
    full_sha256_match: bool | None
    presigned_minio_url: str | None
    verdict: str
    details: list[str]


def _close_minio_response(resp) -> None:
    resp.close()
    resp.release_conn()


def _sha256_from_stream(stream: BinaryIO, *, length: int | None = None) -> str:
    digest = hashlib.sha256()
    remaining = length
    while True:
        read_size = DEFAULT_CHUNK_SIZE
        if remaining is not None:
            if remaining <= 0:
                break
            read_size = min(read_size, remaining)
        chunk = stream.read(read_size)
        if not chunk:
            break
        digest.update(chunk)
        if remaining is not None:
            remaining -= len(chunk)
    return digest.hexdigest()


def _hash_drive_range(
    drive: GoogleDriveClient,
    *,
    file_id: str,
    offset: int,
    length: int,
) -> str:
    end = offset + length - 1
    range_header = f"bytes={offset}-{end}"
    resp = drive.open_media_stream(file_id, range_header=range_header)
    try:
        if resp.status_code != 206:
            raise RuntimeError(f"Drive range request returned HTTP {resp.status_code}")
        return _sha256_from_stream(resp.raw, length=length)
    finally:
        resp.close()


def _hash_drive_full(drive: GoogleDriveClient, *, file_id: str) -> str:
    resp = drive.open_media_stream(file_id)
    try:
        return _sha256_from_stream(resp.raw)
    finally:
        resp.close()


def _hash_minio_range(
    store: MinioObjectStore,
    *,
    object_name: str,
    offset: int,
    length: int,
) -> str:
    resp = store.get_object_stream(object_name, offset=offset, length=length)
    try:
        return _sha256_from_stream(resp, length=length)
    finally:
        _close_minio_response(resp)


def _hash_minio_full(store: MinioObjectStore, *, object_name: str) -> str:
    resp = store.get_object_stream(object_name)
    try:
        return _sha256_from_stream(resp)
    finally:
        _close_minio_response(resp)


def _chunk_ranges(size: int, *, chunk_size: int = DEFAULT_CHUNK_SIZE) -> list[tuple[str, int, int]]:
    if size <= 0:
        return []
    length = min(size, chunk_size)
    ranges = [
        ("head", 0, length),
        ("middle", max(0, (size - length) // 2), length),
        ("tail", max(0, size - length), length),
    ]

    unique: list[tuple[str, int, int]] = []
    seen: set[tuple[int, int]] = set()
    for name, offset, item_length in ranges:
        key = (offset, item_length)
        if key in seen:
            continue
        seen.add(key)
        unique.append((name, offset, item_length))
    return unique


def _metadata_md5_matches(drive_md5: str | None, minio_checksum: str | None) -> bool | None:
    if not drive_md5 or not minio_checksum:
        return None
    return normalize_checksum(drive_md5) == normalize_checksum(minio_checksum)


def _object_key_from_row_or_drive(
    *,
    drive_cfg: DriveConfig,
    db_row: File | None,
    file_id: str,
    file_name: str,
) -> str | None:
    if db_row and db_row.minio_path:
        return db_row.minio_path
    return build_object_key(
        drive_cfg.name,
        file_id,
        file_name,
        object_prefix=drive_cfg.object_prefix,
    )


async def run_video_diagnostic(
    *,
    drive_cfg: DriveConfig,
    store: MinioObjectStore,
    db_row: File | None,
    file_id: str,
    mode: DiagnosticMode = "chunks",
) -> VideoDiagnosticReport:
    drive = GoogleDriveClient(str(drive_cfg.credentials_path), drive_cfg.folder_id)
    drive_meta = await asyncio.to_thread(drive.get_file_metadata, file_id)
    file_name = drive_meta.get("name") or (db_row.file_name if db_row else "unknown")
    drive_md5 = drive_meta.get("md5Checksum")
    drive_size = int(drive_meta.get("size") or 0)
    minio_key = _object_key_from_row_or_drive(
        drive_cfg=drive_cfg,
        db_row=db_row,
        file_id=file_id,
        file_name=file_name,
    )

    stat = await asyncio.to_thread(store.stat_object, minio_key) if minio_key else None
    minio_size = stat.size if stat else None
    minio_metadata_checksum = extract_minio_checksum(stat.metadata) if stat else None
    size_match = (drive_size == minio_size) if minio_size is not None else None
    metadata_md5_match = _metadata_md5_matches(drive_md5, minio_metadata_checksum)
    details: list[str] = []

    if not minio_key:
        return _build_report(
            drive_cfg=drive_cfg,
            file_id=file_id,
            file_name=file_name,
            mode=mode,
            minio_key=minio_key,
            drive_size=drive_size,
            minio_size=minio_size,
            drive_md5=drive_md5,
            minio_metadata_checksum=minio_metadata_checksum,
            size_match=size_match,
            metadata_md5_match=metadata_md5_match,
            verdict="missing_minio_key",
            details=["No MinIO key could be resolved for this file."],
        )

    if stat is None:
        return _build_report(
            drive_cfg=drive_cfg,
            file_id=file_id,
            file_name=file_name,
            mode=mode,
            minio_key=minio_key,
            drive_size=drive_size,
            minio_size=minio_size,
            drive_md5=drive_md5,
            minio_metadata_checksum=minio_metadata_checksum,
            size_match=size_match,
            metadata_md5_match=metadata_md5_match,
            verdict="missing_minio_object",
            details=["The expected MinIO object does not exist."],
        )

    if size_match is False:
        details.append("Drive and MinIO object sizes differ.")
    if metadata_md5_match is False:
        details.append("Drive MD5 differs from the checksum stored in MinIO metadata.")

    if size_match is False:
        presigned_url = await asyncio.to_thread(store.presigned_get_object, minio_key)
        return _build_report(
            drive_cfg=drive_cfg,
            file_id=file_id,
            file_name=file_name,
            mode=mode,
            minio_key=minio_key,
            drive_size=drive_size,
            minio_size=minio_size,
            drive_md5=drive_md5,
            minio_metadata_checksum=minio_metadata_checksum,
            size_match=size_match,
            metadata_md5_match=metadata_md5_match,
            presigned_minio_url=presigned_url,
            verdict="bytes_differ_upload_or_storage_suspect",
            details=details,
        )

    chunk_checks: list[ChunkCheck] = []
    full_drive_sha256: str | None = None
    full_minio_sha256: str | None = None
    full_sha256_match: bool | None = None

    if mode == "chunks":
        for name, offset, length in _chunk_ranges(drive_size):
            drive_hash, minio_hash = await asyncio.gather(
                asyncio.to_thread(
                    _hash_drive_range,
                    drive,
                    file_id=file_id,
                    offset=offset,
                    length=length,
                ),
                asyncio.to_thread(
                    _hash_minio_range,
                    store,
                    object_name=minio_key,
                    offset=offset,
                    length=length,
                ),
            )
            chunk_checks.append(
                ChunkCheck(
                    name=name,
                    offset=offset,
                    length=length,
                    drive_sha256=drive_hash,
                    minio_sha256=minio_hash,
                    match=drive_hash == minio_hash,
                )
            )
        if any(not item.match for item in chunk_checks):
            details.append("At least one sampled byte range differs.")
    else:
        full_drive_sha256, full_minio_sha256 = await asyncio.gather(
            asyncio.to_thread(_hash_drive_full, drive, file_id=file_id),
            asyncio.to_thread(_hash_minio_full, store, object_name=minio_key),
        )
        full_sha256_match = full_drive_sha256 == full_minio_sha256
        if not full_sha256_match:
            details.append("Full file SHA256 differs.")

    verdict = _verdict(
        size_match=size_match,
        metadata_md5_match=metadata_md5_match,
        chunk_checks=chunk_checks,
        full_sha256_match=full_sha256_match,
    )

    presigned_url = await asyncio.to_thread(store.presigned_get_object, minio_key)

    return _build_report(
        drive_cfg=drive_cfg,
        file_id=file_id,
        file_name=file_name,
        mode=mode,
        minio_key=minio_key,
        drive_size=drive_size,
        minio_size=minio_size,
        drive_md5=drive_md5,
        minio_metadata_checksum=minio_metadata_checksum,
        size_match=size_match,
        metadata_md5_match=metadata_md5_match,
        chunk_checks=chunk_checks,
        full_drive_sha256=full_drive_sha256,
        full_minio_sha256=full_minio_sha256,
        full_sha256_match=full_sha256_match,
        presigned_minio_url=presigned_url,
        verdict=verdict,
        details=details,
    )


def _verdict(
    *,
    size_match: bool | None,
    metadata_md5_match: bool | None,
    chunk_checks: list[ChunkCheck],
    full_sha256_match: bool | None,
) -> str:
    if size_match is False:
        return "bytes_differ_upload_or_storage_suspect"
    if full_sha256_match is False:
        return "bytes_differ_upload_or_storage_suspect"
    if any(not item.match for item in chunk_checks):
        return "bytes_differ_upload_or_storage_suspect"
    if metadata_md5_match is False:
        return "metadata_mismatch_upload_or_storage_suspect"
    if full_sha256_match is True:
        return "bytes_match_hook_or_splitter_suspect"
    if chunk_checks and all(item.match for item in chunk_checks):
        return "sampled_bytes_match_run_full_for_proof"
    return "inconclusive"


def _build_report(
    *,
    drive_cfg: DriveConfig,
    file_id: str,
    file_name: str,
    mode: DiagnosticMode,
    minio_key: str | None,
    drive_size: int,
    minio_size: int | None,
    drive_md5: str | None,
    minio_metadata_checksum: str | None,
    size_match: bool | None,
    metadata_md5_match: bool | None,
    verdict: str,
    details: list[str],
    chunk_checks: list[ChunkCheck] | None = None,
    full_drive_sha256: str | None = None,
    full_minio_sha256: str | None = None,
    full_sha256_match: bool | None = None,
    presigned_minio_url: str | None = None,
) -> VideoDiagnosticReport:
    return VideoDiagnosticReport(
        generated_at=datetime.now(timezone.utc),
        drive_name=drive_cfg.name,
        file_id=file_id,
        file_name=file_name,
        mode=mode,
        minio_key=minio_key,
        drive_size=drive_size,
        minio_size=minio_size,
        drive_md5=drive_md5,
        minio_metadata_checksum=minio_metadata_checksum,
        size_match=size_match,
        metadata_md5_match=metadata_md5_match,
        chunk_checks=chunk_checks or [],
        full_drive_sha256=full_drive_sha256,
        full_minio_sha256=full_minio_sha256,
        full_sha256_match=full_sha256_match,
        presigned_minio_url=presigned_minio_url,
        verdict=verdict,
        details=details,
    )
