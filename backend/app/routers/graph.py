"""
=============================================================================
ROUTER GRAPH — ENDPOINT PER IL KNOWLEDGE GRAPH
=============================================================================

Questo router espone endpoint per interrogare e rigenerare il Knowledge Graph,
un grafo semantico che rappresenta entità e relazioni estratte dai documenti.

ENDPOINT:
GET  /api/graph              — Restituisce grafo completo (nodi e archi)
GET  /api/graph/node/{id}    — Dettaglio nodo con storytelling e collegamenti
POST /api/graph/rebuild      — Rigenera grafo da documenti (job in background)

STRUTTURA GRAFO:
- Nodi: entità (persone, organizzazioni, concetti, luoghi, documenti)
- Archi: relazioni tra entità (es. "lavora per", "fa parte di", "ha sede a")
- Metadati: confidence, documenti di origine, tipo entità

ESTRAZIONE:
- Le entità sono estratte dai LLM durante il processing dei documenti
- Devono essere "grounded" (citazioni letterali nel testo)
- Confidence minima configurabile (default 0.7)
- Massimo 60 caratteri per etichetta (evita frasi intere)
"""

from __future__ import annotations
from fastapi import APIRouter, HTTPException

from app.models import GraphData, GraphNodeDetail
from app.services.graph_builder import graph_builder

# Router con prefisso /api/graph
router = APIRouter(prefix="/graph", tags=["graph"])


@router.get("", response_model=GraphData)
async def get_graph():
    """
    Restituisce il grafo completo con tutti i nodi e gli archi.
    
    Returns:
        GraphData con liste di nodi e archi
        
    Note:
        - I nodi contengono: id, label, type, degree, documents
        - Gli archi contengono: source, target, label, confidence
        - Il grafo è generato a runtime dai documenti indicizzati
    """
    graph = graph_builder.get_graph()
    return GraphData(nodes=graph["nodes"], edges=graph["edges"])


@router.get("/node/{node_id}", response_model=GraphNodeDetail)
async def get_node_detail(node_id: str):
    """
    Restituisce i dettagli di un singolo nodo del grafo.
    
    Args:
        node_id: Identificativo del nodo (slug dell'etichetta)
        
    Returns:
        GraphNodeDetail con storytelling, collegamenti e metadati
        
    Raises:
        404: Se il nodo non esiste nel grafo
    """
    detail = graph_builder.get_node_detail(node_id)
    if not detail:
        raise HTTPException(status_code=404, detail=f"Nodo {node_id} non trovato")
    return GraphNodeDetail(**detail)


@router.post("/rebuild")
async def rebuild_graph(reset: bool = True):
    """
    Rigenera il Knowledge Graph da tutti i documenti pronti.
    
    Args:
        reset: Se True (default), azzera il grafo prima della ri-estrazione
        
    Returns:
        Lista dei job IDs avviati per l'estrazione
        
    Note:
        - Con reset=true, nessuna entità stantia sopravvive
        - Il nuovo grafo contiene solo entità estratte dai documenti correnti
        - Ogni documento viene processato come job separato (non blocca l'API)
        - Stato consultabile via GET /api/jobs/{job_id}
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