"""
Router Sistema — Metriche e stato dei servizi.
"""

from fastapi import APIRouter

from app.models import ServiceStatusResponse
from app.services.monitor import get_service_status

router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
async def service_status():
    """Stato dei servizi core."""
    data = await get_service_status()
    return ServiceStatusResponse(**data)


@router.get("/metrics")
async def system_metrics():
    """Metriche complete di sistema."""
    from app.models import SystemMetrics
    from app.services.monitor import get_system_metrics
    data = await get_system_metrics()
    return SystemMetrics(**data)