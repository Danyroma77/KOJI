"""
Embedding Service — Genera embedding densi con sentence-transformers.
Eseguito su CPU in batch con cache su disco.
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
    """Servizio per la generazione di embedding con cache su disco."""

    def __init__(self):
        self._model = None
        self._cache_dir = settings.EMBEDDING_CACHE_DIR
        self._cache_dir.mkdir(parents=True, exist_ok=True)

    @property
    def model(self):
        """Lazy loading del modello — caricato solo al primo uso."""
        if self._model is None:
            from sentence_transformers import SentenceTransformer
            self._model = SentenceTransformer(settings.EMBEDDING_MODEL)
        return self._model

    def embed_texts(self, texts: list[str], chunk_ids: list[str] = None) -> list[list[float]]:
        """Genera embedding per una lista di testi.

        Args:
            texts: Lista di testi da embeddare.
            chunk_ids: ID dei chunk per la cache (opzionale).

        Returns:
            Lista di vettori densi (dimensione EMBEDDING_DIMENSION).
        """
        if not texts:
            return []

        # Controlla cache
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

            for j, idx in enumerate(to_embed_indices):
                results[idx] = embeddings[j]
                cache_key = self._get_cache_key(
                    to_embed[j],
                    chunk_ids[idx] if chunk_ids else None
                )
                self._save_cache(cache_key, embeddings[j])

        return results

    def embed_query(self, query: str) -> list[float]:
        """Genera embedding per una singola query (CHIAMATA BLOCCANTE)."""
        embedding = self.model.encode(
            [query],
            show_progress_bar=False,
            normalize_embeddings=True,
        )
        return embedding[0].tolist()

    async def embed_query_async(self, query: str) -> list[float]:
        """Embedding di una query FUORI dall'event loop.

        sentence-transformers gira su PyTorch/ONNX: il primo load può
        scaricare i pesi da HuggingFace e l'encode è CPU-bound. Chiamato
        in modo sincrono dentro un handler async congela l'event loop →
        le risposte (SSE RAG comprese) non partono mai e il client resta
        "bloccato". Qui l'encode gira in un thread con timeout esplicito:
        in caso di problema l'errore arriva al client, non un silenzio.
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


# Istanza singleton
embedding_service = EmbeddingService()