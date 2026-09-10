"""
=============================================================================
CONFIGURATION SNAPSHOT — SNAPSHOT IMMUTABILE DELLA CONFIGURAZIONE
=============================================================================

Al inicio del processing di un documento, acquisisce una copia immutabile della
configurazione utilizzata. Persiste su filesystem JSON in una directory separata
e genera un hash deterministico per il confronto tra esperimenti.

STRUTTURA FILE:
- DATA_DIR/snapshots/{snapshot_id}.json   (ConfigurationSnapshot)

IMPORTANTE:
- Lo snapshot è una COPIA PROFONDA: non è un riferimento all'oggetto globale settings.
- Se Admin modifica la configurazione AFTER il processing, il documento mantiene
  lo snapshot originale (il documento X mostra config A, non la config attuale).

HASH:
- configuration_hash: SHA-256 deterministico dello snapshot.
- Lo stesso insieme di parametri produce lo stesso hash.
"""

from __future__ import annotations

import hashlib
import json
import threading
import uuid
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import settings


# =============================================================================
# SNAPSHOT SERVICE
# =============================================================================

class ConfigurationSnapshotService:
    """
    Crea, persiste e query gli snapshot di configurazione utilizzati durante
    il processing dei documenti.
    """

    def __init__(self):
        self._base_dir = settings.DATA_DIR / "snapshots"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _snapshot_path(self, snapshot_id: str) -> Path:
        return self._base_dir / f"{snapshot_id}.json"

    def _save(self, snapshot: dict) -> dict:
        snapshot_id = snapshot.get("id") or str(uuid.uuid4())[:12]
        snapshot["id"] = snapshot_id
        path = self._snapshot_path(snapshot_id)
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
        return snapshot

    def _load(self, snapshot_id: str) -> Optional[dict]:
        path = self._snapshot_path(snapshot_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def create_snapshot(self, doc_id: str) -> dict:
        """
        Crea uno snapshot immutabile della configurazione corrente.
        """
        with self._lock:
            snap = self._build_snapshot(doc_id)
            return self._save(snap)

    def _build_snapshot(self, doc_id: str) -> dict:
        """
        Costruisce il dict dello snapshot dai valori EFFECTIVI di settings.
        """
        hnsw_configured = {
            "m": settings.HNSW_M,
            "ef_construction": settings.HNSW_EF_CONSTRUCTION,
        }
        hnsw_effective = {
            "m": None,
            "ef_construction": None,
            "note": "HNSW parameters configured but NOT passed to ChromaDB. "
                     "Effective defaults depend on ChromaDB library version.",
        }

        snap = {
            "id": None,
            "document_id": doc_id,
            "created_at": datetime.now().isoformat(),
            "configuration_hash": None,
            "sections": {
                "chunking": {
                    "chunk_strategy": settings.CHUNK_STRATEGY,
                    "chunk_size": settings.CHUNK_SIZE,
                    "chunk_overlap_pct": settings.CHUNK_OVERLAP_PCT,
                    "chunk_overlap_tokens": settings.chunk_overlap_tokens,
                },
                "embedding": {
                    "embedding_model": settings.EMBEDDING_MODEL,
                    "embedding_batch_size": settings.EMBEDDING_BATCH_SIZE,
                    "embedding_dimension": settings.EMBEDDING_DIMENSION,
                },
                "vector_index": {
                    "vector_store_type": "chroma_db",
                    "collection_name": "knowlocal_chunks",
                    "hnsw": {
                        "configured": hnsw_configured,
                        "effective": hnsw_effective,
                    },
                },
                "retrieval": {
                    "retrieval_mode": settings.RAG_RETRIEVAL_MODE,
                    "top_k_dense": settings.RAG_TOP_K_DENSE,
                    "top_k_keyword": settings.RAG_TOP_K_KEYWORD,
                    "top_k_final": settings.RAG_TOP_K_FINAL,
                    "rrf_k": settings.RAG_RRF_K,
                    "rerank_enabled": settings.RAG_RERANK_ENABLED,
                    "rerank_top_k": settings.RAG_RERANK_TOP_K,
                    "min_similarity_threshold": settings.RAG_MIN_SIMILARITY_THRESHOLD,
                },
                "llm": {
                    "ollama_model": settings.OLLAMA_MODEL,
                    "graph_confidence_threshold": settings.GRAPH_CONFIDENCE_THRESHOLD,
                    "graph_require_grounding": settings.GRAPH_REQUIRE_GROUNDING,
                    "graph_max_entity_chars": settings.GRAPH_MAX_ENTITY_CHARS,
                },
            },
        }
        snap["configuration_hash"] = self._compute_hash(snap)
        return snap

    def _compute_hash(self, snap: dict) -> str:
        snap_copy = deepcopy(snap)
        snap_copy.pop("id", None)
        snap_copy.pop("created_at", None)
        snap_copy.pop("document_id", None)
        canonical = json.dumps(snap_copy, ensure_ascii=True, sort_keys=True)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:16]

    def get_snapshot(self, snapshot_id: str) -> Optional[dict]:
        """Restituisce uno snapshot per ID."""
        with self._lock:
            return self._load(snapshot_id)

    def get_snapshot_by_document(self, doc_id: str) -> Optional[dict]:
        """
        Restituisce lo snapshot associato a un documento.
        """
        with self._lock:
            for f in sorted(self._base_dir.glob("*.json")):
                try:
                    snap = json.loads(f.read_text(encoding="utf-8"))
                    if snap.get("document_id") == doc_id:
                        return snap
                except Exception:
                    pass
            return None


# Istanza singleton
config_snapshot = ConfigurationSnapshotService()