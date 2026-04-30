from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "gdrive-sync-service"
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")

    database_url: str = Field(validation_alias="DATABASE_URL")
    redis_url: str = Field(validation_alias="REDIS_URL")

    minio_endpoint: str = Field(validation_alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(validation_alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(validation_alias="MINIO_SECRET_KEY")
    minio_bucket: str = Field(default="videos", validation_alias="MINIO_BUCKET")
    minio_secure: bool = Field(default=False, validation_alias="MINIO_SECURE")

    drives_config_path: Path = Field(
        default=Path("/config/drives.yaml"),
        validation_alias="DRIVES_CONFIG_PATH",
    )

    sync_interval_seconds: int = Field(default=300, validation_alias="SYNC_INTERVAL_SECONDS")
    drive_read_chunk_size: int = Field(
        default=8 * 1024 * 1024,
        validation_alias="DRIVE_READ_CHUNK_SIZE",
    )
    multipart_threshold_bytes: int = Field(
        default=32 * 1024 * 1024,
        validation_alias="MULTIPART_THRESHOLD_BYTES",
    )
    multipart_part_size: int = Field(
        default=16 * 1024 * 1024,
        validation_alias="MULTIPART_PART_SIZE",
    )

    celery_broker_url: str | None = Field(default=None, validation_alias="CELERY_BROKER_URL")
    celery_result_backend: str | None = Field(default=None, validation_alias="CELERY_RESULT_BACKEND")

    drive_webhook_secret: str | None = Field(default=None, validation_alias="DRIVE_WEBHOOK_SECRET")

    stale_processing_seconds: int = Field(
        default=3600,
        validation_alias="STALE_PROCESSING_SECONDS",
    )

    max_upload_attempts: int = Field(default=5, validation_alias="MAX_UPLOAD_ATTEMPTS")

    # Video integrity validation after upload
    video_validation_enabled: bool = Field(default=True, validation_alias="VIDEO_VALIDATION_ENABLED")
    video_min_size_bytes: int = Field(
        default=5 * 1024 * 1024,
        validation_alias="VIDEO_MIN_SIZE_BYTES",
        description="Files smaller than this are immediately marked CORRUPTED (default 5 MB).",
    )
    video_min_duration_sec: float = Field(
        default=5.0,
        validation_alias="VIDEO_MIN_DURATION_SEC",
        description="Videos shorter than this are marked CORRUPTED (default 5 s).",
    )
    video_ffprobe_timeout_sec: int = Field(
        default=30,
        validation_alias="VIDEO_FFPROBE_TIMEOUT_SEC",
    )
    video_frame_check_enabled: bool = Field(
        default=True,
        validation_alias="VIDEO_FRAME_CHECK_ENABLED",
        description="Whether to extract a frame and check pixel variance.",
    )
    video_frame_seek_sec: float = Field(
        default=2.0,
        validation_alias="VIDEO_FRAME_SEEK_SEC",
        description="Seek offset for frame extraction — avoids green HEVC frames at stream start.",
    )
    video_frame_timeout_sec: int = Field(
        default=60,
        validation_alias="VIDEO_FRAME_TIMEOUT_SEC",
    )
    video_frame_min_variance: float = Field(
        default=8.0,
        validation_alias="VIDEO_FRAME_MIN_VARIANCE",
        description="Minimum pixel std-dev to accept a frame (green/gray frames ≈ 0–5).",
    )
    video_presign_expiry_sec: int = Field(
        default=900,
        validation_alias="VIDEO_PRESIGN_EXPIRY_SEC",
        description="Presigned URL TTL for ffprobe/ffmpeg access (default 15 min).",
    )

    @property
    def celery_broker(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def celery_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
