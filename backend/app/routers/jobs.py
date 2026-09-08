"""
=============================================================================
ROUTER JOB — ESPOSIZIONE DELLO STATO DI LAVORAZIONE (BE-RF-10)
=============================================================================

Espone endpoint per monitorare e gestire i job di processing in background.

ENDPOINT:
GET  /api/jobs              — Elenco job (con filtro stato e paginazione)
GET  /api/jobs/{job_id}     — Dettaglio singolo job
POST /api/jobs/retry       — Rimette in coda tutti i job falliti
POST /api/jobs/{job_id}/retry — Rimette in coda un singolo job fallito

STATO JOB:
- pending: in attesa di essere processato
- running: in esecuzione dal worker
- completed: terminato con successo
- failed: terminato con errore (retry possibile)

USO:
- Monitoraggio elaborazione documenti
- Debug job falliti
- Retry manuale in caso di errori
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app.models import JobDetail

# Router con prefisso /api/jobs
router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.get("", response_model=list[JobDetail])
async def list_jobs(
    status: str = Query(default=None, description="filtro stato: pending|running|completed|failed"),
    limit: int = Query(default=50, ge=1, le=500),
):
    """
    Elenco dei job con stato, progresso, durata ed eventuale errore.
    
    Args:
        status: Filtro per stato (opzionale)
        limit: Numero massimo di risultati
        
    Returns:
        Lista di JobDetail ordinati per data creazione
    """
    from app.services.job_queue import job_queue
    jobs = job_queue.list_all(status=status)
    return [JobDetail(**j) for j in jobs[-limit:]]


@router.get("/{job_id}", response_model=JobDetail)
async def job_detail(job_id: str):
    """
    Dettaglio completo di un singolo job.
    
    Args:
        job_id: ID del job da consultare
        
    Returns:
        JobDetail con tutti i dati del job
        
    Raises:
        404: Se il job non esiste
    """
    from app.services.job_queue import job_queue
    job = job_queue.get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail=f"Job {job_id} non trovato")
    return JobDetail(**job.to_dict())


@router.post("/retry")
async def retry_all_failed():
    """
    Rimette in coda tutti i job falliti.
    
    Utile per ritentare elaborazioni fallite dopo aver risolto
    il problema che ha causato l'errore.
    
    Returns:
        Numero di job rimessi in coda
    """
    from app.services.job_queue import job_queue
    count = job_queue.retry_failed()
    return {"status": "ok", "retried": count}


@router.post("/{job_id}/retry")
async def retry_job(job_id: str):
    """
    Rimette in coda un singolo job fallito.
    
    Args:
        job_id: ID del job da rimettere in coda
        
    Returns:
        Conferma dell'operazione
        
    Raises:
        404: Se il job non esiste
        409: Se il job non è in stato failed
    """
    from app.services.job_queue import job_queue
    retried = job_queue.retry_job(job_id)
    if not retried:
        job = job_queue.get_job(job_id)
        if not job:
            raise HTTPException(status_code=404, detail=f"Job {job_id} non trovato")
        raise HTTPException(status_code=409, detail=f"Job {job_id} non è in stato failed")
    return {"status": "ok", "retried_job": job_id}