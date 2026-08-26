"""
Router Documenti — Upload, lista, delete, download.
Gestisce l'intera pipeline di processing per ogni documento.
"""

from __future__ import annotations
import json
import uuid
import asyncio
import os
import logging
from pathlib import Path
from datetime import datetime

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse

from app.config import settings
from app.models import (
    DocumentUploadResponse, DocumentCatalogEntry, DocumentListResponse,
    DocumentStatus, DocumentFormat, DocumentMetadata, DocumentTechMeta,
    ActivityAction, ActivityEntry, ActivityListResponse,
)
from app.services.document_parser import parse_document, compute_sha256, get_parser
from app.services.text_normalizer import normalizer
from app.services.chunk_manager import chunk_manager
from app.services.embedding_service import embedding_service
from app.services.vector_store import vector_store
from app.services.graph_builder import graph_builder
from app.services.wiki_generator import wiki_generator
from app.services.activity_log import activity_log

logger = logging.getLogger("koji")

router = APIRouter(prefix="/documents", tags=["documents"])


def _load_catalog() -> dict:
    """Carica il catalogo documenti dal disco."""
    if settings.CATALOG_FILE.exists():
        return json.loads(settings.CATALOG_FILE.read_text(encoding="utf-8"))
    return {"documents": []}


def _save_catalog(catalog: dict):
    """Salva il catalogo documenti su disco."""
    settings.CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    settings.CATALOG_FILE.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _get_format(filename: str) -> DocumentFormat:
    """Inferisce il formato dal nome file."""
    ext = Path(filename).suffix.lower().replace(".", "")
    try:
        return DocumentFormat(ext)
    except ValueError:
        return DocumentFormat.TEXT


def _remove_document_artifacts(doc_id: str):
    """Rimuove tutti gli artefatti di un documento: vettori, nodi grafo,
    file raw e file processed. Non tocca il catalogo."""
    vector_store.delete_by_doc(doc_id)
    graph_builder.remove_by_doc(doc_id)
    for f in settings.RAW_DIR.glob(f"{doc_id}_*"):
        f.unlink()
    processed = settings.PROCESSED_DIR / f"{doc_id}.md"
    if processed.exists():
        processed.unlink()


async def _process_document(doc_id: str, filename: str, file_bytes: bytes, catalog: dict):
    """Pipeline completa di processing per un singolo documento.

    Flusso: Parse → Normalize → Chunk → Embed → Index → (Graph → Wiki)
    """
    def _update_status(status: DocumentStatus, error: str = None):
        for doc in catalog["documents"]:
            if doc["id"] == doc_id:
                doc["status"] = status.value
                doc["error_message"] = error
                doc["updated_at"] = datetime.now().isoformat()
                break
        _save_catalog(catalog)

    try:
        # 1. Parsing
        _update_status(DocumentStatus.PARSING)
        parse_result = parse_document(file_bytes, filename)

        # 2. Normalizzazione
        _update_status(DocumentStatus.NORMALIZING)
        normalized_text = normalizer.normalize(parse_result.text)

        # Salva testo normalizzato
        processed_path = settings.PROCESSED_DIR / f"{doc_id}.md"
        processed_path.write_text(normalized_text, encoding="utf-8")

        # 3. Metadati
        sha256 = compute_sha256(file_bytes)
        tech_meta = DocumentTechMeta(
            sha256=sha256,
            size_bytes=len(file_bytes),
            format=_get_format(filename),
            upload_timestamp=datetime.now().isoformat(),
        )
        struct_meta = DocumentMetadata(
            title=parse_result.title,
            author=parse_result.author,
            pages=parse_result.pages,
        )

        # Aggiorna catalogo con metadati
        for doc in catalog["documents"]:
            if doc["id"] == doc_id:
                doc["metadata_structural"] = struct_meta.model_dump()
                doc["metadata_tech"] = tech_meta.model_dump()
                break

        # 4. Chunking
        _update_status(DocumentStatus.CHUNKING)
        chunks = chunk_manager.chunk_text(normalized_text, doc_id)

        # 5. Embedding
        _update_status(DocumentStatus.EMBEDDING)
        chunk_ids = [f"{c.doc_id}_{c.index}" for c in chunks]
        chunk_texts = [c.text for c in chunks]
        embeddings = embedding_service.embed_texts(chunk_texts, chunk_ids)

        # 6. Indicizzazione
        metadatas = []
        for chunk in chunks:
            metadatas.append({
                "doc_id": chunk.doc_id,
                "chunk_index": chunk.index,
                "doc_name": filename,
                "title": parse_result.title or filename,
                "start_char": chunk.start_char,
                "end_char": chunk.end_char,
            })

        vector_store.add_chunks(chunks, embeddings, metadatas)

        # Aggiorna catalogo
        for doc in catalog["documents"]:
            if doc["id"] == doc_id:
                doc["chunks_count"] = len(chunks)
                doc["status"] = DocumentStatus.READY.value
                doc["updated_at"] = datetime.now().isoformat()
                break
        _save_catalog(catalog)

    except Exception as e:
        _update_status(DocumentStatus.ERROR, error=str(e))


