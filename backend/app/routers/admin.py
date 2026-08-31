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
        "chunk_strategy": settings.CHUNK_STRATEGY,
        "chunk_size": settings.CHUNK_SIZE,
        "chunk_overlap_pct": settings.CHUNK_OVERLAP_PCT,
        "embedding_model": settings.EMBEDDING_MODEL,
        "hnsw_m": settings.HNSW_M,
        "hnsw_ef_construction": settings.HNSW_EF_CONSTRUCTION,
        "graph_confidence_threshold": settings.GRAPH_CONFIDENCE_THRESHOLD,
        "graph_require_grounding": settings.GRAPH_REQUIRE_GROUNDING,
        "graph_max_entity_chars": settings.GRAPH_MAX_ENTITY_CHARS,
        "metrics_interval_sec": settings.METRICS_INTERVAL_SEC,
        "ollama_model": settings.OLLAMA_MODEL,
        "dataset_name": settings.DATASET_NAME,
        "rag_top_k_final": settings.RAG_TOP_K_FINAL,
        "rag_top_k_dense": settings.RAG_TOP_K_DENSE,
        "rag_top_k_keyword": settings.RAG_TOP_K_KEYWORD,
        "rag_rrf_k": settings.RAG_RRF_K,
        "rag_rerank_top_k": settings.RAG_RERANK_TOP_K,
        "rag_rerank_enabled": settings.RAG_RERANK_ENABLED,
        "rag_retrieval_mode": settings.RAG_RETRIEVAL_MODE,
        "rag_temperature": settings.RAG_TEMPERATURE,
        "rag_max_tokens": settings.RAG_MAX_TOKENS,
        "max_upload_size_mb": settings.MAX_UPLOAD_SIZE_MB,
    }


@router.put("/config")
async def update_config(update: AdminConfigUpdate):
    """Aggiorna i parametri di configurazione.

    Nota: i parametri di chunking (strategia, dimensione, overlap) sono
    letti a ogni elaborazione — l'effetto è immediato per i NUOVI documenti.
    I chunk già indicizzati non vengono ricreati: ri-processare i documenti
    per rigenerarli con la nuova configurazione.
    """
    if update.chunk_strategy is not None:
        settings.CHUNK_STRATEGY = settings.parse_chunk_strategy(update.chunk_strategy)
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
    if update.graph_require_grounding is not None:
        settings.GRAPH_REQUIRE_GROUNDING = update.graph_require_grounding
    if update.graph_max_entity_chars is not None:
        settings.GRAPH_MAX_ENTITY_CHARS = update.graph_max_entity_chars
    if update.metrics_interval_sec is not None:
        settings.METRICS_INTERVAL_SEC = update.metrics_interval_sec
    if update.rag_top_k_dense is not None:
        settings.RAG_TOP_K_DENSE = update.rag_top_k_dense
    if update.rag_top_k_keyword is not None:
        settings.RAG_TOP_K_KEYWORD = update.rag_top_k_keyword
    if update.rag_top_k_final is not None:
        settings.RAG_TOP_K_FINAL = update.rag_top_k_final
    if update.rag_rrf_k is not None:
        settings.RAG_RRF_K = update.rag_rrf_k
    if update.rag_rerank_top_k is not None:
        settings.RAG_RERANK_TOP_K = update.rag_rerank_top_k
    if update.rag_rerank_enabled is not None:
        settings.RAG_RERANK_ENABLED = update.rag_rerank_enabled
    if update.rag_retrieval_mode is not None:
        settings.RAG_RETRIEVAL_MODE = settings.parse_retrieval_mode(update.rag_retrieval_mode)
    if update.rag_temperature is not None:
        settings.RAG_TEMPERATURE = update.rag_temperature
    if update.rag_max_tokens is not None:
        settings.RAG_MAX_TOKENS = update.rag_max_tokens
    if update.max_upload_size_mb is not None:
        settings.MAX_UPLOAD_SIZE_MB = update.max_upload_size_mb

    return {"status": "ok", "message": "Configurazione aggiornata"}