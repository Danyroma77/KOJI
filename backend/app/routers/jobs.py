"""
Router Job — Esposizione dello stato di lavorazione (BE-RF-10).

GET /api/jobs — elenco job (pending/running/completed/error) con durata ed errore.
GET /api/jobs/{job_id} — dettaglio di un singolo job.
POST /api/jobs/{job_id}/retry — rimette in coda un job fallito.
POST /api/jobs/retry — rimette in coda tutti i job falliti.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models import JobDetail

router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobDetail])
async def list_jobs(
    status: str = Query(default=None, description="filtro stato: pending|running|completed|failed"),
    limit: int = Query(default=50, ge=1, le=500),
):
    """Elenco dei job con stato, progresso, durata ed eventuale errore."""
    from app.services.job_queue import job_queue
    jobs = job_queue.list_all(status=status)
    return [JobDetail(**j) for j in jobs[-limit:]]


@router.get("/{job_id}", response_model=JobDetail)
async def job_detail(job_id: str):
    """Dettaglio completo di un singolo job."""
    from app.services.job_queue import job_queue
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} non trovato")
    return JobDetail(**job.to_dict())


@router.post("/retry")
async def retry_all_failed():
    """Rimette in coda tutti i job falliti."""
    from app.services.job_queue import job_queue
    count = job_queue.retry_failed()
    return {"status": "ok", "retried": count}


@router.post("/{job_id}/retry")
async def retry_job(job_id: str):
    """Rimette in coda un singolo job fallito."""
    from app.services.job_queue import job_queue
    retried = job_queue.retry_job(job_id)
    if not retried:
        job = job_queue.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} non trovato")
        raise HTTPException(status_code=409, detail=f"Job {job_id} non è in stato failed")
    return {"status": "ok", "retried_job": job_id}