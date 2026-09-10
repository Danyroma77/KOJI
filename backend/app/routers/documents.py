"""
=============================================================================
ROUTER DOCUMENTI — UPLOAD, LISTA, DELETE, DOWNLOAD
=============================================================================

Questo router gestisce tutte le operazioni sui documenti della Knowledge Base:
- Upload di nuovi documenti (con job in background)
- Lista e filtraggio documenti
- Download e visualizzazione contenuto
- Eliminazione (con pulizia artefatti)
- Reprocessing e rigenerazione wiki/grafo

ENDPOINT PRINCIPALI:
POST   /api/documents/upload          — Carica nuovi documenti
GET    /api/documents                 — Lista documenti (con filtri)
GET    /api/documents/{doc_id}        — Dettaglio singolo documento
DELETE /api/documents/{doc_id}        — Elimina documento e artefatti
GET    /api/documents/{doc_id}/download       — Download file originale
GET    /api/documents/{doc_id}/content        — Contenuto testo normalizzato
POST   /api/documents/{doc_id}/reprocess      — Rielabora documento
POST   /api/documents/{doc_id}/regenerate-wiki — Rigenera wiki
POST   /api/documents/{doc_id}/regenerate-graph — Rigenera grafo

GESTIONE CATALOGO:
- Il catalogo è un file JSON con metadati di ogni documento
- Contiene: id, filename, formato, stato, metadati, timestamp
- Viene letto/scritto da API e worker (processi separati)

ARTEFATTI DOCUMENTO:
- raw: file originale (non modificato)
- processed: testo normalizzato in Markdown
- vettori: embedding in ChromaDB
- nodi/archi: entità nel Knowledge Graph
"""

from __future__ import annotations
import json
import uuid
import asyncio
import os
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, UploadFile, File, HTTPException, BackgroundTasks, Query
from fastapi.responses import FileResponse, PlainTextResponse

