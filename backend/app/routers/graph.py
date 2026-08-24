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
async def rebuild_graph():
    """Ricostruisce il grafo da tutti i documenti processati (operazione lunga)."""
    from app.routers.documents import _load_catalog
    from app.services.graph_builder import graph_builder

    catalog = _load_catalog()
    # In produzione: avviare come background task
    return {"status": "not_implemented", "message": "Usare il processing documenti per aggiornare il grafo"}