"""
Job Queue leggera — coda su filesystem, nessuna dipendenza esterna.
I job sopravvivono a riavvii del container.
"""

import json
import threading
import uuid
from pathlib import Path
from datetime import datetime
from enum import Enum
from typing import Optional

from app.config import settings


class JobStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class Job:
    """Singolo job di processing."""

    def __init__(self, job_type, payload):
        self.id = str(uuid.uuid4())[:8]
        self.type = job_type
        self.payload = payload
        self.status = JobStatus.PENDING
        self.created_at = datetime.now().isoformat()
        self.started_at = None
        self.completed_at = None
        self.error = None
        self.progress = 0.0
        self.result = None

    def to_dict(self):
        return {
            "id": self.id,
            "type": self.type,
            "payload": self.payload,
            "status": self.status.value,
            "created_at": self.created_at,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "error": self.error,
            "progress": round(self.progress, 2),
            "result": self.result,
        }

    @classmethod
    def from_dict(cls, data):
        job = cls(data["type"], data["payload"])
        job.id = data["id"]
        job.status = JobStatus(data["status"])
        job.created_at = data["created_at"]
        job.started_at = data.get("started_at")
        job.completed_at = data.get("completed_at")
        job.error = data.get("error")
        job.progress = data.get("progress", 0.0)
        job.result = data.get("result")
        return job


class JobQueue:
    """Coda persistente su filesystem."""

    def __init__(self):
        self.queue_dir = settings.DATA_DIR / "jobs"
        self.queue_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def enqueue(self, job_type, payload):
        job = Job(job_type, payload)
        self._save_job(job)
        return job

    def dequeue(self):
        with self._lock:
            jobs = self._list_jobs(status=JobStatus.PENDING)
            if not jobs:
                return None
            job = jobs[0]
            job.status = JobStatus.RUNNING
            job.started_at = datetime.now().isoformat()
            self._save_job(job)
            return job

    def complete(self, job_id, result=None):
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.COMPLETED
            job.completed_at = datetime.now().isoformat()
            job.progress = 1.0
            job.result = result
            self._save_job(job)

    def fail(self, job_id, error):
        job = self.get_job(job_id)
        if job:
            job.status = JobStatus.FAILED
            job.completed_at = datetime.now().isoformat()
            job.error = error
            self._save_job(job)

    def update_progress(self, job_id, progress):
        job = self.get_job(job_id)
        if job:
            job.progress = min(1.0, max(0.0, progress))
            self._save_job(job)

    def get_job(self, job_id):
        path = self.queue_dir / f"{job_id}.json"
        if not path.exists():
            return None
        return Job.from_dict(json.loads(path.read_text(encoding="utf-8")))

    def list_all(self, status=None):
        jobs = self._list_jobs(status=JobStatus(status) if status else None)
        return [j.to_dict() for j in jobs]

    def retry_failed(self):
        with self._lock:
            failed = self._list_jobs(status=JobStatus.FAILED)
            count = 0
            for job in failed:
                job.status = JobStatus.PENDING
                job.started_at = None
                job.completed_at = None
                job.error = None
                job.progress = 0.0
                self._save_job(job)
                count += 1
            return count

    def cancel_pending_for_doc(self, doc_id, reason: str = None):
        """Annulla i job pendenti di un documento (es. dopo la sua eliminazione).

        Evita che il worker processi un documento non più esistente e registri
        un errore fuorviante nella cronologia delle attività. Il motivo è
        personalizzabile: viene usato anche per ripulire job derivati
        residui prima di un nuovo processing.
        """
        with self._lock:
            count = 0
            for job in self._list_jobs(status=JobStatus.PENDING):
                if job.payload.get("doc_id") == doc_id:
                    job.status = JobStatus.FAILED
                    job.completed_at = datetime.now().isoformat()
                    job.error = reason or "Annullato: documento eliminato prima del processing"
                    self._save_job(job)
                    count += 1
            return count

    def has_active_for_doc(self, doc_id, job_type=None):
        """True se esiste un job pendente o in esecuzione per il documento.

        Usato come guardia contro doppioni (es. reprocessing richiesto mentre
        un altro processing dello stesso documento è ancora in corso).
        """
        for st in (JobStatus.PENDING, JobStatus.RUNNING):
            for job in self._list_jobs(status=st):
                if job.payload.get("doc_id") == doc_id and (job_type is None or job.type == job_type):
                    return True
        return False

    def _list_jobs(self, status=None):
        jobs = []
        for f in self.queue_dir.glob("*.json"):
            try:
                job = Job.from_dict(json.loads(f.read_text(encoding="utf-8")))
                if status is None or job.status == status:
                    jobs.append(job)
            except Exception:
                pass
        jobs.sort(key=lambda j: j.created_at)
        return jobs

    def _save_job(self, job):
        path = self.queue_dir / f"{job.id}.json"
        path.write_text(json.dumps(job.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


job_queue = JobQueue()