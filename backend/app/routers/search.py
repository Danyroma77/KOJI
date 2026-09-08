"""
=============================================================================
ROUTER RICERCA — RICERCA NELLA KNOWLEDGE BASE (BE-RF-12/13/14)
=============================================================================

Questo router espone l'endpoint per cercare chunk nella Knowledge Base
con diverse modalità di retrieval.

ENDPOINT:
POST /api/search — Ricerca con modalità selezionabile

MODALITÀ DI RICERCA:
- "dense": ricerca vettoriale (HNSW) basata su similarità semantica
- "bm25": ricerca lessicale (keyword) basata su corrispondenza esatta
- "hybrid": fusione RRF di dense + BM25 (default, miglior qualità)

RE-RANKING:
- Opzionale con cross-encoder (BE-RF-15)
- Riordina i candidati per migliorare la pertinenza
- Eseguito in thread separato per non bloccare l'API

METRICHE:
- Ogni ricerca viene registrata per il monitoraggio
- Latenza, numero risultati, dimensione indice
"""

from __future__ import annotations

import time
import logging

from fastapi import APIRouter, HTTPException

from app.config import settings
from app.models import (
    SearchQueryRequest,
    SearchResponse,
    SearchResultItem,
    SearchMode,
)
from app.services.vector_store import vector_store
from app.services.embedding_service import embedding_service
from app.services.metrics_store import metrics_store

logger = logging.getLogger("koji")

# Router con prefisso /api/search
router = APIRouter(prefix="/search", tags=["search"])


def _enrich_metadata(items: list[dict]) -> list[dict]:
    """
    Aggiunge i metadati ai risultati che non li hanno.
    
    Necessario per i risultati BM25-only che non includono metadati.
    Recupera i metadati da ChromaDB per ID mancanti.
    """
    missing = [i["id"] for i in items if not i.get("metadata")]
    if missing:
        got = vector_store.get_metadata_for_ids(missing)
        for item in items:
            if not item.get("metadata"):
                item["metadata"] = got.get(item["id"], {})
    return items


@router.post("", response_model=SearchResponse)
async def search(request: SearchQueryRequest):
    """
    Esegue una ricerca nella Knowledge Base.
    
    Args:
        request: SearchQueryRequest con query, modalità e parametri
        
    Returns:
        SearchResponse con risultati, punteggi e metriche
        
    Raises:
        422: Query vuota
        500: Errore durante la ricerca
        
    Note:
        - L'embedding della query è eseguito in thread separato (non blocca API)
        - Il re-ranking è opzionale e disabilitabile via configurazione
        - Le metriche vengono registrate per il monitoraggio
    """
    if not request.query.strip():
        raise HTTPException(status_code=422, detail="Query di ricerca vuota")

    t_start = time.time()
    mode = request.mode.value

    try:
        if mode == SearchMode.DENSE.value:
            # Ricerca vettoriale: embedding della query + HNSW
            query_embedding = await embedding_service.embed_query_async(request.query)
            results = vector_store.dense_search(
                query_embedding,
                top_k=request.top_k,
            )
            results = _enrich_metadata(results)
        elif mode == SearchMode.BM25.value:
            # Ricerca lessicale: matching esatto di parole
            results = vector_store.keyword_search(
                request.query,
                top_k=request.top_k,
            )
            results = _enrich_metadata(results)
        else:  # hybrid
            # Fusione RRF di dense + BM25
            query_embedding = await embedding_service.embed_query_async(request.query)
            results = vector_store.hybrid_search(
                query=request.query,
                query_embedding=query_embedding,
                top_k_dense=request.top_k_dense,
                top_k_keyword=request.top_k_keyword,
                rrf_k=request.rrf_k,
            )
    except Exception as e:
        logger.warning("Ricerca fallita: %s", e)
        raise HTTPException(status_code=500, detail=f"Errore ricerca: {str(e)[:200]}")

    # =========================================================================
    # RE-RANKING OPZIONALE CON CROSS-ENCODER (BE-RF-15)
    # =========================================================================
    # Il cross-encoder riordina i candidati per migliorare la pertinenza.
    # Eseguito in thread separato per non bloccare l'event loop.
    rerank_used = False
    if request.rerank or settings.RAG_RERANK_ENABLED:
        from app.services.rag_engine import rag_engine
        candidates = results[: (request.rerank_top_k or settings.RAG_RERANK_TOP_K)]
        if candidates:
            scores = await rag_engine.rerank_scores(
                request.query, [item["text"] for item in candidates]
            )
            if scores is not None:
                for item, score in zip(candidates, scores):
                    item["rerank_score"] = float(score)
                candidates.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
                results = candidates
                rerank_used = True
            else:
                logger.warning(
                    "Re-ranking non disponibile: si usa l'ordinamento del retriever"
                )

    latency_ms = (time.time() - t_start) * 1000

    # Registra metriche per monitoraggio
    try:
        index_size = vector_store.count
        metrics_store.record_retrieval(
            query=request.query,
            mode="rerank" if rerank_used else mode,
            latency_ms=latency_ms,
            num_results=len(results),
            index_size=index_size,
        )
    except Exception:
        pass

    # Costruisce risposta con tutti i punteggi
    items = [
        SearchResultItem(
            id=r["id"],
            text=r["text"],
            score=r.get("score", r.get("rrf_score", 0.0)),
            dense_score=r.get("dense_score"),
            keyword_score=r.get("keyword_score"),
            rrf_score=r.get("rrf_score"),
            rerank_score=r.get("rerank_score"),
            metadata=r.get("metadata", {}),
        )
        for r in results
    ]

    return SearchResponse(
        query=request.query,
        mode=mode,
        results=items,
        total=len(items),
        latency_ms=round(latency_ms, 2),
        rerank_used=rerank_used,
    )