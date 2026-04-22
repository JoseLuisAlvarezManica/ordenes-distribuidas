import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)

class WriterClient:

    def __init__(self, session: httpx.AsyncClient):
        self.session = session
        self.max_retries = settings.writer_max_retries

    async def post(self, endpoint: str, data: dict, headers: dict | None = None):
        request_id = (headers or {}).get("X-Request-Id", "N/A")
        retries = max(0, self.max_retries)
        total_attempts = retries + 1
        for attempt in range(total_attempts):
            try:
                logger.info("Enviando a writer %s intento=%d [X-Request-Id: %s]", endpoint, attempt + 1, request_id)
                response = await self.session.post(endpoint, json=data, headers=headers)
                response.raise_for_status()
                logger.info("Writer respondió %d [X-Request-Id: %s]", response.status_code, request_id)
                return response.json()
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                logger.warning("Intento %d fallido: %s [X-Request-Id: %s]", attempt + 1, exc, request_id)
        raise Exception("Max retries exceeded")

    async def get(self, endpoint: str, headers: dict | None = None):
        request_id = (headers or {}).get("X-Request-Id", "N/A")
        retries = max(0, self.max_retries)
        total_attempts = retries + 1
        for attempt in range(total_attempts):
            try:
                logger.info("GET a writer %s intento=%d [X-Request-Id: %s]", endpoint, attempt + 1, request_id)
                response = await self.session.get(endpoint, headers=headers)
                response.raise_for_status()
                logger.info("Writer respondió %d [X-Request-Id: %s]", response.status_code, request_id)
                return response.json()
            except (httpx.HTTPStatusError, httpx.TransportError) as exc:
                logger.warning("Intento %d fallido GET: %s [X-Request-Id: %s]", attempt + 1, exc, request_id)
        raise Exception("Max retries exceeded")

# Inyección de dependencia, solo hable un cliente por request
async def get_writer_client():
    async with httpx.AsyncClient(
        base_url=settings.writer_service_url,
        timeout=settings.writer_timeout_seconds,
    ) as session:
        yield WriterClient(session)
