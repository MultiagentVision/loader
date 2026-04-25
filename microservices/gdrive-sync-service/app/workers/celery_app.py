from __future__ import annotations

from datetime import timedelta

from celery import Celery
from celery.schedules import schedule

from app.core.settings import get_settings


def create_celery_app() -> Celery:
    settings = get_settings()
    app = Celery(
        "gdrive_sync",
        broker=settings.celery_broker,
        backend=settings.celery_backend,
    )
    app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
    )
    app.conf.task_routes = {
        "app.workers.tasks.sync_all_drives": {"queue": "sync"},
        "app.workers.tasks.sync_drive": {"queue": "sync"},
        "app.workers.tasks.upload_file": {"queue": "upload"},
        "app.workers.tasks.reconcile_stale_processing": {"queue": "sync"},
    }
    interval = timedelta(seconds=float(settings.sync_interval_seconds))
    stale_interval = timedelta(seconds=float(min(settings.sync_interval_seconds, 600)))
    app.conf.beat_schedule = {
        "poll-sync-all": {
            "task": "app.workers.tasks.sync_all_drives",
            "schedule": schedule(run_every=interval),
        },
        "reconcile-stale-processing": {
            "task": "app.workers.tasks.reconcile_stale_processing",
            "schedule": schedule(run_every=stale_interval),
        },
    }
    return app


celery_app = create_celery_app()

# Register tasks (import side effects: decorators bind to ``celery_app``).
import app.workers.tasks  # noqa: E402,F401
