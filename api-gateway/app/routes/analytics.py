from typing import Annotated
import logging
from fastapi import APIRouter, Depends, HTTPException, Request, status
from ..decorators import must_be_admin, bearer_scheme
from ..schemas import AnalyticsResponse
from ..services.analytics_client import AnalyticsClient, get_analytics_client


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/analytics", tags=["analytics"])

analytics_dependency = Annotated[AnalyticsClient, Depends(get_analytics_client)]

@router.get("/", response_model=AnalyticsResponse)
@must_be_admin
async def get_analytics(
    request: Request,
    analytics_client: analytics_dependency,
) -> AnalyticsResponse:
    try:
        data = await analytics_client.get_analytics()
        return AnalyticsResponse(**data)
    except Exception as exc:
        logger.error("Error obteniendo analytics: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Error obteniendo analytics",
        )
