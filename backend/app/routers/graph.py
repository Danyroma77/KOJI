"""
Router Graph — Endpoint per il Knowledge Graph.
"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException

from app.models import GraphData, GraphNodeDetail
from app.services.graph_builder import graph_builder

router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("", response_model=GraphData)
async def get_graph():
    """Restituisce il grafo completo (nodi e archi)."""
    graph = graph_builder.get_graph()
    return GraphData(nodes=graph["nodes"], edges=graph["edges"])


@router.get("/node/{node_id}", response_model=GraphNodeDetail)
async def get_node_detail(node_id: str):
    """Restituisce dettagli di un singolo nodo con storytelling e collegamenti."""
    detail = graph_builder.get_node_detail(node_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Nodo {node_id} non trovato")
    return GraphNodeDetail(**detail)


@router.post("/rebuild")
async def rebuild_graph(reset: bool = True):
    """Rigenera il grafo a runtime da tutti i documenti processati.

    Con reset=true (default) il grafo esistente viene azzerato PRIMA della
    ri-estrazione: nessuna entità stantia sopravvive — il nuovo grafo
    contiene solo entità estratte dai documenti correnti e ancorate al
    loro testo. Ogni documento viene riprocessato come job separato per
    non bloccare l'API; stato consultabile via /api/jobs/{job_id}.
    """
    from app.services.job_queue import job_queue
    from app.routers.documents import _load_catalog

    catalog = _load_catalog()
    ready_docs = [d for d in catalog.get("documents", [])
                  if d.get("status") == "ready"]
    if not ready_docs:
        if reset:
            graph_builder.reset()
        return {"status": "ok", "job_id": None, "reset": reset,
                "message": "Nessun documento pronto per l'estrazione del grafo"}

    if reset:
        graph_builder.reset()

    jobs = []
    for doc in ready_docs:
        job = job_queue.enqueue("generate_graph", {
            "doc_id": doc["id"],
            "filename": doc.get("filename", "documento"),
        })
        jobs.append(job.id)

    return {
        "status": "ok",
        "job_ids": jobs,
        "reset": reset,
        "message": f"Rigenerazione runtime del grafo avviata per {len(jobs)} documenti"
                   + (" (grafo azzerato, entità ri-estratte dal testo)" if reset else ""),
    }