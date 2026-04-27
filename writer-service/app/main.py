from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .db import engine, AsyncSessionLocal
from .models import Base
from .redis_client import close_redis, get_redis

from .routes import orders
from .seeder import Seeder
from .rabbit_publisher import rabbit_connect, rabbit_close

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    force=True,
)

logger = logging.getLogger(__name__)
logging.getLogger("pika").setLevel(logging.WARNING)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Crear tablas en la bd
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed Base datos y redis
    try:
        redis = await get_redis()
        async with AsyncSessionLocal() as session:
            seeder = Seeder(session, redis)
            await seeder.seed()
    except Exception as exc:
        logger.error(f"[Seeder] Error: {exc}", exc_info=True)

    rabbit_connect()

    yield
    await close_redis()
    rabbit_close()


app = FastAPI(title="writer-service", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(orders.router)


@app.get("/health", tags=["ops"])
async def health() -> JSONResponse:
    checks: dict[str, str] = {}

    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        checks["postgres"] = f"error: {exc}"

    try:
        r = await get_redis()
        await r.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    http_status = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(
        content={"status": "ok" if all_ok else "degraded", "checks": checks},
        status_code=http_status,
    )