from app.config import settings
from app.models import (
    DocumentUploadResponse, DocumentCatalogEntry, DocumentListResponse,
    DocumentStatus, DocumentFormat, DocumentMetadata, DocumentTechMeta,
    ActivityAction, ActivityEntry, ActivityListResponse,
    DocumentMetadataUpdate,
    ProcessingDetailResponse, ProcessingRunResponse,
    ConfigurationSnapshotResponse,
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

# Router con prefisso /api/documents
router = APIRouter(prefix="/documents", tags=["documents"])


# =============================================================================
# FUNZIONI DI ACCESSO AL CATALOGO
# =============================================================================
# Il catalogo è un file JSON che contiene i metadati di tutti i documenti.
# Viene condiviso tra API e worker (entrambi processi separati).

def _load_catalog() -> dict:
    """
    Carica il catalogo documenti dal disco.
    
    Returns:
        Dict con chiave "documents" contenente la lista dei documenti.
        Se il file non esiste, ritorna un catalogo vuoto.
    """
    if settings.CATALOG_FILE.exists():
        return json.loads(settings.CATALOG_FILE.read_text(encoding="utf-8"))
    return {"documents": []}


def _save_catalog(catalog: dict):
    """
    Salva il catalogo documenti su disco.
    
    Args:
        catalog: Dict con i dati del catalogo da salvare
        
    Note:
        - Crea la directory se non esiste
        - Scrive in UTF-8 con indentazione per leggibilità
    """
    settings.CATALOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    settings.CATALOG_FILE.write_text(
        json.dumps(catalog, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _get_format(filename: str) -> DocumentFormat:
    """
    Inferisce il formato del documento dall'estensione del file.
    
    Args:
        filename: Nome del file con estensione
        
    Returns:
        DocumentFormat corrispondente, o TEXT se sconosciuto
    """
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


def _reset_indexing_artifacts(doc_id: str):
    """Reset dei soli artefatti derivati del documento: vettori, nodi grafo
    e testo normalizzato. PRESERVA il file raw — serve al reprocessing,
    in cui il documento esiste già e va solo ri-elaborato."""
    vector_store.delete_by_doc(doc_id)
    graph_builder.remove_by_doc(doc_id)
    processed = settings.PROCESSED_DIR / f"{doc_id}.md"
    if processed.exists():
        processed.unlink()


async def _process_document(doc_id: str, filename: str, file_bytes: bytes, catalog: dict):
    """Pipeline completa di processing per un singolo documento.

    Flusso: Parse → Normalize → Chunk → Embed → Index → (Wiki → Graph).
    Nota: questo percorso è mantenuto per compatibilità/test; il percorso
    reale di caricamento usa il worker (process_document job) che accoda la
    wiki e, al suo completamento, il grafo (sequenza wiki → grafo).
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
                doc["chunk_strategy"] = settings.CHUNK_STRATEGY
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

            # Validazione dimensione (BE-RF-02): limite configurabile in MB
            max_bytes = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024
            if len(file_bytes) > max_bytes:
                raise ValueError(
                    f"file troppo grande ({len(file_bytes) / (1024 * 1024):.1f} MB, "
                    f"massimo {settings.MAX_UPLOAD_SIZE_MB} MB)"
                )

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


@router.patch("/{doc_id}", response_model=DocumentCatalogEntry)
async def update_document_metadata(doc_id: str, update: DocumentMetadataUpdate):
    """Modifica i metadati di un documento (BE-RF-09).

    Aggiorna i metadati structural (title, author, date, language, pages) e
    semantic (topics, entities) del documento. Le modifiche sono immediate
    sul catalogo; gli artefatti derivati (wiki/grafo) vengono rigenerati
    tramite i job dedicati se necessario.
    """
    from datetime import datetime
    catalog = _load_catalog()
    doc = next((d for d in catalog["documents"] if d.get("id") == doc_id), None)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Documento {doc_id} non trovato")

    changes = update.model_dump(exclude_unset=True)
    structural_keys = {"title", "author", "date", "language", "pages"}

    structural = dict(doc.get("metadata_structural") or {})
    semantic = dict(doc.get("metadata_semantic") or {})
    for key, value in changes.items():
        if key in structural_keys:
            structural[key] = value
        elif key in ("topics", "entities"):
            semantic[key] = value

    doc["metadata_structural"] = structural
    doc["metadata_semantic"] = semantic
    doc["updated_at"] = datetime.now().isoformat()
    _save_catalog(catalog)
    activity_log.log(
        ActivityAction.MODIFIED,
        doc.get("filename", "documento"),
        doc_id,
        detail="metadati aggiornati",
    )
    return DocumentCatalogEntry(**doc)


@router.get("/activities", response_model=ActivityListResponse)
async def list_activities(
    limit: int = Query(default=20, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
):
    """Cronologia delle attività sulla KB.

    Traccia oltre agli upload anche le modifiche (sovrascrittura di un file
    esistente) e le eliminazioni — eventi che altrimenti sparirebbero dal
    catalogo. Al primo avvio popola il log dai documenti già presenti.

    Paginazione server-side: `offset` + `limit` permettono di scorrere tutto
    il log (MAX_ACTIVITIES = 200, quindi un cap di limit=200 basta a coprirlo
    in una sola richiesta). `total` riporta il numero complessivo di eventi
    registrati, così il client può calcolare quante pagine esistono.
    """
    # Nota: la route è dichiarata prima di /{doc_id} per evitare che
    # "activities" venga interpretato come un id documento.
    catalog = _load_catalog()
    activity_log.seed_from_catalog(catalog["documents"])
    entries, total_count = activity_log.list_page(offset=offset, limit=limit)
    return ActivityListResponse(
        activities=[ActivityEntry(**e) for e in entries],
        total=total_count,
    )


@router.delete("/all")
async def delete_all_documents(background_tasks: BackgroundTasks):
    """Svuota la Knowledge Base: elimina tutti i documenti con i loro artefatti.

    Ogni rimozione viene tracciata nella cronologia attività (azione 'deleted')
    e i job ancora in coda vengono annullati. Per logica, svuotando la KB
    vengono eliminati ANCHE gli artefatti derivati: il grafo viene azzerato
    (graph.json rimosso) e la wiki viene svuotata (pagine e indice) — non
    vengono rigenerati, non avendo più documenti da cui derivare.
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

    # Svuotamento garantito degli artefatti derivati: il grafo viene azzerato
    # completamente (anche di eventuali nodi stanti non più referenziati) e la
    # wiki viene svuotata. Nessuna rigenerazione: senza documenti non hanno
    # da cosa derivare.
    graph_builder.reset()
    wiki_generator.reset()

    return {
        "status": "ok",
        "removed": len(docs),
        "message": f"Rimossi {len(docs)} documenti dalla KB (wiki e grafo eliminati)",
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


@router.get("/{doc_id}/text")
async def get_document_text(doc_id: str):
    """Restituisce il testo estratto dal documento (per il viewer della KB).

    A differenza di /download (che serve il file originale, anche binario
    per PDF/DOCX), qui si restituisce il testo normalizzato prodotto dalla
    pipeline di parsing — leggibile per qualsiasi formato.
    """
    catalog = _load_catalog()
    doc_entry = next((d for d in catalog["documents"] if d["id"] == doc_id), None)

    if not doc_entry:
        raise HTTPException(status_code=404, detail="Documento non trovato")

    processed_path = settings.PROCESSED_DIR / f"{doc_id}.md"
    if not processed_path.exists():
        raise HTTPException(
            status_code=404,
            detail="Testo non disponibile: il documento non è ancora stato processato",
        )

    return PlainTextResponse(
        content=processed_path.read_text(encoding="utf-8", errors="replace"),
        media_type="text/plain; charset=utf-8",
    )


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


# ============ Azioni per singolo documento (richieste da interfaccia) ============

@router.post("/{doc_id}/reprocess")
async def reprocess_document(doc_id: str):
    """Richiede un nuovo processing (parsing→wiki/grafo) del file originale.

    Non richiede un nuovo upload: il file raw già presente su disco viene
    ri-elaborato. I vecchi artefatti indicizzati (vettori, grafo, testo
    normalizzato) vengono azzerati; wiki e grafo verranno rigenerati dai job
    indipendenti accodati automaticamente a fine processing.
    """
    from app.services.job_queue import job_queue

    catalog = _load_catalog()
    doc_entry = next((d for d in catalog["documents"] if d["id"] == doc_id), None)
    if not doc_entry:
        raise HTTPException(status_code=404, detail=f"Documento {doc_id} non trovato")

    filename = doc_entry["filename"]
    raw_files = list(settings.RAW_DIR.glob(f"{doc_id}_*"))
    if not raw_files:
        raise HTTPException(
            status_code=404,
            detail="File originale non disponibile su disco: impossibile riprocessare",
        )

    # Annulla eventuali job ancora pendenti per questo documento (es. wiki/grafo
    # della precedente elaborazione) prima di accodarne di nuovi.
    job_queue.cancel_pending_for_doc(
        doc_id, reason="Annullato: sostituito da un nuovo processing richiesto"
    )

    # Guardia anti-doppione: un processing per questo documento non deve
    # mai essere in coda o in esecuzione due volte contemporaneamente.
    if job_queue.has_active_for_doc(doc_id, job_type="process_document"):
        raise HTTPException(
            status_code=409,
            detail="Un processing di questo documento è già in corso o in coda",
        )

    # Azzera gli artefatti derivati mantenendo il file raw
    _reset_indexing_artifacts(doc_id)

    # Riparte come un caricamento: il worker eseguirà l'intera catena
    doc_entry["status"] = DocumentStatus.UPLOADED.value
    doc_entry["error_message"] = None
    doc_entry["chunks_count"] = None
    doc_entry["updated_at"] = datetime.now().isoformat()
    _save_catalog(catalog)

    activity_log.log(ActivityAction.REPROCESSING, filename, doc_id)

    raw_path = raw_files[0]
    job = job_queue.enqueue("process_document", {
        "doc_id": doc_id,
        "filename": filename,
        "raw_path": str(raw_path),
    })
    logger.info("Accodato reprocessing %s per %s", job.id, filename)

    return {
        "status": "ok",
        "job_id": job.id,
        "message": f"Riprocessamento di '{filename}' accodato",
    }


@router.post("/{doc_id}/regenerate-wiki")
async def regenerate_wiki_for_document(doc_id: str):
    """Accoda la rigenerazione della wiki (globale) che include il documento.

    La wiki aggrega sezioni da tutti i documenti pronti: la richiesta parte
    dal singolo documento ma la ricostruzione copre l'intera KB. Job indipendente:
    un eventuale fallimento non tocca grafo né indicizzazione.
    """
    from app.services.job_queue import job_queue

    catalog = _load_catalog()
    doc_entry = next((d for d in catalog["documents"] if d["id"] == doc_id), None)
    if not doc_entry:
        raise HTTPException(status_code=404, detail=f"Documento {doc_id} non trovato")

    job = job_queue.enqueue("generate_wiki", {
        "doc_id": doc_id,
        "filename": doc_entry["filename"],
    })
    logger.info("Accodata rigenerazione wiki %s per %s", job.id, doc_entry["filename"])

    return {
        "status": "ok",
        "job_id": job.id,
        "message": "Rigenerazione wiki accodata",
    }


@router.post("/{doc_id}/regenerate-graph")
async def regenerate_graph_for_document(doc_id: str):
    """Accoda la ri-estrazione del grafo per il singolo documento tramite LLM.

    Le triple precedenti del documento vengono rimosse dal job e sostituite.
    Operazione indipendente: non modifica chunk, wiki né stato di indicizzazione.
    """
    from app.services.job_queue import job_queue

    catalog = _load_catalog()
    doc_entry = next((d for d in catalog["documents"] if d["id"] == doc_id), None)
    if not doc_entry:
        raise HTTPException(status_code=404, detail=f"Documento {doc_id} non trovato")

    job = job_queue.enqueue("generate_graph", {
        "doc_id": doc_id,
        "filename": doc_entry["filename"],
    })
    logger.info("Accodata ri-estrazione grafo %s per %s", job.id, doc_entry["filename"])

    return {
        "status": "ok",
        "job_id": job.id,
        "message": f"Estrazione grafo di '{doc_entry['filename']}' accodata",
    }


async def _regenerate_wiki(catalog: dict):
    """Rigenera la wiki da tutti i documenti pronti.

    Se non c'è alcun documento pronto (es. eliminato l'ultimo documento),
    la wiki viene azzerata: è un artefatto derivato e non deve sopravvivere
    ai documenti da cui era stata generata.
    """
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
        wiki_generator.generate_all_sync(docs_for_wiki)
    else:
        wiki_generator.reset()

@router.get("/{doc_id}/processing")
async def get_document_processing(doc_id: str):
    """Stato di processing di un documento con run corrente e cronologia.

    Restituisce:
    - current_run: ultimo ProcessingRun (o null se non presente)
    - history: lista di tutti i ProcessingRun ordinati per started_at decrescente
    """
    from app.services.processing_tracker import processing_tracker
    from app.services.config_snapshot import config_snapshot

    catalog = _load_catalog()
    doc_entry = next((d for d in catalog["documents"] if d["id"] == doc_id), None)
    if not doc_entry:
        raise HTTPException(status_code=404, detail=f"Documento {doc_id} non trovato")

    current_run_raw = processing_tracker.get_current_run(doc_id)
    history_raw = processing_tracker.get_runs_for_document(doc_id)

    def _build_snapshot_model(snap_id: Optional[str]) -> Optional[ConfigurationSnapshotResponse]:
        if not snap_id:
            return None
        snap = config_snapshot.get_snapshot(snap_id)
        if not snap:
            return None
        return ConfigurationSnapshotResponse(
            id=snap["id"],
            document_id=snap.get("document_id", doc_id),
            created_at=snap.get("created_at", ""),
            configuration_hash=snap.get("configuration_hash", ""),
            sections=snap.get("sections", {}),
        )

    def _build_run_model(run_raw: Optional[dict]) -> Optional[ProcessingRunResponse]:
        if not run_raw:
            return None
        snap_id = run_raw.get("snapshot_id")
        return ProcessingRunResponse(
            id=run_raw["id"],
            run_type=run_raw.get("run_type", "initial"),
            status=run_raw.get("status", "pending"),
            current_stage=run_raw.get("current_stage"),
            started_at=run_raw.get("started_at"),
            completed_at=run_raw.get("completed_at"),
            duration_ms=run_raw.get("duration_ms"),
            configuration_snapshot=_build_snapshot_model(snap_id),
            stages=run_raw.get("stages", {}),
            error=run_raw.get("error"),
        )

    current_run = _build_run_model(current_run_raw)
    history = [_build_run_model(r) for r in history_raw]

    return ProcessingDetailResponse(
        document_id=doc_id,
        current_run=current_run,
        history=history,
    )


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