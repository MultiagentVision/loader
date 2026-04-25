from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Request
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.settings import get_settings
from app.services.minio_client import MinioObjectStore

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(request: Request, deep: bool = False) -> dict:
    if not deep:
        return {"status": "ok"}
    settings = get_settings()
    checks: dict[str, str] = {}

    try:
        session_maker = request.app.state.session_maker
        async with session_maker() as session:
            await session.execute(text("SELECT 1"))
        checks["database"] = "ok"
    except Exception as exc:  # noqa: BLE001
        logger.exception("deep health database failed")
        checks["database"] = f"error:{exc.__class__.__name__}"

    try:
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        try:
            pong = await client.ping()
            checks["redis"] = "ok" if pong else "error"
        finally:
            await client.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.exception("deep health redis failed")
        checks["redis"] = f"error:{exc.__class__.__name__}"

    try:
        store = MinioObjectStore(
            endpoint=settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            bucket=settings.minio_bucket,
            secure=settings.minio_secure,
        )
        exists = await asyncio.to_thread(store.bucket_exists)
        checks["minio"] = "ok" if exists else "missing_bucket"
    except Exception as exc:  # noqa: BLE001
        logger.exception("deep health minio failed")
        checks["minio"] = f"error:{exc.__class__.__name__}"

    overall = "ok"
    if any(str(v).startswith("error") for v in checks.values()):
        overall = "degraded"
    if checks.get("minio") == "missing_bucket":
        overall = "degraded"
    return {"status": overall, "checks": checks}
