"""
Router Benchmark — Esecuzione e consultazione di esperimenti (BE-RF-22).

POST /api/benchmarks/run — avvia una run con configurazione data.
GET  /api/benchmarks — elenco run (stato/risultati sintetici).
GET  /api/benchmarks/{id} — stato/risultati completi di una run.
DELETE /api/benchmarks/{id} — elimina una run (best-effort).
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Query

from app.models import (
    BenchmarkConfig,
    BenchmarkRunSummary,
    BenchmarkStartResponse,
)
from app.services.benchmark import benchmark_service

router = APIRouter(prefix="/benchmarks", tags=["benchmarks"])


@router.post("/run", response_model=BenchmarkStartResponse)
async def run_benchmark(config: BenchmarkConfig):
    """Creazione e avvio asincrono di una run benchmark.

    La run prosegue in background; lo stato è consultabile via
    GET /api/benchmarks/{id}. Persistita su disco (riproducibilità).
    """
    run = benchmark_service.create_run(config)
    # Avvia la run in background senza bloccare la risposta
    asyncio.create_task(benchmark_service.start_run(run, config))
    return BenchmarkStartResponse(
        run_id=run["run_id"],
        experiment=config.experiment.value,
        status=run["status"],
        message="Benchmark avviato — stato consultabile su /api/benchmarks/{id}",
    )


@router.get("", response_model=list[BenchmarkRunSummary])
async def list_benchmark_runs(
    experiment: str = Query(default=None, description="filtro esperimento E1..E7"),
):
    """Elenco delle run di benchmark (dalla più recente)."""
    runs = benchmark_service.list_runs()
    if experiment:
        runs = [r for r in runs if r.get("experiment") == experiment]
    out = []
    for r in runs:
        out.append(BenchmarkRunSummary(
            run_id=r["run_id"],
            experiment=r["experiment"],
            label=r.get("label"),
            status=r["status"],
            started_at=r.get("started_at"),
            finished_at=r.get("finished_at"),
            error=r.get("error"),
            duration_s=r.get("duration_s"),
            summary=r.get("summary") or {},
        ))
    return out


@router.get("/{run_id}")
async def benchmark_run_detail(run_id: str):
    """Stato/risultati completi di una singola run."""
    run = benchmark_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run benchmark {run_id} non trovata")
    return run


@router.delete("/{run_id}")
async def delete_benchmark_run(run_id: str):
    """Elimina una run benchmark persistita (solo se non in esecuzione)."""
    run = benchmark_service.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run benchmark {run_id} non trovata")
    if run.get("status") == "running":
        raise HTTPException(status_code=409, detail="Impossibile eliminare una run in esecuzione")
    try:
        path = benchmark_service._path(run_id)
        path.unlink(missing_ok=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return {"status": "ok", "deleted": run_id}