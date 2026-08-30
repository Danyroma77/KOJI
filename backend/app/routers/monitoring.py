"""
Router Monitoring — Metriche live della piattaforma (BE-RF-21).

GET /api/monitoring/live — snapshot corrente: metriche di sistema (CPU/RAM/VRAM),
stato servizi, statistiche retrieval (latenza media, risultati, dimensione
indice), metriche LLM (tok/s, first-token, durata), fasi del processing e
conteggi dei job.

Le metriche RAG/ricerca vengono accumulate a runtime dal MetricsStore;
quelle di sistema vengono misurate al momento della richiesta.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.services.monitor import get_system_metrics, get_service_status
from app.services.metrics_store import metrics_store

router = APIRouter(prefix="/monitoring", tags=["monitoring"])


@router.get("/live")
async def monitoring_live():
    """Metriche correnti aggregate per la dashboard di monitoraggio."""
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
    """Alias di /api/system/metrics per compatibilità della dashboard."""
    return await get_system_metrics()