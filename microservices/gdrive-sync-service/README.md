# gdrive-sync-service

Syncs video-like files (including `.h265` / `application/octet-stream`) from multiple Google Drive folders (service accounts) into a configurable MinIO bucket (production: **`chess-ai`**) under optional per-drive **`object_prefix`** (e.g. `video/Rehovot`), with PostgreSQL as source of truth.

## Quick start (local)

1. Copy `config/config.example.yaml` and `.env.example` to real paths (do not commit secrets).
2. `pip install -e ".[dev]"` from this directory.
3. Run migrations: `alembic upgrade head`.
4. API: `uvicorn app.main:app --host 0.0.0.0 --port 8080`.
5. Worker: `celery -A app.workers.celery_app worker -Q sync,upload -l info`.
6. Beat: `celery -A app.workers.celery_app beat -l info`.

Use `docker compose up` from this directory for Postgres, Redis, MinIO, API, worker, and beat.

## Environment

See [.env.example](.env.example). Drive credentials JSON paths are referenced from `config.yaml`, not from the repo.

## Docker compose integration

1. Copy `config/config.example.yaml` to `config/drives.yaml` and fill `folder_id` + mount service account JSON under `./secrets/`.
2. Copy `.env.example` to `.env`.
3. Run migrations once:

```bash
docker compose run --rm gdrive-sync-api alembic upgrade head
```

4. `docker compose up -d`

The upload pipeline calls `ensure_bucket` before writes so the `videos` bucket is created automatically when credentials allow it.

## Monorepo note

When this folder is merged into `chessverse-monorepo`, align `Dockerfile`/`compose` naming with existing `train` / `splitter` services and reuse shared logging/config utilities if present.
