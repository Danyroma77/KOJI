"""
=============================================================================
EMBEDDING SERVICE — GENERA EMBEDDING DENSI CON SENTENCE-TRANSFORMERS
=============================================================================

Questo servizio genera vettori densi (embedding) che rappresentano il
significato semantico del testo. Usa sentence-transformers su CPU con
cache su disco per evitare ricalcoli.

CARATTERISTICHE:
- Modello: all-MiniLM-L6-v2 (leggero, 80MB, 384 dimensioni)
- Batch processing: elabora più testi insieme per efficienza
- Cache su disco: evita di ricalcolare embedding già generati
- Async support: esegue embedding in thread separato per non bloccare API

FLUSSO:
1. Controlla cache su disco (per chunk_id o hash del testo)
2. Se cache miss, genera embedding con sentence-transformers
3. Salva in cache per usi futuri
4. Ritorna vettori normalizzati (norma L2 = 1)

USO:
- embed_texts: per batch di chunk (indicizzazione)
- embed_query: per singola query (sincrono, uso interno)
- embed_query_async: per query API (async, non blocca event loop)
"""

from __future__ import annotations
import asyncio
import json
import hashlib
import os
from pathlib import Path
from typing import Optional

from app.config import settings


class EmbeddingService:
    """
    Servizio per la generazione di embedding con cache su disco.
    
    Gestisce la generazione efficiente di vettori semantici con:
    - Lazy loading del modello (caricato al primo uso)
    - Cache su disco (evita ricalcoli)
    - Supporto batch (elaborazione multipla)
    - Async wrapper (non blocca l'event loop)
    """

    def __init__(self):
        self._model = None
        self._cache_dir = settings.EMBEDDING_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def model(self):
        """
        Lazy loading del modello sentence-transformers.
        
        Il modello viene caricato solo al primo uso per risparmiare memoria.
        Utilizza il modello configurato in settings.EMBEDDING_MODEL.
        """
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
        return self._model

    def embed_texts(self, texts: list[str], chunk_ids: list[str] = None) -> list[list[float]]:
        """
        Genera embedding per una lista di testi (BATCH).
        
        Args:
            texts: Lista di testi da embeddare.
            chunk_ids: ID dei chunk per la cache (opzionale, stabile).
            
        Returns:
            Lista di vettori densi (dimensione EMBEDDING_DIMENSION).
            
        Note:
            - Usa chunk_id come chiave cache se disponibile
            - Altrimenti usa hash MD5 del testo
            - I vettori sono normalizzati (norma L2 = 1)
        """
        if not texts:
            return []

        # Controlla cache per ogni testo
        results = [None] * len(texts)
        to_embed = []
        to_embed_indices = []

        for i, text in enumerate(texts):
            cache_key = self._get_cache_key(text, chunk_ids[i] if chunk_ids else None)
            cached = self._load_cache(cache_key)
            if cached is not None:
                results[i] = cached
            else:
                to_embed.append(text)
                to_embed_indices.append(i)

        # Genera embedding per i testi non in cache
        if to_embed:
            embeddings = self.model.encode(
                to_embed,
                batch_size=settings.EMBEDDING_BATCH_SIZE,
                show_progress_bar=False,
                normalize_embeddings=True,
            )
            embeddings = embeddings.tolist()

            # Salva in cache e aggiorna risultati
            for j, idx in enumerate(to_embed_indices):
                results[idx] = embeddings[j]
                cache_key = self._get_cache_key(
                    to_embed[j],
                    chunk_ids[idx] if chunk_ids else None
                )
                self._save_cache(cache_key, embeddings[j])

        return results

    def embed_query(self, query: str) -> list[float]:
        """
        Genera embedding per una singola query (CHIAMATA BLOCCANTE).
        
        Args:
            query: Testo della query.
            
        Returns:
            Vettore denso rappresentante la query.
            
        Warning:
            Questa funzione è bloccante. Per uso in API async,
            utilizzare embed_query_async().
        """
        embedding = self.model.encode(
            [query],
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embedding[0].tolist()

    async def embed_query_async(self, query: str) -> list[float]:
        """
        Embedding di una query FUORI dall'event loop (ASINCRONO).
        
        Esegue l'embedding in un thread separato per non bloccare l'event
        loop di FastAPI. Include timeout esplicito per evitare attese
        infinite in caso di problemi.
        
        Args:
            query: Testo della query.
            
        Returns:
            Vettore denso rappresentante la query.
            
        Raises:
            RuntimeError: Se l'embedding non completa entro il timeout.
            
        Note:
            - sentence-transformers è CPU-bound e può essere lento
            - Il primo caricamento può scaricare il modello da HuggingFace
            - Il timeout di default è 30s (configurabile)
        """
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(self.embed_query, query),
                timeout=settings.EMBEDDING_TIMEOUT,
            )
        except asyncio.TimeoutError:
            raise RuntimeError(
                f"Embedding non completato entro {settings.EMBEDDING_TIMEOUT}s "
                f"(modello '{settings.EMBEDDING_MODEL}')"
            )

    def _get_cache_key(self, text: str, chunk_id: str = None) -> str:
        """Genera chiave di cache basata su contenuto o ID chunk."""
        if chunk_id:
            # Se abbiamo un ID stabile, usiamo quello
            key = f"chunk_{chunk_id}"
        else:
            # Altrimenti hash del testo
            key = hashlib.md5(text.encode()).hexdigest()
        return key

    def _load_cache(self, key: str) -> Optional[list[float]]:
        """Carica embedding dalla cache su disco."""
        cache_file = self._cache_dir / f"{key}.json"
        if cache_file.exists():
            try:
                with open(cache_file, "r") as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError):
                return None
        return None

    def _save_cache(self, key: str, embedding: list[float]):
        """Salva embedding nella cache su disco."""
        cache_file = self._cache_dir / f"{key}.json"
        try:
            with open(cache_file, "w") as f:
                json.dump(embedding, f)
        except IOError:
            pass  # Cache failure non blocca il processing

    def clear_cache(self):
        """Svuota la cache embedding."""
        for f in self._cache_dir.glob("*.json"):
            f.unlink()

    @property
    def dimension(self) -> int:
        return settings.EMBEDDING_DIMENSION

    def warmup(self):
        """Pre-carica il modello per evitare timeout alla prima query.

        Il modello viene caricato in lazy loading al primo uso, il che può
        causare timeout (30s) specialmente in container Docker con risorse
        limitate. Questo metodo forza il caricamento sincrono all'avvio.
        """
        if self._model is None:
            # Forza il caricamento del modello
            _ = self.model


# Istanza singleton
embedding_service = EmbeddingService()