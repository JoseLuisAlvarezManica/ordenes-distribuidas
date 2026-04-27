import logging
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class AnalyticsClient:
    def __init__(self, session: httpx.AsyncClient):
        self.session = session

    async def get(self, endpoint: str, headers: dict | None = None):
        logger.info("AnalyticsClient GET %s", endpoint)
        response = await self.session.get(endpoint, headers=headers or {})
        response.raise_for_status()
        return response.json()

    async def get_analytics(self):
        return await self.get("/analytics")


async def get_analytics_client():
    async with httpx.AsyncClient(
        base_url=settings.analytics_service_url,
        timeout=10.0,
    ) as session:
        yield AnalyticsClient(session)
