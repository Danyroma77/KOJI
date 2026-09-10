"""
Test per ProcessingTracker e ConfigurationSnapshot (FASE 1B).

Coordina:
- processing_tracker: stages, run, counters, fail/complete
- config_snapshot: snapshot immutabili, hash
- worker: pipeline completa su documento reale (FASE 1B)
- endpoint API: GET /api/documents/{id}/processing
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import uuid
from copy import deepcopy
from pathlib import Path
from typing import Any, Optional

import pytest

BACKEND_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(BACKEND_DIR))

TMP_DATA = Path(tempfile.mkdtemp(prefix="koji_test_"))
os.environ["KOJI_DATA_DIR"] = str(TMP_DATA)

from app.config import settings  # noqa: E402
from app.services.processing_tracker import (  # noqa: E402
    ProcessingTracker,
    StageStatus,
    RunStatus,
    StageType,
    RunType,
)
from app.services.config_snapshot import (  # noqa: E402
    ConfigurationSnapshotService,
    config_snapshot,
)
from app.models import (  # noqa: E402
    ProcessingStageResponse,
    ConfigurationSnapshotResponse,
    ProcessingRunResponse,
    ProcessingDetailResponse,
    DocumentStatus,
)


def _clean_tracker_fs() -> None:
    """Rimuove i file JSON del tracker e degli snapshot."""
    for sub in ("processing", "snapshots", "jobs", "activity"):

# ---------------------------------------------------------------------------
# 2-9. START / COMPLETE / FAIL STAGE + COUNTERS
# ---------------------------------------------------------------------------


class TestStageLifecycle:
    def _make_run(self):
        doc_id = str(uuid.uuid4())
        snap = str(uuid.uuid4())[:12]
        return doc_id, processing_tracker.create_run(
            doc_id, RunType.INITIAL, snap, []
        )

    def test_start_stage_sets_running(self):
        doc_id, run = self._make_run()
        s = processing_tracker.start_stage(
            run["id"], doc_id, StageType.PARSING
        )
        assert s["status"] == StageStatus.RUNNING.value
        assert s["started_at"] is not None
        assert s["completed_at"] is None

    def test_complete_stage_sets_completed(self):
        doc_id, run = self._make_run()
        processing_tracker.start_stage(
            run["id"], doc_id, StageType.EMBEDDING
        )
        s = processing_tracker.complete_stage(
            run["id"], doc_id, StageType.EMBEDDING,
            counters={"embeddings_created": 42},
        )
        assert s["status"] == StageStatus.COMPLETED.value
        assert s["duration_ms"] is not None
        assert s["counters"]["embeddings_created"] == 42

    def test_fail_stage_sets_error(self):
        doc_id, run = self._make_run()
        processing_tracker.start_stage(
            run["id"], doc_id, StageType.NORMALIZATION
        )
        s = processing_tracker.fail_stage(
            run["id"], doc_id, StageType.NORMALIZATION, "err",
        )
        assert s["status"] == StageStatus.ERROR.value
        assert s["error_message"] == "err"
        assert s["counters"] == {}
        fetched = processing_tracker.get_run(run["id"], doc_id)
        assert fetched["status"] == RunStatus.ERROR.value

    def test_counters_chunking_embedding_vectorindex(self):
        doc_id, run = self._make_run()
        rid = run["id"]
        for st, cnt in [
            (StageType.CHUNKING, {"chunks_created": 12}),
            (StageType.EMBEDDING, {"embeddings_created": 12}),
            (StageType.VECTOR_INDEX, {"vectors_indexed": 12}),
        ]:
            processing_tracker.start_stage(rid, doc_id, st)
            s = processing_tracker.complete_stage(
                rid, doc_id, st, counters=cnt
            )
            assert s["counters"] == cnt

    def test_counter_bm25(self):
        doc_id, run = self._make_run()
        rid = run["id"]
        processing_tracker.start_stage(rid, doc_id, StageType.BM25)
        s = processing_tracker.complete_stage(
            rid, doc_id, StageType.BM25,
            counters={"documents_indexed": 5},
        )
        assert s["counters"]["documents_indexed"] == 5

    def test_counter_wiki(self):
        doc_id, run = self._make_run()
        rid = run["id"]
        processing_tracker.start_stage(rid, doc_id, StageType.WIKI)
        s = processing_tracker.complete_stage(
            rid, doc_id, StageType.WIKI,
            counters={"pages_created": 3},
        )
        assert s["counters"]["pages_created"] == 3

    def test_counter_graph(self):
        doc_id, run = self._make_run()
        rid = run["id"]
        processing_tracker.start_stage(rid, doc_id, StageType.GRAPH)
        s = processing_tracker.complete_stage(
            rid, doc_id, StageType.GRAPH,
            counters={"entities_created": 3, "relations_created": 5},
        )
        assert s["counters"]["entities_created"] == 3
        assert s["counters"]["relations_created"] == 5

    def test_complete_run(self):
        doc_id, run = self._make_run()
        completed = processing_tracker.complete_run(run["id"], doc_id)
        assert completed["status"] == RunStatus.COMPLETED.value
        assert completed["duration_ms"] is not None
        assert completed["current_stage"] is None

    def test_fail_stage_propagates_to_run(self):
        doc_id, run = self._make_run()
        rid = run["id"]
        processing_tracker.start_stage(rid, doc_id, StageType.PARSING)
        processing_tracker.complete_stage(rid, doc_id, StageType.PARSING)
        processing_tracker.start_stage(rid, doc_id, StageType.CHUNKING)
        processing_tracker.fail_stage(
            rid, doc_id, StageType.CHUNKING, "chunk err"
        )
        fetched = processing_tracker.get_run(rid, doc_id)
        assert fetched["status"] == RunStatus.ERROR.value
        assert fetched["current_stage"] == StageType.CHUNKING.value

    def test_concurrent_access(self):
        doc_id, run = self._make_run()
        rid = run["id"]
        errs: list[Exception] = []

        def w(st, c):
            try:
                processing_tracker.start_stage(rid, doc_id, st)
                time.sleep(0.02)
                processing_tracker.complete_stage(
                    rid, doc_id, st, counters={"c": c}
                )
            except Exception as e:
                errs.append(e)

        threads = [
            threading.Thread(target=w, args=(StageType.PARSING, 1)),
            threading.Thread(
                target=w, args=(StageType.NORMALIZATION, 2)
            ),
            threading.Thread(target=w, args=(StageType.CHUNKING, 3)),
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert not errs

        d = settings.DATA_DIR / sub
        if d.exists():
            for f in d.glob("*.json"):
                f.unlink()
            d.rmdir()


def _ensure_dirs() -> None:
    for sub in ("processing", "snapshots", "jobs", "activity"):
        (settings.DATA_DIR / sub).mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# FIXTURE: DATA_DIR temporaneo + reset servizi singleton
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _reset_global_state(monkeypatch: pytest.MonkeyPatch):
    """Usa un DATA_DIR temporaneo e resetta i servizi singleton."""
    monkeypatch.setattr(settings, "DATA_DIR", TMP_DATA)
    _clean_tracker_fs()
    _ensure_dirs()

    from app.services.processing_tracker import ProcessingTracker
    from app.services.config_snapshot import ConfigurationSnapshotService
    from app.services.activity_log import ActivityLogService
    from app.services.job_queue import JobQueueService

    processing_tracker._base_dir = TMP_DATA / "processing"
    processing_tracker._base_dir.mkdir(parents=True, exist_ok=True)
    config_snapshot._base_dir = TMP_DATA / "snapshots"
    config_snapshot._base_dir.mkdir(parents=True, exist_ok=True)
    activity_log._base_dir = TMP_DATA / "activity"
    activity_log._base_dir.mkdir(parents=True, exist_ok=True)
    job_queue._base_dir = TMP_DATA / "jobs"
    job_queue._base_dir.mkdir(parents=True, exist_ok=True)

    yield


# ---------------------------------------------------------------------------
# 1. CREATE RUN → tutti gli 8 stage PENDING
# ---------------------------------------------------------------------------


class TestCreateRun:
    def test_all_eight_stages_pending(self):
        doc_id = str(uuid.uuid4())
        snap = str(uuid.uuid4())[:12]
        run = processing_tracker.create_run(
            doc_id, RunType.INITIAL, snap, []
        )
        assert run["status"] == RunStatus.PENDING.value
        assert run["current_stage"] is None
        assert run["snapshot_id"] == snap
        assert len(run["stages"]) == 8
        for st in StageType:
            assert st.value in run["stages"]
            s = run["stages"][st.value]
            assert s["status"] == StageStatus.PENDING.value
            assert s["started_at"] is None
            assert s["completed_at"] is None
            assert s["duration_ms"] is None

    def test_get_run(self):
        doc_id = str(uuid.uuid4())
        snap = str(uuid.uuid4())[:12]
        run = processing_tracker.create_run(
            doc_id, RunType.INITIAL, snap, []
        )
        fetched = processing_tracker.get_run(run["id"], doc_id)
        assert fetched["id"] == run["id"]

    def test_get_current_run(self):
        doc_id = str(uuid.uuid4())
        snap1 = str(uuid.uuid4())[:12]
        r1 = processing_tracker.create_run(
            doc_id, RunType.INITIAL, snap1, []
        )
        snap2 = str(uuid.uuid4())[:12]
        r2 = processing_tracker.create_run(
            doc_id, RunType.INITIAL, snap2, []
        )
        cur = processing_tracker.get_current_run(doc_id)
        assert cur["id"] == r2["id"]

    def test_doc_without_runs(self):
        doc_id = str(uuid.uuid4())
        assert processing_tracker.get_runs_for_document(doc_id) == []
        assert processing_tracker.get_current_run(doc_id) is None
