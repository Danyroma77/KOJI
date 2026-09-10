"""
=============================================================================
PROCESSING TRACKER — TRACCIAMENTO DETTAGLIATO DEL PROCESSING DOCUMENTI
=============================================================================

Persiste ProcessingRun e ProcessingStage su filesystem JSON, coerentemente con
job_queue e activity_log. Thread-safe con lock.

STRUTTURA FILE:
- DATA_DIR/processing/{doc_id}/{run_id}.json   (ProcessingRun)

STATI STAGE:
- PENDING: fase non ancora avviata
- RUNNING: fase in esecuzione
- COMPLETED: fase completata con successo
- ERROR: fase fallita
- SKIPPED: fase non eseguita (es. wiki/graph non chainati)

STATI RUN:
- PENDING: run creato, non ancora avviato
- RUNNING: run in esecuzione
- COMPLETED: run completato
- ERROR: run fallito
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import settings


# =============================================================================
# ENUMERAZIONI
# =============================================================================

class StageStatus(str):
    """Stati di una singola fase di processing."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    SKIPPED = "skipped"


class RunStatus(str):
    """Stati globali di un ProcessingRun."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class StageType(str):
    """Fasi ufficiali della pipeline."""
    PARSING = "PARSING"
    NORMALIZATION = "NORMALIZATION"
    CHUNKING = "CHUNKING"
    EMBEDDING = "EMBEDDING"
    VECTOR_INDEX = "VECTOR_INDEX"
    BM25 = "BM25"
    WIKI = "WIKI"
    GRAPH = "GRAPH"


class RunType(str):
    """Tipo di run per distinguere initial/reprocess/rebuild."""
    INITIAL = "initial"
    REPROCESS = "reprocess"
    REBUILD = "rebuild"


# =============================================================================
# MODELLI DATI (dict-based, persistenti su JSON)
# =============================================================================

STAGE_ORDER = [
    StageType.PARSING,
    StageType.NORMALIZATION,
    StageType.CHUNKING,
    StageType.EMBEDDING,
    StageType.VECTOR_INDEX,
    StageType.BM25,
    StageType.WIKI,
    StageType.GRAPH,
]

STAGE_COUNTERS = {
    StageType.CHUNKING: [("chunks_created", "Chunk creati")],
    StageType.EMBEDDING: [("embeddings_created", "Embedding creati")],
    StageType.VECTOR_INDEX: [("vectors_indexed", "Vettori indicizzati")],
    StageType.BM25: [("documents_indexed", "Documenti BM25 indicizzati")],
    StageType.WIKI: [("pages_created", "Pagine wiki create")],
    StageType.GRAPH: [("entities_created", "Entità create"), ("relations_created", "Relazioni create")],
}


def _now_iso() -> str:
    return datetime.now().isoformat()


def _default_stage(stage_type: StageType) -> dict:
    """Crea una fase in stato PENDING."""
    return {
        "stage": stage_type.value,
        "status": StageStatus.PENDING.value,
        "started_at": None,
        "completed_at": None,
        "duration_ms": None,
        "error_message": None,
        "counters": {},
    }


def _default_run(document_id: str, run_type: RunType, snapshot_id: Optional[str] = None) -> dict:
    """Crea un ProcessingRun in stato PENDING con tutte le fasi inizializzate."""
    return {
        "id": None,
        "document_id": document_id,
        "run_type": run_type.value,
        "status": RunStatus.PENDING.value,
        "current_stage": None,
        "started_at": None,
        "completed_at": None,
        "duration_ms": None,
        "error": None,
        "config_snapshot_id": snapshot_id,
        "stages": {st.value: _default_stage(st) for st in STAGE_ORDER},
    }


# =============================================================================
# TRACKER
# =============================================================================

class ProcessingTracker:
    """
    Traccia i ProcessingRun per documento, persistente su filesystem JSON.
    """

    def __init__(self):
        self._base_dir = settings.DATA_DIR / "processing"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _run_path(self, document_id: str, run_id: str) -> Path:
        doc_dir = self._base_dir / document_id
        doc_dir.mkdir(parents=True, exist_ok=True)
        return doc_dir / f"{run_id}.json"

    def _save_run(self, run: dict) -> dict:
        run_id = run.get("id") or str(uuid.uuid4())[:12]
        run["id"] = run_id
        path = self._run_path(run["document_id"], run_id)
        path.write_text(json.dumps(run, ensure_ascii=False, indent=2), encoding="utf-8")
        return run

    def _load_run(self, document_id: str, run_id: str) -> Optional[dict]:
        path = self._run_path(document_id, run_id)
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))

    def _list_runs_for_document(self, document_id: str) -> list[dict]:
        doc_dir = self._base_dir / document_id
        if not doc_dir.exists():
            return []
        runs = []
        for f in sorted(doc_dir.glob("*.json")):
            try:
                runs.append(json.loads(f.read_text(encoding="utf-8")))
            except Exception:
                pass
        return runs

    def create_run(
        self,
        document_id: str,
        run_type: RunType = RunType.INITIAL,
        snapshot_id: Optional[str] = None,
        existing_runs: Optional[list[dict]] = None,
    ) -> dict:
        with self._lock:
            if run_type == RunType.INITIAL and existing_runs:
                run_type = RunType.REPROCESS
            run = _default_run(document_id, run_type, snapshot_id)
            return self._save_run(run)

    def skip_stage(self, run_id: str, document_id: str, stage_type: StageType, reason: Optional[str] = None) -> dict:
        with self._lock:
            run = self._load_run(document_id, run_id)
            if run is None:
                raise ValueError(f"ProcessingRun {run_id} non trovato per {document_id}")
            stage_key = stage_type.value
            stage = run["stages"].get(stage_key)
            if stage is None:
                raise ValueError(f"Fase {stage_type.value} sconosciuta")
            stage["status"] = StageStatus.SKIPPED.value
            stage["completed_at"] = _now_iso()
            stage["duration_ms"] = 0
            stage["error_message"] = reason
            stage["counters"] = {}
            self._save_run(run)
            return run


    def start_stage(self, run_id: str, document_id: str, stage_type: StageType) -> dict:
        with self._lock:
            run = self._load_run(document_id, run_id)
            if run is None:
                raise ValueError(f"ProcessingRun {run_id} non trovato per {document_id}")
            stage_key = stage_type.value
            stage = run["stages"].get(stage_key)
            if stage is None:
                raise ValueError(f"Fase {stage_type.value} sconosciuta")
            if run["status"] == RunStatus.PENDING.value:
                run["status"] = RunStatus.RUNNING.value
                if not run["started_at"]:
                    run["started_at"] = _now_iso()
            if stage["status"] != StageStatus.PENDING.value:
                return run
            stage["status"] = StageStatus.RUNNING.value
            stage["started_at"] = _now_iso()
            stage["completed_at"] = None
            stage["duration_ms"] = None
            stage["error_message"] = None
            stage["counters"] = {}
            run["current_stage"] = stage_key
            self._save_run(run)
            return run


    def complete_stage(
        self,
        run_id: str,
        document_id: str,
        stage_type: StageType,
        counters: Optional[dict] = None,
    ) -> dict:
        with self._lock:
            run = self._load_run(document_id, run_id)
            if run is None:
                raise ValueError(f"ProcessingRun {run_id} non trovato per {document_id}")
            stage_key = stage_type.value
            stage = run["stages"].get(stage_key)
            if stage is None:
                raise ValueError(f"Fase {stage_type.value} sconosciuta")
            if stage["status"] != StageStatus.RUNNING.value:
                return run
            now = _now_iso()
            started = stage.get("started_at")
            duration_ms = None
            if started:
                try:
                    s = datetime.fromisoformat(started)
                    e = datetime.fromisoformat(now)
                    duration_ms = round((e - s).total_seconds() * 1000)
                except (ValueError, TypeError):
                    duration_ms = None
            stage["status"] = StageStatus.COMPLETED.value
            stage["completed_at"] = now
            stage["duration_ms"] = duration_ms
            stage["error_message"] = None
            stage["counters"] = counters or {}

    def skip_stage(self, run_id: str, document_id: str, stage_type: StageType, reason: Optional[str] = None) -> dict:
        with self._lock:
            run = self._load_run(document_id, run_id)
            if run is None:
                raise ValueError(f"ProcessingRun {run_id} non trovato per {document_id}")
            stage_key = stage_type.value
            stage = run["stages"].get(stage_key)
            if stage is None:
                raise ValueError(f"Fase {stage_type.value} sconosciuta")
            stage["status"] = StageStatus.SKIPPED.value
            stage["completed_at"] = _now_iso()
            stage["duration_ms"] = 0
            stage["error_message"] = reason
            stage["counters"] = {}
            self._save_run(run)
            return run

    def fail_stage(self, run_id: str, document_id: str, stage_type: StageType, error_message: str) -> dict:
        with self._lock:
            run = self._load_run(document_id, run_id)
            if run is None:
                raise ValueError(f"ProcessingRun {run_id} non trovato per {document_id}")
            stage_key = stage_type.value
            stage = run["stages"].get(stage_key)
            if stage is None:
                raise ValueError(f"Fase {stage_type.value} sconosciuta")
            now = _now_iso()
            started = stage.get("started_at")
            duration_ms = None
            if started:
                try:
                    s = datetime.fromisoformat(started)
                    e = datetime.fromisoformat(now)
                    duration_ms = round((e - s).total_seconds() * 1000)
                except (ValueError, TypeError):
                    duration_ms = None
            stage["status"] = StageStatus.ERROR.value
            stage["completed_at"] = now
            stage["duration_ms"] = duration_ms
            stage["error_message"] = error_message
            stage["counters"] = {}
            run["status"] = RunStatus.ERROR.value
            run["completed_at"] = now
            run["duration_ms"] = None
            if not run.get("error"):
                run["error"] = error_message[:500]
            self._save_run(run)
            return run

    def complete_run(self, run_id: str, document_id: str) -> dict:
        with self._lock:
            run = self._load_run(document_id, run_id)
            if run is None:
                raise ValueError(f"ProcessingRun {run_id} non trovato per {document_id}")
            if run["status"] == RunStatus.ERROR.value:
                return run
            now = _now_iso()
            started = run.get("started_at")
            duration_ms = None
            if started:
                try:
                    s = datetime.fromisoformat(started)
                    e = datetime.fromisoformat(now)
                    duration_ms = round((e - s).total_seconds() * 1000)
                except (ValueError, TypeError):
                    duration_ms = None
            run["status"] = RunStatus.COMPLETED.value
            run["completed_at"] = now
            run["duration_ms"] = duration_ms
            run["current_stage"] = None
            self._save_run(run)
            return run

    def get_run(self, run_id: str, document_id: str) -> Optional[dict]:
        with self._lock:
            return self._load_run(document_id, run_id)

    def get_runs_for_document(self, document_id: str) -> list[dict]:
        with self._lock:
            runs = self._list_runs_for_document(document_id)
            runs.sort(key=lambda r: r.get("started_at") or "", reverse=True)
            return runs

    def get_current_run(self, document_id: str) -> Optional[dict]:
        runs = self.get_runs_for_document(document_id)
        return runs[0] if runs else None


# Istanza singleton
processing_tracker = ProcessingTracker()
