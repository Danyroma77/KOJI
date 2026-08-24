"""
Vector Store — ChromaDB per ricerca densa + BM25 per ricerca keyword.
Implementa Hybrid Retrieval con fusione RRF.
"""

from __future__ import annotations
import json
from typing import Optional
from pathlib import Path

import chromadb
from rank_bm25 import BM25Okapi

from app.config import settings
from app.services.embedding_service import embedding_service


class VectorStore:
    """Vector store ibrido: HNSW (denso) + BM25 (keyword)."""

    def __init__(self):
        self._chroma = None
        self._collection = None
        self._bm25_index = None
        self._bm25_docs: list[dict] = []  # {id, text}
        self._initialized = False

    def initialize(self):
        """Inizializza ChromaDB e carica lo stato persistente."""
        if self._initialized:
            return

        self._chroma = chromadb.PersistentClient(
            path=str(settings.CHROMA_PERSIST_DIR)
        )
        self._collection = self._chroma.get_or_create_collection(
            name="knowlocal_chunks",
            metadata={
                "hnsw:M": settings.HNSW_M,
                "hnsw:efConstruction": settings.HNSW_EF_CONSTRUCTION,
            }
        )

        # Ricostruisci indice BM25 dalla collection
        self._rebuild_bm25()
        self._initialized = True

    def add_chunks(self, chunks: list, embeddings: list[list[float]], metadatas: list[dict]):
        """Aggiunge chunk e embedding al vector store.

        Args:
            chunks: Lista di oggetti Chunk (dal ChunkManager).
            embeddings: Lista di vettori embedding.
            metadatas: Lista di metadati per ogni chunk.
        """
        self.initialize()

        ids = [f"{c.doc_id}_{c.index}" for c in chunks]
        documents = [c.text for c in chunks]

        # Inserisci in ChromaDB (upsert per aggiornamenti)
        self._collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )

        # Aggiorna BM25
        for i, chunk in enumerate(chunks):
            # Rimuovi vecchia versione se esiste
            self._bm25_docs = [
                d for d in self._bm25_docs if d["id"] != f"{chunk.doc_id}_{chunk.index}"
            ]
            self._bm25_docs.append({
                "id": f"{chunk.doc_id}_{chunk.index}",
                "text": chunk.text,
            })

        self._rebuild_bm25_index()

    def delete_by_doc(self, doc_id: str):
        """Rimuove tutti i chunk di un documento."""
        self.initialize()

        # ChromaDB: delete con where filter
        try:
            self._collection.delete(where={"doc_id": doc_id})
        except Exception:
            # Se la collection non ha documenti con quel doc_id
            pass

        # BM25: rimuovi e ricostruisci
        prefix = f"{doc_id}_"
        self._bm25_docs = [d for d in self._bm25_docs if not d["id"].startswith(prefix)]
        self._rebuild_bm25_index()

    def dense_search(self, query_embedding: list[float], top_k: int = 10) -> list[dict]:
        """Ricerca vettoriale densa con HNSW.

        Returns:
            Lista di {id, text, score, metadata}.
        """
        self.initialize()

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        items = []
        if results and results["ids"] and results["ids"][0]:
            for i, id_ in enumerate(results["ids"][0]):
                items.append({
                    "id": id_,
                    "text": results["documents"][0][i],
                    "score": 1 - results["distances"][0][i],  # Converti distanza in similarità
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                })

        return items

    def keyword_search(self, query: str, top_k: int = 10) -> list[dict]:
        """Ricerca keyword con BM25.

        Returns:
            Lista di {id, text, score}.
        """
        self.initialize()

        if not self._bm25_index:
            return []

        tokenized_query = query.lower().split()
        scores = self._bm25_index.get_scores(tokenized_query)

        # Top-k
        import numpy as np
        top_indices = np.argsort(scores)[::-1][:top_k]

        items = []
        for idx in top_indices:
            if scores[idx] > 0:
                doc = self._bm25_docs[idx]
                items.append({
                    "id": doc["id"],
                    "text": doc["text"],
                    "score": float(scores[idx]),
                })

        return items

    def hybrid_search(
        self,
        query: str,
        query_embedding: list[float],
        top_k_dense: int = None,
        top_k_keyword: int = None,
        rrf_k: int = None,
    ) -> list[dict]:
        """Hybrid Search: Dense + Keyword con Reciprocal Rank Fusion.

        Args:
            query: Testo della query (per BM25).
            query_embedding: Embedding della query (per HNSW).
            top_k_dense: Numero risultati dallo spazio denso.
            top_k_keyword: Numero risultati dallo spazio keyword.
            rrf_k: Parametro k per RRF (default 60).

        Returns:
            Lista di {id, text, dense_score, keyword_score, rrf_score} ordinata per RRF.
        """
        top_k_dense = top_k_dense or settings.RAG_TOP_K_DENSE
        top_k_keyword = top_k_keyword or settings.RAG_TOP_K_KEYWORD
        rrf_k = rrf_k or settings.RAG_RRF_K

        # Recupero parallelo
        dense_results = self.dense_search(query_embedding, top_k_dense)
        keyword_results = self.keyword_search(query, top_k_keyword)

        # Reciprocal Rank Fusion
        rrf_scores = {}

        for rank, item in enumerate(dense_results, start=1):
            id_ = item["id"]
            rrf_scores[id_] = rrf_scores.get(id_, 0) + 1 / (rrf_k + rank)
            if id_ not in rrf_scores or "dense" not in rrf_scores[id_]:
                rrf_scores[id_] = rrf_scores.get(id_, 0)

        # Separiamo i punteggi RRF dai dati
        rrf_raw = {}
        for rank, item in enumerate(dense_results, start=1):
            id_ = item["id"]
            if id_ not in rrf_raw:
                rrf_raw[id_] = {"score": 0, "dense": item}
            rrf_raw[id_]["score"] += 1 / (rrf_k + rank)

        for rank, item in enumerate(keyword_results, start=1):
            id_ = item["id"]
            if id_ not in rrf_raw:
                rrf_raw[id_] = {"score": 0, "dense": None}
            rrf_raw[id_]["score"] += 1 / (rrf_k + rank)
            rrf_raw[id_]["keyword"] = item

        # Ordina per RRF score
        sorted_items = sorted(
            rrf_raw.items(),
            key=lambda x: x[1]["score"],
            reverse=True,
        )

        results = []
        for id_, data in sorted_items:
            dense_item = data.get("dense") or {}
            keyword_item = data.get("keyword", {})
            results.append({
                "id": id_,
                "text": dense_item.get("text") or keyword_item.get("text", ""),
                "dense_score": dense_item.get("score", 0),
                "keyword_score": keyword_item.get("score", 0),
                "rrf_score": data["score"],
                "metadata": dense_item.get("metadata", {}),
            })

        return results

    def _rebuild_bm25(self):
        """Ricostruisce l'indice BM25 dai dati ChromaDB."""
        if not self._collection:
            return

        try:
            # Recupera tutti i documenti da ChromaDB
            all_data = self._collection.get(include=["documents"])
            if all_data and all_data["ids"]:
                self._bm25_docs = [
                    {"id": id_, "text": doc}
                    for id_, doc in zip(all_data["ids"], all_data["documents"])
                ]
                self._rebuild_bm25_index()
        except Exception:
            self._bm25_docs = []

    def _rebuild_bm25_index(self):
        """Costruisce l'indice BM25 dai documenti correnti."""
        if self._bm25_docs:
            tokenized = [doc["text"].lower().split() for doc in self._bm25_docs]
            self._bm25_index = BM25Okapi(tokenized)
        else:
            self._bm25_index = None

    @property
    def count(self) -> int:
        """Numero totale di chunk indicizzati."""
        if not self._initialized:
            self.initialize()
        return self._collection.count()

    def get_stats(self) -> dict:
        """Statistiche del vector store."""
        self.initialize()
        return {
            "total_chunks": self._collection.count(),
            "bm25_docs": len(self._bm25_docs),
        }


# Istanza singleton
vector_store = VectorStore()