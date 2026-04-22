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
        return response.status_code, response.json()


async def get_analytics_client():
    async with httpx.AsyncClient(
        base_url=settings.analytics_service_url,
        timeout=10.0,
    ) as session:
        yield AnalyticsClient(session)
