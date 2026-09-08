"""
=============================================================================
ROUTER RAG — INTERROGAZIONE DELLA KNOWLEDGE BASE CON SSE STREAMING
=============================================================================

Questo router espone l'endpoint per interrogare la Knowledge Base tramite
RAG (Retrieval-Augmented Generation) con risposta in streaming.

ENDPOINT:
POST /api/rag/query — Interroga la KB e ricevi risposta in tempo reale

FLUSSO RAG:
1. Ricezione domanda utente
2. Generazione embedding della query
3. Retrieval chunk pertinenti (dense, BM25, o hybrid)
4. Re-ranking con cross-encoder (opzionale)
5. Assemblaggio prompt con contesto
6. Streaming risposta da LLM (token per token)

EVENTI SSE:
- "status": fase in corso (retrieval/generation) per feedback immediato
- "sources": elenco fonti recuperate con punteggi
- "token": singolo token generato dal LLM
- "metrics": metriche di prestazione (tok/s, TTFT, latency)
- "error": messaggio d'errore (mai silenzio: l'errore è sempre comunicato)
- "done": segnale di fine generazione

VANTAGGI SSE:
- Feedback immediato all'utente (la risposta appare progressivamente)
- Possibilità di mostrare spinner/loading durante il retrieval
- Connessione persistente per aggiornamenti in tempo reale
"""

from __future__ import annotations
import json
import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.models import RAGQuery
from app.services.rag_engine import rag_engine

logger = logging.getLogger("koji")

# Router con prefisso /api/rag
router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/query")
async def query_rag(request: RAGQuery):
    """
    Interroga la Knowledge Base tramite RAG con risposta in streaming SSE.
    
    Args:
        request: RAGQuery con domanda e parametri opzionali (model, top_k, etc.)
        
    Returns:
        StreamingResponse con eventi SSE
        
    Note:
        - L'errore è SEMPRE comunicato come evento SSE (mai silenzio)
        - I header disabilitano il buffering per garantire streaming reale
        - La connessione rimane aperta fino a fine generazione
    """
    async def event_generator():
        """Generatore di eventi SSE per la risposta streaming."""
        try:
            # Itera sugli eventi prodotti dal RAG engine
            async for event in rag_engine.query_stream(
                question=request.question,
                model=request.model,
                top_k=request.top_k,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                retrieval_mode=request.retrieval_mode,
            ):
                # Ogni evento è serializzato come JSON in formato SSE
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            # GARANZIA: l'errore è sempre comunicato al client
            # La richiesta non resta mai sospesa senza risposta
            logger.exception("Errore nel flusso RAG: %s", e)
            error_event = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",      # Disabilita cache
            "Connection": "keep-alive",        # Mantieni connessione aperta
            "X-Accel-Buffering": "no",         # Disabilita buffering nginx
        },
    )