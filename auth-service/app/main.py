from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from sqlalchemy import text

from .db import engine
from .models import Base
from .redis_client import close_redis, get_redis

from .routes import users

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    try:
        await get_redis()
    except Exception as exc:
        logger.error(f"[Redis] Error al conectar: {exc}", exc_info=True)

    yield
    await close_redis()


app = FastAPI(title="auth-service", lifespan=lifespan)
app.include_router(users.router)


@app.get("/health", tags=["ops"])
async def health() -> JSONResponse:
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    http_status = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        content={"status": "ok" if all_ok else "degraded", "checks": checks},
        status_code=http_status,
    )
