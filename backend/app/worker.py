"""
Koji Worker — Processo separato che esegue i job della coda.
Avviato con: python -m app.worker
Non dipende dall'API — puo essere riavviato indipendentemente.
"""

import logging
import time
import signal
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] worker: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("koji-worker")

_shutdown = False


def signal_handler(sig, frame):
    global _shutdown
    logger.info("Shutdown richiesto — finisco il job corrente...")
    _shutdown = True


signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def process_document_job(job):
    """Esegue il processing completo di un documento."""
    from app.services.document_parser import parse_document, compute_sha256
    from app.services.text_normalizer import normalizer
    from app.services.chunk_manager import chunk_manager
    from app.services.embedding_service import embedding_service
    from app.services.vector_store import vector_store
    from app.services.job_queue import job_queue
    from app.services.activity_log import activity_log
    from app.config import settings
    from app.routers.documents import _load_catalog, _save_catalog, _get_format
    from app.models import DocumentStatus, DocumentTechMeta, DocumentMetadata, ActivityAction
    from pathlib import Path
    from datetime import datetime

    doc_id = job.payload["doc_id"]
    filename = job.payload["filename"]
    raw_path = Path(job.payload["raw_path"])

    catalog = _load_catalog()

    # Il documento può essere stato eliminato mentre il job era in coda:
    # in tal caso si salta il processing senza segnare un errore fittizio
    # nella cronologia delle attività.
    if not any(d["id"] == doc_id for d in catalog["documents"]):
        logger.info("[%s] SALTATO: %s eliminato prima del processing", job.id, filename)
        return {"skipped": True, "filename": filename}

    total_steps = 5

    def update_progress(step, sub=0):
        job_queue.update_progress(job.id, (step + sub * 0.2) / total_steps)

    try:
        logger.info("[%s] Parsing: %s", job.id, filename)
        file_bytes = raw_path.read_bytes()
        parse_result = parse_document(file_bytes, filename)
        update_progress(1)

        logger.info("[%s] Normalizzazione", job.id)
        normalized_text = normalizer.normalize(parse_result.text)
        processed_path = settings.PROCESSED_DIR / f"{doc_id}.md"
        processed_path.write_text(normalized_text, encoding="utf-8")
        update_progress(2)

        logger.info("[%s] Metadati", job.id)
        sha256 = compute_sha256(file_bytes)
        tech_meta = DocumentTechMeta(
            sha256=sha256,
            size_bytes=len(file_bytes),
            # Usa l'enum DocumentFormat: una stringa tipo 'MD' verrebbe
            # rifiutata dalla validazione pydantic e fallirebbe tutto il job.
            format=_get_format(filename),
            upload_timestamp=datetime.now().isoformat(),
        )
        struct_meta = DocumentMetadata(
            title=parse_result.title,
            author=parse_result.author,
            pages=parse_result.pages,
        )
        for doc in catalog["documents"]:
            if doc["id"] == doc_id:
                doc["metadata_structural"] = struct_meta.model_dump()
                doc["metadata_tech"] = tech_meta.model_dump()
                break
        update_progress(3)

        logger.info("[%s] Chunking", job.id)
        chunks = chunk_manager.chunk_text(normalized_text, doc_id)
        update_progress(4)

        logger.info("[%s] Embedding %d chunk", job.id, len(chunks))
        chunk_ids = [f"{c.doc_id}_{c.index}" for c in chunks]
        embeddings = embedding_service.embed_texts([c.text for c in chunks], chunk_ids)

        metadatas = [{
            "doc_id": c.doc_id,
            "chunk_index": c.index,
            "doc_name": filename,
            "title": parse_result.title or filename,
            "start_char": c.start_char,
            "end_char": c.end_char,
        } for c in chunks]

        vector_store.add_chunks(chunks, embeddings, metadatas)
        update_progress(5)

        for doc in catalog["documents"]:
            if doc["id"] == doc_id:
                doc["chunks_count"] = len(chunks)
                doc["status"] = DocumentStatus.READY.value
                doc["updated_at"] = datetime.now().isoformat()
                break
        _save_catalog(catalog)

        # Traccia l'esito positivo del processing nella cronologia attività
        activity_log.log(
            ActivityAction.READY, filename, doc_id,
            detail=f"{len(chunks)} chunk",
        )

        logger.info("[%s] COMPLETATO: %s -> %d chunk", job.id, filename, len(chunks))
        return {"chunks": len(chunks), "filename": filename}

    except Exception as e:
        logger.error("[%s] FALLITO: %s — %s", job.id, filename, e)
        for doc in catalog["documents"]:
            if doc["id"] == doc_id:
                doc["status"] = DocumentStatus.ERROR.value
                doc["error_message"] = str(e)
                doc["updated_at"] = datetime.now().isoformat()
                break
        _save_catalog(catalog)

        # Traccia il fallimento nella cronologia attività
        activity_log.log(ActivityAction.ERROR, filename, doc_id, detail=str(e)[:80])
        raise


JOB_HANDLERS = {
    "process_document": process_document_job,
}


def run_worker():
    """Loop principale del worker."""
    from app.services.job_queue import job_queue

    logger.info("Worker avviato — in attesa di job...")
    idle_count = 0

    while not _shutdown:
        job = job_queue.dequeue()
        if job is None:
            idle_count += 1
            if idle_count == 1:
                logger.info("Nessun job in coda — in attesa...")
            time.sleep(2)
            continue

        idle_count = 0
        handler = JOB_HANDLERS.get(job.type)
        if not handler:
            logger.warning("[%s] Tipo job sconosciuto: %s", job.id, job.type)
            job_queue.fail(job.id, f"Handler non trovato: {job.type}")
            continue

        try:
            result = handler(job)
            job_queue.complete(job.id, result)
        except Exception as e:
            job_queue.fail(job.id, str(e))

    logger.info("Worker fermato.")


if __name__ == "__main__":
    run_worker()