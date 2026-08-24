"""
RAG Engine — Motore principale di interrogazione.
Hybrid Retrieval → Re-ranking → Prompt assembly → LLM → Risposta con citazioni.
"""

from __future__ import annotations
import time
import re
from dataclasses import dataclass
from typing import Optional

from app.config import settings
from app.services.vector_store import vector_store
from app.services.embedding_service import embedding_service
from app.services.llm_manager import llm_manager


@dataclass
class RAGResult:
    """Risultato completo di una query RAG."""
    answer: str
    sources: list[dict]
    metrics: dict


RAG_SYSTEM_PROMPT = """Sei un assistente specializzato nella consultazione di documenti amministrativi.
Rispondi alla domanda dell'utente ESCLUSIVAMENTE basandoti sul contesto fornito.
Regole:
- Se il contesto non contiene informazioni sufficienti, dichiara esplicitamente di non avere dati a disposizione.
- Non inventare informazioni. Non fare inferenze non supportate dai documenti.
- Cita le fonti usando il formato [N] dove N è il numero della fonte.
- Rispondi in italiano, in modo chiaro e strutturato.
- Se ci sono dati numerici (date, importi, percentuali), riportali con precisione.
"""

RAG_CONTEXT_TEMPLATE = """CONTESTO:
{chunks}

DOMANDA: {question}

Risposta:"""


