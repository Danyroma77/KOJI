"""
Router Ricerca — Ricerca nella Knowledge Base (BE-RF-12/13/14).

POST /api/search — esegue ricerca Dense (HNSW), BM25 o Hybrid (RRF)
nella KB indicizzata e restituisce risultati rankati con punteggi e metadati.

La modalità Hybrid fonde i risultati densi e lessicali tramite Reciprocal
Rank Fusion come previsto dalla specifica operativa (sezione 8).
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

router = APIRouter(prefix="/search", tags=["search"])


def _enrich_metadata(items: list[dict]) -> list[dict]:
    """Aggiunge i metadati ai risultati che non li hanno (caso BM25-only)."""
    missing = [i["id"] for i in items if not i.get("metadata")]
    if missing:
        got = vector_store.get_metadata_for_ids(missing)
        for item in items:
            if not item.get("metadata"):
                item["metadata"] = got.get(item["id"], {})
    return items


@router.post("", response_model=SearchResponse)
async def search(request: SearchQueryRequest):
    """Ricerca nella Knowledge Base con modalità selezionabile.

    Mode ammesse: ``dense``, ``bm25``, ``hybrid`` (default).
    Con ``rerank=True`` si applica il cross-encoder sui candidati (BE-RF-15).
    """
    if not request.query.strip():
        raise HTTPException(status_code=422, detail="Query di ricerca vuota")

    t_start = time.time()
    mode = request.mode.value

    try:
        if mode == SearchMode.DENSE.value:
            # Embedding fuori dall'event loop (thread + timeout)
            query_embedding = await embedding_service.embed_query_async(request.query)
            results = vector_store.dense_search(
                query_embedding,
                top_k=request.top_k,
            )
            results = _enrich_metadata(results)
        elif mode == SearchMode.BM25.value:
            results = vector_store.keyword_search(
                request.query,
                top_k=request.top_k,
            )
            results = _enrich_metadata(results)
        else:  # hybrid
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

    # Re-ranking opzionale con cross-encoder (BE-RF-15, P1 "se configurato").
    # Il predict gira FUORI dall'event loop (thread + timeout) in
    # rag_engine.rerank_scores: bloccarlo qui congelerebbe l'intera API.
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

    # Registra la metrica di retrieval
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