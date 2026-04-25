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

    @property
    def celery_broker(self) -> str:
        return self.celery_broker_url or self.redis_url

    @property
    def celery_backend(self) -> str:
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    return Settings()
