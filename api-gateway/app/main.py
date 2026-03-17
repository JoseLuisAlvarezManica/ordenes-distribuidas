from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import FastAPI, status, Depends
from fastapi.responses import JSONResponse

import redis.asyncio as aioredis
from .redis_client import close_redis, get_redis
from .routes.orders import router as orders_router

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("pika").setLevel(logging.WARNING)

redis_dependency = Annotated[aioredis.Redis, Depends(get_redis)]

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_redis()


app = FastAPI(title="api-gateway", lifespan=lifespan)
app.include_router(orders_router)

@app.get("/health", tags=["ops"])
async def health(redis: redis_dependency) -> JSONResponse:
    checks: dict[str, str] = {}

    try:
        await redis.ping()
        checks["redis"] = "ok"
    except Exception as exc: 
        checks["redis"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    http_status = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content={"status": "ok" if all_ok else "degraded", "checks": checks}, status_code=http_status)