"""
Router RAG — Interrogazione della Knowledge Base con SSE streaming.
"""

from __future__ import annotations
import json
import logging
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.models import RAGQuery
from app.services.rag_engine import rag_engine

logger = logging.getLogger("koji")

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/query")
async def query_rag(request: RAGQuery):
    """Interroga la KB e restituisce la risposta in streaming SSE.

    Ogni evento SSE è un JSON con campo "type":
    - "status": fase in corso (retrieval/generation) per feedback immediato
    - "sources": elenco fonti recuperate
    - "token": singolo token generato
    - "metrics": metriche di prestazione
    - "error": messaggio d'errore (es. Ollama non raggiungibile) — la
      richiesta non resta mai sospesa senza risposta
    - "done": segnale di fine
    """
    async def event_generator():
        try:
            async for event in rag_engine.query_stream(
                question=request.question,
                model=request.model,
                top_k=request.top_k,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
                retrieval_mode=request.retrieval_mode,
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            # L'errore viene SEMPRE comunicato al client come evento SSE:
            # la richiesta non resta mai sospesa senza risposta.
            logger.exception("Errore nel flusso RAG: %s", e)
            error_event = {"type": "error", "message": str(e)}
            yield f"data: {json.dumps(error_event, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )