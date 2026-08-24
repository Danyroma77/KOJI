"""
Router Admin — Configurazione dei parametri della piattaforma.
"""

from __future__ import annotations
from fastapi import APIRouter

from app.models import AdminConfigUpdate
from app.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/config")
async def get_config():
    """Restituisce la configurazione attuale (esclusi segreti)."""
    return {
        "chunk_size": settings.CHUNK_SIZE,
        "chunk_overlap_pct": settings.CHUNK_OVERLAP_PCT,
        "embedding_model": settings.EMBEDDING_MODEL,
        "hnsw_m": settings.HNSW_M,
        "hnsw_ef_construction": settings.HNSW_EF_CONSTRUCTION,
        "graph_confidence_threshold": settings.GRAPH_CONFIDENCE_THRESHOLD,
        "metrics_interval_sec": settings.METRICS_INTERVAL_SEC,
        "ollama_model": settings.OLLAMA_MODEL,
        "dataset_name": settings.DATASET_NAME,
        "rag_top_k_final": settings.RAG_TOP_K_FINAL,
        "rag_temperature": settings.RAG_TEMPERATURE,
    }


@router.put("/config")
async def update_config(update: AdminConfigUpdate):
    """Aggiorna i parametri di configurazione.

    Nota: le modifiche sono effettive per le nuove operazioni.
    I parametri già in uso da singoliton (es. chunk_manager)
    non vengono ricreati — riavviare il container per applicare tutti i cambiamenti.
    """
    if update.chunk_size is not None:
        settings.CHUNK_SIZE = update.chunk_size
    if update.chunk_overlap_pct is not None:
        settings.CHUNK_OVERLAP_PCT = update.chunk_overlap_pct
    if update.embedding_model is not None:
        settings.EMBEDDING_MODEL = update.embedding_model
    if update.hnsw_m is not None:
        settings.HNSW_M = update.hnsw_m
    if update.hnsw_ef_construction is not None:
        settings.HNSW_EF_CONSTRUCTION = update.hnsw_ef_construction
    if update.graph_confidence_threshold is not None:
        settings.GRAPH_CONFIDENCE_THRESHOLD = update.graph_confidence_threshold
    if update.metrics_interval_sec is not None:
        settings.METRICS_INTERVAL_SEC = update.metrics_interval_sec

    return {"status": "ok", "message": "Configurazione aggiornata"}