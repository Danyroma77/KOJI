"""
=============================================================================
VECTOR STORE — CHROMADB PER RICERCA DENSA + BM25 PER RICERCA KEYWORD
=============================================================================

Questo modulo implementa un vector store ibrido che combina:
- Ricerca densa: HNSW (ChromaDB) per similarità semantica
- Ricerca keyword: BM25 per corrispondenza lessicale
- Hybrid: fusione RRF (Reciprocal Rank Fusion) dei due metodi

ARCHITETTURA:
- ChromaDB: database vettoriale persistente su disco
- HNSW: indice gerarchico per ricerca approssimativa efficiente
- BM25: indice lessicale costruito da ChromaDB
- Fusione RRF: combina i ranking dei due metodi

REFRESH MECHANISM:
- API e worker sono processi separati
- ChromaDB carica l'indice in memoria all'apertura
- Le scritture di un processo non sono visibili all'altro senza refresh
- Il refresh periodico (5s) rende visibili le scritture del worker all'API

METODI DI RICERCA:
- dense_search: ricerca vettoriale (embedding query + HNSW)
- keyword_search: ricerca BM25 (tokenizzazione + scoring)
- hybrid_search: fusione RRF di dense + keyword
"""

from __future__ import annotations
import json
import time
import threading
import logging
from typing import Optional
from pathlib import Path

import chromadb
from rank_bm25 import BM25Okapi

from app.config import settings
from app.services.embedding_service import embedding_service

logger = logging.getLogger("koji")