class RAGEngine:
    """Motore RAG con hybrid retrieval e re-ranking."""

    def __init__(self):
        self._reranker = None

    @property
    def reranker(self):
        """Lazy loading del cross-encoder per re-ranking."""
        if self._reranker is None:
            from sentence_transformers import CrossEncoder
            self._reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        return self._reranker

    async def query(
        self,
        question: str,
        model: Optional[str] = None,
        top_k: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> RAGResult:
        """Esegue una query RAG completa.

        Args:
            question: Domanda in linguaggio naturale.
            model: Modello LLM da usare (default da config).
            top_k: Numero di chunk finali per il contesto.
            temperature: Temperatura di generazione.
            max_tokens: Token massimi nella risposta.

        Returns:
            RAGResult con risposta, fonti e metriche.
        """
        top_k = top_k or settings.RAG_TOP_K_FINAL
        t_start = time.time()

        # 1. Embedding della query
        t_embed = time.time()
        query_embedding = embedding_service.embed_query(question)
        t_embed_done = time.time()

        # 2. Hybrid Retrieval (dense + keyword → RRF)
        t_retrieve = time.time()
        hybrid_results = vector_store.hybrid_search(
            query=question,
            query_embedding=query_embedding,
        )
        t_retrieve_done = time.time()

        # 3. Re-ranking con cross-encoder sui top-20
        t_rerank = time.time()
        candidates = hybrid_results[:20]
        if candidates:
            pairs = [(question, item["text"]) for item in candidates]
            scores = self.reranker.predict(pairs)
            for item, score in zip(candidates, scores):
                item["rerank_score"] = float(score)
            candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
        final_chunks = candidates[:top_k]
        t_rerank_done = time.time()

        # 4. Assemblaggio contesto con citazioni
        context_parts = []
        sources = []
        for i, chunk in enumerate(final_chunks, start=1):
            ref = f"[{i}]"
            doc_name = chunk.get("metadata", {}).get("doc_name", "Sconosciuto")
            location = chunk.get("metadata", {}).get("location", "")
            context_parts.append(f"{ref} {chunk['text']}")
            sources.append({
                "ref": ref,
                "document_name": doc_name,
                "location": location,
                "chunk_id": chunk["id"],
                "score": round(chunk.get("rerank_score", chunk.get("rrf_score", 0)), 4),
                "snippet": chunk["text"][:200] + "..." if len(chunk["text"]) > 200 else chunk["text"],
            })

        context = "\n\n---\n\n".join(context_parts)
        prompt = RAG_SYSTEM_PROMPT + "\n\n" + RAG_CONTEXT_TEMPLATE.format(
            chunks=context,
            question=question,
        )

        # 5. Generazione LLM con streaming
        t_gen = time.time()
        full_answer = ""
        token_count = 0
        async for token in llm_manager.generate_stream(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            full_answer += token
            token_count += 1
        t_gen_done = time.time()

        # 6. Metriche
        t_total = t_gen_done - t_start
        ttft = t_gen - t_gen  # Non misurabile con questo approccio semplificato
        tok_per_sec = token_count / max(t_gen_done - t_gen, 0.001)

        metrics = {
            "total_time_ms": round(t_total * 1000, 1),
            "embedding_time_ms": round((t_embed_done - t_embed) * 1000, 1),
            "retrieval_time_ms": round((t_retrieve_done - t_retrieve) * 1000, 1),
            "rerank_time_ms": round((t_rerank_done - t_rerank) * 1000, 1),
            "generation_time_ms": round((t_gen_done - t_gen) * 1000, 1),
            "tok_per_sec": round(tok_per_sec, 1),
            "ttft_ms": round((t_gen - t_start) * 1000, 1),
            "tokens_generated": token_count,
            "chunks_retrieved": len(hybrid_results),
            "chunks_after_rerank": len(final_chunks),
        }

        return RAGResult(
            answer=full_answer.strip(),
            sources=sources,
            metrics=metrics,
        )

    async def query_stream(
        self,
        question: str,
        model: Optional[str] = None,
        top_k: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ):
        """Versione streaming che yielda eventi SSE.

        Yields:
            Dizionario con tipo evento e dati.
        """
        top_k = top_k or settings.RAG_TOP_K_FINAL
        t_start = time.time()

        # 1-3: Retrieval (stesso della query normale)
        query_embedding = embedding_service.embed_query(question)
        hybrid_results = vector_store.hybrid_search(
            query=question,
            query_embedding=query_embedding,
        )

        # Re-ranking
        candidates = hybrid_results[:20]
        if candidates:
            pairs = [(question, item["text"]) for item in candidates]
            scores = self.reranker.predict(pairs)
            for item, score in zip(candidates, scores):
                item["rerank_score"] = float(score)
            candidates.sort(key=lambda x: x["rerank_score"], reverse=True)
        final_chunks = candidates[:top_k]

        # Invia fonti
        sources = []
        for i, chunk in enumerate(final_chunks, start=1):
            ref = f"[{i}]"
            doc_name = chunk.get("metadata", {}).get("doc_name", "Sconosciuto")
            location = chunk.get("metadata", {}).get("location", "")
            sources.append({
                "ref": ref,
                "document_name": doc_name,
                "location": location,
                "chunk_id": chunk["id"],
                "score": round(chunk.get("rerank_score", chunk.get("rrf_score", 0)), 4),
                "snippet": chunk["text"][:200] + "..." if len(chunk["text"]) > 200 else chunk["text"],
            })

        yield {"type": "sources", "sources": sources}

        # Assemblaggio prompt
        context_parts = []
        for i, chunk in enumerate(final_chunks, start=1):
            context_parts.append(f"[{i}] {chunk['text']}")
        context = "\n\n---\n\n".join(context_parts)
        prompt = RAG_SYSTEM_PROMPT + "\n\n" + RAG_CONTEXT_TEMPLATE.format(
            chunks=context,
            question=question,
        )

        # Streaming generazione
        t_gen = time.time()
        token_count = 0
        first_token = True

        async for token in llm_manager.generate_stream(
            prompt=prompt,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        ):
            if first_token:
                ttft = time.time() - t_gen
                first_token = False
            yield {"type": "token", "token": token}
            token_count += 1

        t_gen_done = time.time()
        tok_per_sec = token_count / max(t_gen_done - t_gen, 0.001)

        yield {
            "type": "metrics",
            "tok_per_sec": round(tok_per_sec, 1),
            "ttft": round(ttft if not first_token else 0, 2),
            "retrieval_time_ms": round((time.time() - t_start) * 1000, 1),
        }
        yield {"type": "done"}


# Istanza singleton
rag_engine = RAGEngine()