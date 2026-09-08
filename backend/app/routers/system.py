"""
=============================================================================
ROUTER SISTEMA — METRICHE E STATO DEI SERVIZI
=============================================================================

Espone endpoint per ottenere stato e metriche del sistema.

ENDPOINT:
GET /api/system/status   — Stato semplificato dei servizi
GET /api/system/metrics  — Metriche complete di sistema

USO:
- Health check servizi
- Dashboard admin
- Monitoraggio risorse
"""

from fastapi import APIRouter

from app.models import ServiceStatusResponse
from app.services.monitor import get_service_status

# Router con prefisso /api/system
router = APIRouter(prefix="/system", tags=["system"])


@router.get("/status")
async def service_status():
    """
    Stato dei servizi core.
    
    Returns:
        Stato di Ollama, ChromaDB, File Store e API
    """
    data = await get_service_status()
    return ServiceStatusResponse(**data)


@router.get("/metrics")
async def system_metrics():
    """
    Metriche complete di sistema.
    
    Returns:
        Metriche CPU, RAM, VRAM e stato servizi
    """
    from app.models import SystemMetrics
    from app.services.monitor import get_system_metrics
    data = await get_system_metrics()
    return SystemMetrics(**data)