@router.post("/upload", response_model=DocumentUploadResponse)
async def upload_documents(
    files: list[UploadFile] = File(...),
):
    """Carica uno o più documenti e li accoda per il processing."""
    from app.services.job_queue import job_queue

    uploaded = []
    errors = []
    catalog = _load_catalog()

    for file in files:
        filename = file.filename or "unknown"
        try:
            get_parser(filename)
            file_bytes = await file.read()
            doc_id = str(uuid.uuid4())[:8]

            # Modifica: se un documento con lo stesso nome esiste già, la nuova
            # versione lo sostituisce (artefatti della vecchia versione rimossi)
            # e l'attività viene tracciata come "modified" invece di "uploaded".
            existing = next(
                (d for d in catalog["documents"] if d.get("filename") == filename),
                None,
            )
            if existing:
                existing_id = existing.get("id")
                _remove_document_artifacts(existing_id)
                catalog["documents"] = [
                    d for d in catalog["documents"] if d.get("id") != existing_id
                ]
                activity_log.log(ActivityAction.MODIFIED, filename, doc_id)
            else:
                activity_log.log(ActivityAction.UPLOADED, filename, doc_id)

            # Salva file raw
            raw_path = settings.RAW_DIR / f"{doc_id}_{filename}"
            raw_path.write_bytes(file_bytes)

            # Catalogo
            catalog["documents"].append({
                "id": doc_id,
                "filename": filename,
                "format": _get_format(filename).value,
                "status": DocumentStatus.UPLOADED.value,
                "chunks_count": None,
                "metadata_structural": None,
                "metadata_semantic": None,
                "metadata_tech": None,
                "error_message": None,
                "updated_at": datetime.now().isoformat(),
            })
            _save_catalog(catalog)

            # Accoda job per il worker
            job = job_queue.enqueue("process_document", {
                "doc_id": doc_id,
                "filename": filename,
                "raw_path": str(raw_path),
            })

            uploaded.append(filename)
            logger.info("Accodato job %s per %s", job.id, filename)

        except ValueError as e:
            errors.append(f"{filename}: {str(e)}")
        except Exception as e:
            errors.append(f"{filename}: errore caricamento ({str(e)})")

    return DocumentUploadResponse(
        uploaded=uploaded, errors=errors, total=len(uploaded),
    )

@router.get("", response_model=DocumentListResponse)
async def list_documents():
    """Restituisce la lista di tutti i documenti nella KB."""
    catalog = _load_catalog()
    docs = [DocumentCatalogEntry(**d) for d in catalog["documents"]]
    total_chunks = sum(d.chunks_count or 0 for d in docs)
    return DocumentListResponse(
        documents=docs,
        total=len(docs),
        total_chunks=total_chunks,
    )


@router.get("/activities", response_model=ActivityListResponse)
async def list_activities(limit: int = Query(default=20, ge=1, le=50)):
    """Cronologia delle attività sulla KB.

    Traccia oltre agli upload anche le modifiche (sovrascrittura di un file
    esistente) e le eliminazioni — eventi che altrimenti sparirebbero dal
    catalogo. Al primo avvio popola il log dai documenti già presenti.
    """
    # Nota: la route è dichiarata prima di /{doc_id} per evitare che
    # "activities" venga interpretato come un id documento.
    catalog = _load_catalog()
    activity_log.seed_from_catalog(catalog["documents"])
    entries = activity_log.list_recent(limit=limit)
    return ActivityListResponse(
        activities=[ActivityEntry(**e) for e in entries],
        total=len(entries),
    )


