from contextlib import asynccontextmanager

from fastapi import FastAPI, status
from fastapi.responses import JSONResponse

from .redis_client import close_redis, get_redis


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await close_redis()


app = FastAPI(title="api-gateway", lifespan=lifespan)

@app.get("/health", tags=["ops"])
async def health() -> JSONResponse:
    checks: dict[str, str] = {}

    try:
        r = await get_redis()
        await r.ping()
        checks["redis"] = "ok"
    except Exception as exc: 
        checks["redis"] = f"error: {exc}"

    all_ok = all(v == "ok" for v in checks.values())
    http_status = status.HTTP_200_OK if all_ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return JSONResponse(content={"status": "ok" if all_ok else "degraded", "checks": checks}, status_code=http_status)
