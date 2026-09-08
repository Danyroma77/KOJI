"""
=============================================================================
ROUTER MONITORING — METRICHE LIVE DELLA PIATTAFORMA (BE-RF-21)
=============================================================================

Espone endpoint per ottenere metriche aggregate della piattaforma.

ENDPOINT:
GET /api/monitoring/live    — Snapshot completo per dashboard
GET /api/monitoring/metrics — Solo metriche di sistema (alias)

METRICHE ESPOSTE:
- Sistema: CPU, RAM, VRAM
- Servizi: Ollama, ChromaDB, File Store
- Retrieval: latenza media, numero risultati
- LLM: tok/s, TTFT, durata
- Processing: durata per fase
- Job: conteggi per stato
- Uptime: tempo dall'avvio
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services.monitor import get_system_metrics, get_service_status
from app.services.metrics_store import metrics_store

# Router con prefisso /api/monitoring
router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/live")
async def monitoring_live():
    """
    Metriche correnti aggregate per la dashboard di monitoraggio.
    
    Returns:
        Dict con tutte le metriche della pittaforma
        
    Include:
        - Metriche di sistema (CPU, RAM, VRAM)
        - Stato servizi
        - Statistiche retrieval
        - Metriche LLM
        - Tempi processing
        - Conteggi job
        - Uptime
    """
    system_metrics = await get_system_metrics()
    services = await get_service_status()

    # Conteggi job dalla coda persistente (BE-RF-10)
    from app.services.job_queue import job_queue
    jobs = job_queue.list_all()
    job_counts = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
    for j in jobs:
        job_counts[j["status"]] = job_counts.get(j["status"], 0) + 1

    return {
        "system": system_metrics,
        "services": services,
        "retrieval": metrics_store.retrieval_summary(),
        "llm": metrics_store.llm_summary(),
        "processing": metrics_store.processing_summary(),
        "jobs": job_counts,
        "uptime_s": round(metrics_store.uptime_s(), 1),
    }


@router.get("/metrics")
async def system_metrics_endpoint():
    """
    Alias di /api/system/metrics per compatibilità della dashboard.
    
    Returns:
        Solo metriche di sistema (CPU, RAM, VRAM, servizi)
    """
    return await get_system_metrics()