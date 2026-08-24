"""
Router RAG — Interrogazione della Knowledge Base con SSE streaming.
"""

from __future__ import annotations
import json
from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from app.models import RAGQuery
from app.services.rag_engine import rag_engine

router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/query")
async def query_rag(request: RAGQuery):
    """Interroga la KB e restituisce la risposta in streaming SSE.

    Ogni evento SSE è un JSON con campo "type":
    - "sources": elenco fonti recuperate
    - "token": singolo token generato
    - "metrics": metriche di prestazione
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
            ):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
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