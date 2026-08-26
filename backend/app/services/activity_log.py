"""
Activity Log — registro persistente delle attività sulla Knowledge Base.

Traccia gli eventi significativi del ciclo di vita dei documenti:
upload, modifica (sovrascrittura di un file esistente), eliminazione
ed esiti del processing (indicizzato / errore).

Il log è un file JSON nel dataset (activities.json), thread-safe,
con rotazione FIFO per evitare crescita illimitata. Stesso approccio
della JobQueue: nessuna dipendenza esterna, sopravvive ai riavvii.
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.config import settings
from app.models import ActivityAction, DocumentStatus

# Numero massimo di voci conservate nel log (rotazione FIFO)
MAX_ACTIVITIES = 200

# Mappa status del catalogo → azione attività (usata per il seeding a freddo)
_STATUS_TO_ACTION = {
    DocumentStatus.UPLOADED.value: ActivityAction.UPLOADED,
    DocumentStatus.PARSING.value: ActivityAction.PARSING,
    DocumentStatus.NORMALIZING.value: ActivityAction.NORMALIZING,
    DocumentStatus.CHUNKING.value: ActivityAction.CHUNKING,
    DocumentStatus.EMBEDDING.value: ActivityAction.EMBEDDING,
    DocumentStatus.READY.value: ActivityAction.READY,
    DocumentStatus.ERROR.value: ActivityAction.ERROR,
}


class ActivityLog:
    """Registro delle attività su file, thread-safe."""

    def __init__(self):
        self.log_file: Path = settings.ACTIVITY_LOG_FILE
        self._lock = threading.Lock()

    def _read(self) -> list:
        """Legge tutte le voci dal file di log."""
        if not self.log_file.exists():
            return []
        try:
            return json.loads(self.log_file.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _write(self, entries: list):
        """Scrive tutte le voci sul file di log."""
        self.log_file.parent.mkdir(parents=True, exist_ok=True)
        self.log_file.write_text(
            json.dumps(entries, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    def log(
        self,
        action,
        filename: str,
        doc_id: Optional[str] = None,
        detail: Optional[str] = None,
    ) -> dict:
        """Registra una nuova attività e la persiste su disco.

        Args:
            action: Azione tracciata (ActivityAction o stringa equivalente).
            filename: Nome del file interessato.
            doc_id: Identificativo del documento (se ancora presente).
            detail: Dettaglio opzionale (es. "12 chunk", messaggio d'errore).

        Returns:
            La voce di log creata.
        """
        with self._lock:
            entries = self._read()
            action_value = action if isinstance(action, str) else action.value
            entry = {
                "id": uuid.uuid4().hex[:8],
                "action": action_value,
                "doc_id": doc_id,
                "filename": filename,
                "timestamp": datetime.now().isoformat(),
                "detail": detail,
            }
            entries.append(entry)
            if len(entries) > MAX_ACTIVITIES:
                entries = entries[-MAX_ACTIVITIES:]
            self._write(entries)
            return entry

    def list_recent(self, limit: int = 20) -> list:
        """Restituisce le attività più recenti, dalla più nuova alla più vecchia."""
        with self._lock:
            entries = self._read()
        ordered = sorted(entries, key=lambda e: e.get("timestamp", ""), reverse=True)
        return ordered[:limit]

    def seed_from_catalog(self, catalog_docs: list) -> bool:
        """Popola il log a partire dai documenti già presenti nel catalogo.

        Serve solo al primo avvio dopo l'introduzione del log: senza seed la
        cronologia apparirebbe vuota anche con una KB piena. Non fa nulla se il
        log contiene già voci.

        Returns:
            True se il seeding è stato effettuato, False altrimenti.
        """
        with self._lock:
            if self._read():
                return False

            entries = []
            for doc in catalog_docs:
                status = doc.get("status") or DocumentStatus.UPLOADED.value
                action = _STATUS_TO_ACTION.get(status, ActivityAction.UPLOADED)
                detail = None
                if action == ActivityAction.ERROR:
                    detail = (doc.get("error_message") or "")[:80]
                elif action == ActivityAction.READY and doc.get("chunks_count"):
                    detail = f"{doc.get('chunks_count')} chunk"
                entries.append({
                    "id": uuid.uuid4().hex[:8],
                    "action": action.value,
                    "doc_id": doc.get("id"),
                    "filename": doc.get("filename") or "documento",
                    "timestamp": doc.get("updated_at") or datetime.now().isoformat(),
                    "detail": detail,
                })

            entries.sort(key=lambda e: e["timestamp"])
            if len(entries) > MAX_ACTIVITIES:
                entries = entries[-MAX_ACTIVITIES:]
            self._write(entries)
            return True


activity_log = ActivityLog()
