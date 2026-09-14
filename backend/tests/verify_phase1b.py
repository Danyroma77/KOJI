"""
===============================================================================
VERIFICA FASE 1B — E2E reale worker + endpoint processing (uso manuale)
===============================================================================

Esegue un'elaborazione REALE attraverso il worker su un documento di test e
verifica l'endpoint HTTP. Va lanciato con un interprete Python reale che abbia
le dipendenze di backend/requirements.txt installate:

    cd backend
    python scripts/verify_phase1b.py
    # oppure: KOJI_DATA_DIR=/data python scripts/verify_phase1b.py

    # ESECUZIONE IN DOCKER (ambiente ufficiale KOJI):
    #   docker compose build api
    #   docker compose exec koji-api python scripts/verify_phase1b.py

NON dichiara nulla da solo: stampa tutte le evidenze richieste
(document_id, run_id, snapshot_id, run_type, snapshot/run persistiti, 8 stage,
stato finale, timestamp, durata, contatori, errori, risposta endpoint).
La FASE 1B e' completata solo se TUTTE le verifiche tornano.
"""

from __future__ import annotations

import json
import sys
import uuid
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

TEST_CONTENT = """Koji e' una piattaforma locale di gestione della conoscenza.

Il processing di un documento segue una pipeline in otto fasi tracciate.
Ogni fase registra stato, timestamp, durata, contatori ed eventuali errori.

La configurazione usata viene congelata in uno snapshot immutabile.
Lo snapshot permette di riprodurre ogni esperimento di retrieval.

Il tracker persiste ogni run su filesystem in formato JSON.
L'endpoint di processing espone run corrente, cronologia e snapshot.
"""


def _load_catalog(catalog_file: Path) -> dict:
    if catalog_file.exists():
        try:
            data = json.loads(catalog_file.read_text(encoding="utf-8"))
            if isinstance(data, dict) and "documents" in data:
                return data
        except Exception:
            pass
    return {"documents": []}


def _save_catalog(catalog_file: Path, catalog: dict) -> None:
    catalog_file.parent.mkdir(parents=True, exist_ok=True)
    catalog_file.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main() -> int:
    from app.config import settings
    from app.services.job_queue import job_queue
    from app.services.processing_tracker import processing_tracker
    from app.services.config_snapshot import config_snapshot
    from app.worker import JOB_HANDLERS

    doc_id = f"phase1b-{uuid.uuid4().hex[:8]}"
    filename = "phase1b_test.txt"
    raw_path = settings.RAW_DIR / f"{doc_id}.txt"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_text(TEST_CONTENT, encoding="utf-8")

    catalog = _load_catalog(settings.CATALOG_FILE)
    catalog["documents"] = [
        d for d in catalog["documents"] if d.get("id") != doc_id
    ]
    catalog["documents"].append(
        {
            "id": doc_id,
            "filename": filename,
            "format": "txt",
            "status": "uploaded",
            "upload_timestamp": datetime.now().isoformat(),
        }
    )
    _save_catalog(settings.CATALOG_FILE, catalog)

    job = job_queue.enqueue(
        "process_document",
        {"doc_id": doc_id, "filename": filename, "raw_path": str(raw_path)},
    )
    qjob = job_queue.dequeue()
    if qjob is None:
        print("ERRORE: nessun job in coda dopo enqueue", flush=True)
        return 1
    print(f"job_id={qjob.id} doc_id={doc_id}", flush=True)
    try:
        result = JOB_HANDLERS[qjob.type](qjob)
        job_queue.complete(qjob.id, result)
        print(f"worker result: {json.dumps(result, ensure_ascii=False)}", flush=True)
    except Exception as e:  # noqa: BLE001 — l'evidenza della run resta comunque
        job_queue.fail(qjob.id, str(e))
        print(f"worker FAILED: {e}", flush=True)

    run = processing_tracker.get_current_run(doc_id)
    if not run:
        print("ERRORE: nessun ProcessingRun persistito", flush=True)
        return 1
    snap = config_snapshot.get_snapshot(run.get("snapshot_id") or "")
    print("--- RUN ---", flush=True)
    print(json.dumps(run, ensure_ascii=False, indent=2), flush=True)
    print("--- SNAPSHOT ---", flush=True)
    print(json.dumps(snap, ensure_ascii=False, indent=2), flush=True)

    expected = [
        "PARSING", "NORMALIZATION", "CHUNKING", "EMBEDDING",
        "VECTOR_INDEX", "BM25", "WIKI", "GRAPH",
    ]
    missing = [s for s in expected if s not in run.get("stages", {})]
    print(f"missing_stages={missing}", flush=True)
    print(f"run status={run.get('status')} snapshot_found={snap is not None}", flush=True)

    print("--- ENDPOINT GET /api/documents/{id}/processing ---", flush=True)
    from fastapi.testclient import TestClient

    from app.main import app

    client = TestClient(app, raise_server_exceptions=False)
    resp = client.get(f"/api/documents/{doc_id}/processing")
    print(f"http_status={resp.status_code}", flush=True)
    try:
        body = resp.json()
    except Exception:
        body = {"raw": resp.text[:2000]}
    print(json.dumps(body, ensure_ascii=False, indent=2)[:6000], flush=True)
    ok = (
        resp.status_code == 200
        and isinstance(body, dict)
        and body.get("current_run") is not None
        and isinstance(body.get("history"), list)
        and (body.get("current_run") or {}).get("configuration_snapshot") is not None
    )
    print(f"E2E_OK={ok and not missing}", flush=True)
    return 0 if (ok and not missing) else 1


if __name__ == "__main__":
    raise SystemExit(main())
