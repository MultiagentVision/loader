from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.files_route import router as files_router
from app.api.health import router as health_router
from app.api.sync_route import router as sync_router
from app.core.logging_config import configure_logging
from app.core.settings import get_settings
from app.db.session import create_engine, create_session_maker


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    settings = get_settings()
    engine = create_engine(settings)
    app.state.settings = settings
    app.state.session_maker = create_session_maker(engine)
    yield
    await engine.dispose()


app = FastAPI(title="gdrive-sync-service", lifespan=lifespan)
app.include_router(health_router)
app.include_router(sync_router)
app.include_router(files_router)
