"""
RAG Engine — Motore principale di interrogazione.
Hybrid Retrieval → Re-ranking → Prompt assembly → LLM → Risposta con citazioni.
"""

from __future__ import annotations
import asyncio
import logging
import time
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("koji")

from app.config import settings
from app.services.vector_store import vector_store
from app.services.embedding_service import embedding_service
from app.services.llm_manager import llm_manager
from app.services.metrics_store import metrics_store


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
        # Dopo un fallimento (download bloccato, modello assente, timeout) il
        # re-ranking viene disattivato per le query successive: evita di
        # ri-tentare a ogni domanda un'operazione lenta o impossibile.
        self._reranker_failed = False

    @property
    def reranker(self):
        """Lazy loading del cross-encoder per re-ranking (solo cache locale)."""
        if self._reranker is None:
            from sentence_transformers import CrossEncoder
            self._reranker = CrossEncoder("cross-encoder/ms-marco-MiniLM-L-6-v2")
        return self._reranker

    async def rerank_scores(self, question: str, texts: list[str]) -> Optional[list[float]]:
        """Punteggi cross-encoder per le coppie (query, testo).

        Esegue il predict FUORI dall'event loop (thread dedicato) con un
        timeout: il cross-encoder è pesante e il primo load può persino
        scaricare il modello da HuggingFace — eseguirlo in modo sincrono
        bloccherebbe l'event loop congelando API e streaming SSE.

        Returns:
            Lista di punteggi, oppure None se il re-ranking non è
            disponibile/disattivato (il chiamante prosegue con l'ordine
            del retriever).
        """
        if not settings.RAG_RERANK_ENABLED or self._reranker_failed or not texts:
            return None
        try:
            def _predict() -> list[float]:
                pairs = [(question, t) for t in texts]
                return [float(s) for s in self.reranker.predict(pairs)]

            return await asyncio.wait_for(
                asyncio.to_thread(_predict),
                timeout=settings.RAG_RERANK_TIMEOUT,
            )
        except Exception as e:
            self._reranker_failed = True
            logger.warning(
                "Re-ranking non disponibile (%s): si usa l'ordinamento del retriever", e
            )
            return None

    async def _rerank(
        self, question: str, results: list[dict], top_k: int, metrics: dict
    ) -> list[dict]:
        """Applica il re-ranking opzionale ai risultati del retriever."""
        final = results[:top_k]
        if not results:
            return final
        candidates = results[: settings.RAG_RERANK_TOP_K]
        scores = await self.rerank_scores(question, [c["text"] for c in candidates])
        if scores is None:
            metrics["reranked"] = False
            return final
        for item, score in zip(candidates, scores):
            item["rerank_score"] = score
        candidates.sort(key=lambda x: x.get("rerank_score", 0), reverse=True)
        metrics["reranked"] = True
        return candidates[:top_k]

    async def _retrieve(
        self,
        question: str,
        top_k: int,
        top_k_dense: Optional[int] = None,
        top_k_keyword: Optional[int] = None,
        rrf_k: Optional[int] = None,
        retrieval_mode: Optional[str] = None,
    ) -> tuple[list[dict], dict]:
        """Recupero contesto con modalità selezionabile (hybrid|dense|bm25) + re-ranking.

        Returns:
            (final_chunks, metrics) — metriche includono modalità, candidati e
            tempo di retrieval.
        """
        mode = (retrieval_mode or settings.RAG_RETRIEVAL_MODE).lower()
        t_start = time.time()
        m = {"mode": mode, "reranked": False, "retrieval_time_ms": 0.0}

        # Embedding della query FUORI dall'event loop (thread + timeout):
        # sincrono congelerebbe API e stream SSE (cursore bloccato lato UI)
        query_embedding = await embedding_service.embed_query_async(question)

        if mode == "dense":
            results = vector_store.dense_search(
                query_embedding,
                top_k=max(top_k, top_k_dense or settings.RAG_TOP_K_DENSE),
            )
        elif mode == "bm25":
            results = vector_store.keyword_search(
                question,
                top_k=max(top_k, top_k_keyword or settings.RAG_TOP_K_KEYWORD),
            )
        else:
            results = vector_store.hybrid_search(
                query=question,
                query_embedding=query_embedding,
                top_k_dense=top_k_dense,
                top_k_keyword=top_k_keyword,
                rrf_k=rrf_k,
            )
        m["candidates"] = len(results)
        m["retrieval_time_ms"] = round((time.time() - t_start) * 1000, 1)

        # Re-ranking con cross-encoder "se configurato" (BE-RF-15, P1).
        # Fuori dall'event loop, con timeout e fallback: vedi _rerank.
        final_chunks = await self._rerank(question, results, top_k, m)

        return final_chunks, m

    async def query(
        self,
        question: str,
        model: Optional[str] = None,
        top_k: Optional[int] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        retrieval_mode: Optional[str] = None,
    ) -> RAGResult:
        """Esegue una query RAG completa.

        Args:
            question: Domanda in linguaggio naturale.
            model: Modello LLM da usare (default da config).
            top_k: Numero di chunk finali per il contesto.
            temperature: Temperatura di generazione.
            max_tokens: Token massimi nella risposta.
            retrieval_mode: Modalità di retrieval ("hybrid"|"dense"|"bm25").

        Returns:
            RAGResult con risposta, fonti e metriche.
        """
        top_k = top_k or settings.RAG_TOP_K_FINAL
        t_start = time.time()

        # 1. Retrieval (hybrid/dense/bm25) + re-ranking
        final_chunks, r_metrics = await self._retrieve(
            question=question,
            top_k=top_k,
            retrieval_mode=retrieval_mode,
        )
        # (Il re-ranking è già applicato in _retrieve)
        t_rerank_done = time.time()

        # 2. Assemblaggio contesto con citazioni
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

        # 3. Generazione LLM con streaming
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

        # 4. Metriche
        t_total = t_gen_done - t_start
        tok_per_sec = token_count / max(t_gen_done - t_gen, 0.001)

        metrics = {
            "total_time_ms": round(t_total * 1000, 1),
            "retrieval_time_ms": r_metrics["retrieval_time_ms"],
            "generation_time_ms": round((t_gen_done - t_gen) * 1000, 1),
            "tok_per_sec": round(tok_per_sec, 1),
            "ttft_ms": round((t_gen - t_start) * 1000, 1),
            "tokens_generated": token_count,
            "chunks_retrieved": r_metrics.get("candidates", 0),
            "chunks_after_rerank": len(final_chunks),
            "retrieval_mode": r_metrics["mode"],
            "reranked": r_metrics["reranked"],
        }

        # 5. Registra metriche runtime (monitoraggio BE-RF-21)
        try:
            metrics_store.record_retrieval(
                query=question,
                mode=r_metrics["mode"],
                latency_ms=r_metrics["retrieval_time_ms"],
                num_results=len(final_chunks),
                index_size=vector_store.count,
            )
            used_model = model or llm_manager.active_model or settings.OLLAMA_MODEL
            metrics_store.record_llm(
                model=used_model,
                tokens=token_count,
                ttft=metrics["ttft_ms"] / 1000.0,
                duration_s=(t_gen_done - t_gen),
                tok_per_sec=tok_per_sec,
                mode="rag",
            )
        except Exception:
            pass

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
        retrieval_mode: Optional[str] = None,
    ):
        """Versione streaming che yielda eventi SSE.

        Yields:
            Dizionario con tipo evento e dati.
        """
        top_k = top_k or settings.RAG_TOP_K_FINAL
        t_start = time.time()

        # Feedback immediato per il client: il primo evento SSE viene emesso
        # subito, mentre retrieval ed embedding sono ancora in corso.
        yield {"type": "status", "stage": "retrieval",
               "message": "Ricerca nei documenti in corso..."}

        # 1. Retrieval (hybrid/dense/bm25) + re-ranking
        final_chunks, r_metrics = await self._retrieve(
            question=question,
            top_k=top_k,
            retrieval_mode=retrieval_mode,
        )
        t_retrieval_done = time.time()

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
        yield {"type": "status", "stage": "generation",
               "message": "Generazione della risposta..."}

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
        ttft = 0.0  # può restare 0 se il modello non genera token

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
            # Tempo effettivo di embedding+retrieval+reranking, misurato PRIMA della generazione
            "retrieval_time_ms": round((t_retrieval_done - t_start) * 1000, 1),
        }
        yield {"type": "done"}

        # Registra metriche runtime (monitoraggio BE-RF-21)
        try:
            metrics_store.record_retrieval(
                query=question,
                mode=r_metrics["mode"],
                latency_ms=r_metrics["retrieval_time_ms"],
                num_results=len(final_chunks),
                index_size=vector_store.count,
            )
            used_model = model or llm_manager.active_model or settings.OLLAMA_MODEL
            metrics_store.record_llm(
                model=used_model,
                tokens=token_count,
                ttft=ttft if not first_token else 0.0,
                duration_s=(t_gen_done - t_gen),
                tok_per_sec=tok_per_sec,
                mode="rag_stream",
            )
        except Exception:
            pass


# Istanza singleton
rag_engine = RAGEngine()