class VectorStore:
    """
    Vector store ibrido: HNSW (denso) + BM25 (keyword).
    
    Gestisce l'indicizzazione e la ricerca di chunk di testo nella
    Knowledge Base con supporto per ricerca semantica e lessicale.
    """

    def __init__(self):
        self._chroma = None
        self._collection = None
        self._bm25_index = None
        self._bm25_docs: list[dict] = []  # {id, text}
        self._initialized = False
        self._lock = threading.Lock()
        self._last_refresh = 0.0
        # Intervallo (s) dopo il quale lo stato persistito di ChromaDB viene
        # riletto dal disco. API e worker sono processi separati sulla stessa
        # directory persistente: il refresh rende visibili all'API le scritture
        # fatte dal worker senza richiedere riavvii (vedi _maybe_refresh).
        self.REFRESH_INTERVAL = 5.0

    def initialize(self):
        """
        Inizializza ChromaDB e carica lo stato persistente.
        
        Crea il client ChromaDB, ottiene/crea la collection, e ricostruisce
        l'indice BM25 dai dati persistenti.
        
        Note:
            - I parametri HNSW non vengono passati a ChromaDB >= 0.4.16
              perché causano errori. Si usano i default della libreria.
        """
        if self._initialized:
            return

        self._chroma = chromadb.PersistentClient(
            path=str(settings.CHROMA_PERSIST_DIR)
        )
        # NB: non passare metadata {"hnsw:M", "hnsw:efConstruction"} — da
        # ChromaDB >= 0.4.16 queste chiavi sono state rimosse e su 0.5.7 la
        # creazione fallisce lasciando una collection SENZA segmenti (ogni
        # successiva count()/query() va in StopIteration). Si usano i default
        # della libreria; le impostazioni HNSW_* restano in config per un
        # eventuale futuro uso del parametro `configuration`.
        self._collection = self._chroma.get_or_create_collection(
            name="knowlocal_chunks"
        )

        # Ricostruisci indice BM25 dalla collection
        self._rebuild_bm25()
        self._initialized = True
        self._last_refresh = time.time()

    def _maybe_refresh(self):
        """Rilegge lo stato persistito di ChromaDB se è passato l'intervallo.

        API e worker sono processi separati che condividono la stessa
        directory persistente di ChromaDB. ChromaDB carica l'indice in
        memoria al momento dell'apertura del client: le scritture fatte
        dall'altro processo non diventano visibili senza riaprire il client.
        Con un refresh periodico le ricerche (e quindi il RAG) vedono sempre
        i documenti appena indicizzati, senza riavvii. In caso di errore si
        continua con lo stato corrente (best-effort).
        """
        now = time.time()
        if not self._initialized:
            self.initialize()
            return
        if now - self._last_refresh < self.REFRESH_INTERVAL:
            return
        try:
            with self._lock:
                close = getattr(self._chroma, "close", None)
                if callable(close):
                    try:
                        close()
                    except Exception:
                        pass
                client = chromadb.PersistentClient(
                    path=str(settings.CHROMA_PERSIST_DIR)
                )
                collection = client.get_or_create_collection(
                    name="knowlocal_chunks"
                )
                # Ricostruisce lo stato BM25 dai dati appena riletti
                bm25_docs = []
                all_data = collection.get(include=["documents"])
                if all_data and all_data.get("ids"):
                    bm25_docs = [
                        {"id": id_, "text": doc}
                        for id_, doc in zip(all_data["ids"], all_data["documents"])
                    ]
                new_index = None
                if bm25_docs:
                    tokenized = [d["text"].lower().split() for d in bm25_docs]
                    new_index = BM25Okapi(tokenized)
                self._chroma = client
                self._collection = collection
                self._bm25_docs = bm25_docs
                self._bm25_index = new_index
                self._last_refresh = now
                logger.info(
                    "Vector store aggiornato dal disco: %d chunk riletti",
                    len(bm25_docs),
                )
        except Exception as e:
            logger.warning(
                "Refresh vector store non riuscito (uso stato corrente): %s", e
            )

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

    def get_metadata_for_ids(self, ids: list[str]) -> dict[str, dict]:
        """Ritorna {id: metadata} per gli ID richiesti via ChromaDB.

        Usato quando un risultato proviene solo dall'indice BM25 (che non
        conserva i metadati) e serve documento/posizione per le fonti.
        """
        if not ids:
            return {}
        self._maybe_refresh()
        result: dict[str, dict] = {}
        try:
            got = self._collection.get(ids=ids, include=["metadatas"])
            if got and got.get("ids"):
                for id_, meta in zip(got["ids"], got["metadatas"] or []):
                    result[id_] = meta or {}
        except Exception:
            pass
        return result

    def dense_search(self, query_embedding: list[float], top_k: int = 10) -> list[dict]:
        """Ricerca vettoriale densa con HNSW.

        Returns:
            Lista di {id, text, score, metadata}.
        """
        self._maybe_refresh()

        results = self._collection.query(
            query_embeddings=[query_embedding],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )

        items = []
        if results and results["ids"] and results["ids"][0]:
            for i, id_ in enumerate(results["ids"][0]):
                # Converti distanza in similarità, normalizzando tra 0 e 1.
                # ChromaDB usa distanza coseno (0-2) o L2. La formula
                # max(0, 1 - distance) garantisce un punteggio sempre valido.
                distance = results["distances"][0][i]
                similarity = max(0.0, 1.0 - distance)
                items.append({
                    "id": id_,
                    "text": results["documents"][0][i],
                    "score": similarity,
                    "metadata": results["metadatas"][0][i] if results["metadatas"] else {},
                })

        return items

    def keyword_search(self, query: str, top_k: int = 10) -> list[dict]:
        """Ricerca keyword con BM25.

        Returns:
            Lista di {id, text, score}.
        """
        self._maybe_refresh()

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

        # Reciprocal Rank Fusion — accumula i punteggi RRF per id
        # NB: il vecchio blocco con `rrf_scores` è stato rimosso: conteneva
        # `"dense" not in rrf_scores[id_]` su un float (TypeError appena
        # la KB non è vuota) e il suo valore non era mai usato.
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
            metadata = dense_item.get("metadata") or {}
            if not metadata:
                # Chunk trovato solo via BM25: recupera i metadati da ChromaDB
                # così le fonti mostrano documento e posizione corretti.
                try:
                    got = self._collection.get(ids=[id_], include=["metadatas"])
                    if got and got.get("metadatas") and got["metadatas"][0]:
                        metadata = got["metadatas"][0]
                except Exception:
                    pass
            results.append({
                "id": id_,
                "text": dense_item.get("text") or keyword_item.get("text", ""),
                "dense_score": dense_item.get("score", 0),
                "keyword_score": keyword_item.get("score", 0),
                "rrf_score": data["score"],
                "metadata": metadata,
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
        self._maybe_refresh()
        return self._collection.count()

    def get_stats(self) -> dict:
        """Statistiche del vector store."""
        self._maybe_refresh()
        return {
            "total_chunks": self._collection.count(),
            "bm25_docs": len(self._bm25_docs),
        }


# Istanza singleton
vector_store = VectorStore()