@router.delete("/all")
async def delete_all_documents(background_tasks: BackgroundTasks):
    """Svuota la Knowledge Base: elimina tutti i documenti con i loro artefatti.

    Ogni rimozione viene tracciata nella cronologia attività (azione 'deleted'),
    i job ancora in coda vengono annullati e la wiki viene rigenerata vuota.
    Nota: la route è dichiarata prima di /{doc_id} per evitare che 'all'
    venga interpretato come un id documento.
    """
    from app.services.job_queue import job_queue

    catalog = _load_catalog()
    docs = list(catalog["documents"])

    # Traccia le eliminazioni PRIMA di svuotare il catalogo: dopo non sarebbe
    # più possibile recuperare nome file e id di ciascun documento.
    for d in docs:
        activity_log.log(
            ActivityAction.DELETED,
            d.get("filename") or "documento",
            d.get("id"),
        )

    for d in docs:
        doc_id = d.get("id")
        if not doc_id:
            continue
        _remove_document_artifacts(doc_id)
        job_queue.cancel_pending_for_doc(doc_id)

    catalog["documents"] = []
    _save_catalog(catalog)

    # Rigenera la wiki in background (con la KB vuota la resetta)
    background_tasks.add_task(_regenerate_wiki, catalog)

    return {
        "status": "ok",
        "removed": len(docs),
        "message": f"Rimossi {len(docs)} documenti dalla KB",
    }


@router.delete("/{doc_id}")
async def delete_document(doc_id: str, background_tasks: BackgroundTasks):
    """Elimina un documento e tutti i suoi chunk, embedding, nodi grafo e pagine wiki."""
    catalog = _load_catalog()
    doc_entry = next((d for d in catalog["documents"] if d["id"] == doc_id), None)

    if not doc_entry:
        raise HTTPException(status_code=404, detail=f"Documento {doc_id} non trovato")

    filename = doc_entry["filename"]

    # Traccia l'eliminazione PRIMA di rimuovere la voce dal catalogo,
    # altrimenti l'evento sarebbe perduto insieme al documento.
    activity_log.log(ActivityAction.DELETED, filename, doc_id)

    # Rimuovi artefatti: vettori, grafo, file raw e processed
    _remove_document_artifacts(doc_id)

    # Annulla eventuali job ancora in coda per questo documento: senza questa
    # tutela il worker processerebbe un file eliminato registrando un errore
    # fittizio nella cronologia delle attività.
    from app.services.job_queue import job_queue
    job_queue.cancel_pending_for_doc(doc_id)

    # Rimuovi dal catalogo
    catalog["documents"] = [d for d in catalog["documents"] if d["id"] != doc_id]
    _save_catalog(catalog)

    # Rigenera wiki in background
    background_tasks.add_task(_regenerate_wiki, catalog)

    return {"status": "ok", "message": f"Documento '{filename}' eliminato"}


@router.get("/{doc_id}/download")
async def download_document(doc_id: str):
    """Scarica il file originale di un documento."""
    catalog = _load_catalog()
    doc_entry = next((d for d in catalog["documents"] if d["id"] == doc_id), None)

    if not doc_entry:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    # Trova il file raw
    raw_files = list(settings.RAW_DIR.glob(f"{doc_id}_*"))
    if not raw_files:
        raise HTTPException(status_code=404, detail="File non trovato su disco")

    return FileResponse(
        path=str(raw_files[0]),
        filename=doc_entry["filename"],
        media_type="application/octet-stream",
    )


async def _regenerate_wiki(catalog: dict):
    """Rigenera la wiki da tutti i documenti pronti."""
    docs_for_wiki = []
    for doc_entry in catalog["documents"]:
        if doc_entry["status"] != DocumentStatus.READY.value:
            continue
        processed_path = settings.PROCESSED_DIR / f"{doc_entry['id']}.md"
        if processed_path.exists():
            docs_for_wiki.append({
                "id": doc_entry["id"],
                "filename": doc_entry["filename"],
                "processed_text": processed_path.read_text(encoding="utf-8"),
                "metadata": doc_entry.get("metadata_structural", {}),
            })

    if docs_for_wiki:
        wiki_generator.generate_all(docs_for_wiki)

@router.get("/jobs")
async def list_jobs(status: str = None):
    """Lista job di processing con stato e progresso."""
    from app.services.job_queue import job_queue
    return job_queue.list_all(status=status)


@router.post("/jobs/retry")
async def retry_failed_jobs():
    """Rimette in coda tutti i job falliti."""
    from app.services.job_queue import job_queue
    count = job_queue.retry_failed()
    return {"status": "ok", "retried": count}