"""
=============================================================================
KOJI WORKER — PROCESSO SEPARATO PER ESECUZIONE JOB
=============================================================================

Il worker è un processo indipendente dall'API che esegue operazioni lunghe
e CPU-bound in background. Avviato con: python -m app.worker

RESPONSABILITÀ:
- Processare documenti (parsing, normalizzazione, chunking, embedding)
- Generare Knowledge Graph (estrazione entità/relazioni via LLM)
- Generare Wiki semantica (aggregazione contenuti)

VANTAGNI DEL PROCESSO SEPARATO:
- Non blocca l'API durante operazioni lunghe
- Può essere riavviato indipendently dall'API
- Permette scaling separato (più worker se necessario)
- Isola errori: un crash del worker non ferma l'API

GESTIONE SHUTDOWN:
- Riceve SIGTERM/SIGINT per shutdown elegante
- Termina il job corrente prima di uscire
- I job incompleti restano in coda per il prossimo avvio

COMUNICAZIONE:
- Condivide la stessa filesystem dell'API (job queue su disco)
- Usa la stessa directory di dati (/data)
"""

import logging
import time
import signal
import sys
from datetime import datetime

# Configurazione logging specifica per il worker
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] worker: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("koji-worker")

# Flag globale per gestire il shutdown elegante
_shutdown = False


def signal_handler(sig, frame):
    """
    Gestore dei segnali per shutdown elegante.
    
    Quando il processo riceve SIGTERM (Docker stop) o SIGCTRL (Ctrl+C),
    imposta il flag _shutdown per terminare il job corrente e uscire.
    """
    global _shutdown
    logger.info("Shutdown richiesto — finisco il job corrente...")
    _shutdown = True


# Registrazione dei gestori segnali
signal.signal(signal.SIGTERM, signal_handler)
signal.signal(signal.SIGINT, signal_handler)


def process_document_job(job):
    """
    Esegue il processing completo di un documento nella pipeline.

    PIPELINE (8 fasi sequenziali tracciate dal ProcessingTracker):
    1. PARSING: estrazione testo grezzo dal file (PDF, DOCX, etc.)
    2. NORMALIZATION: pulizia e conversione in Markdown uniforme
    3. CHUNKING: suddivisione in segmenti per l'indicizzazione
    4. EMBEDDING: generazione vettori semantici per ogni chunk
    5. VECTOR_INDEX: indicizzazione in ChromaDB
    6. BM25: costruzione indice lessicale
    7. WIKI: generazione pagine wiki semantiche
    8. GRAPH: estrazione entità/relazioni (job separato)

    Ogni fase è tracciata con start_stage/complete_stage/fail_stage.
    La configurazione viene snapshotata all'inizio del processing.

    Args:
        job: Oggetto Job con payload {doc_id, filename, raw_path}
        
    Returns:
        Dict con risultato del processing (chunks_count, skipped, etc.)
        
    Note:
        - Il documento può essere stato eliminato mentre era in coda:
          in tal caso salta il processing senza errori
        - Ogni fase viene tracciata dal ProcessingTracker
        - La configurazione viene snapshotata all'inizio del processing
        - In caso di errore, il documento viene marcato come ERROR
    """
    # Import locali per evitare dipendenze circolari
    from app.services.document_parser import parse_document, compute_sha256
    from app.services.text_normalizer import normalizer
    from app.services.chunk_manager import chunk_manager
    from app.services.embedding_service import embedding_service
    from app.services.vector_store import vector_store
    from app.services.job_queue import job_queue
    from app.services.activity_log import activity_log
    from app.services.processing_tracker import (
        processing_tracker,
        StageType,
        RunType,
    )
    from app.services.config_snapshot import config_snapshot
    from app.services.wiki_generator import wiki_generator
    from app.config import settings
    from app.routers.documents import _load_catalog, _save_catalog, _get_format
    from app.models import DocumentStatus, DocumentTechMeta, DocumentMetadata, ActivityAction
    from app.services.metrics_store import metrics_store
    from pathlib import Path
    import time

    # Estrazione dati dal payload del job
    doc_id = job.payload["doc_id"]
    filename = job.payload["filename"]
    raw_path = Path(job.payload["raw_path"])

    # Caricamento catalogo documenti
    catalog = _load_catalog()

    # Controllo eliminazione: se il documento è stato cancellato mentre era in coda,
    # salta il processing senza segnare un errore fittizio
    if not any(d["id"] == doc_id for d in catalog["documents"]):
        logger.info("[%s] SALTATO: %s eliminato prima del processing", job.id, filename)
        return {"skipped": True, "filename": filename}

    # Percorso dove salvare il testo normalizzato
    processed_path = settings.PROCESSED_DIR / f"{doc_id}.md"

    def _mark_doc_error(msg: str):
        """
        Marca un documento come in errore nel catalogo.
        
        Args:
            msg: Messaggio di errore da salvare
        """
        for doc in catalog["documents"]:
            if doc["id"] == doc_id:
                doc["status"] = DocumentStatus.ERROR.value
                doc["error_message"] = msg
                doc["updated_at"] = datetime.now().isoformat()
                break
        _save_catalog(catalog)

    # =========================================================================
    # FASE 0 — CREAZIONE ProcessingRun E ConfigurationSnapshot
    # =========================================================================
    # Crea uno snapshot immutabile della configurazione corrente
    snapshot = config_snapshot.create_snapshot(doc_id)
    snapshot_id = snapshot["id"]
    logger.info("[%s] ConfigurationSnapshot creato: %s", job.id, snapshot_id)

    # Crea il ProcessingRun associato allo snapshot
    existing_runs = processing_tracker.get_runs_for_document(doc_id)
    run = processing_tracker.create_run(
        doc_id,
        run_type=RunType.INITIAL,
        snapshot_id=snapshot_id,
        existing_runs=existing_runs,
    )
    run_id = run["id"]
    logger.info("[%s] ProcessingRun %s creato per %s", job.id, run_id, filename)

    # =========================================================================
    # FASE 1 — PARSING
    # =========================================================================
    processing_tracker.start_stage(run_id, doc_id, StageType.PARSING)
    parse_result = None
    normalized_text = None
    try:
        logger.info("[%s] Parsing: %s", job.id, filename)
        t_phase = time.time()
        file_bytes = raw_path.read_bytes()
        parse_result = parse_document(file_bytes, filename)
        metrics_store.record_processing(
            doc_id=doc_id, phase="parse",
            duration_s=time.time() - t_phase, filename=filename,
        )
        processing_tracker.complete_stage(
            run_id, doc_id, StageType.PARSING,
            counters={"chars_parsed": len(parse_result.text)}
        )
        logger.info("[%s] PARSING completato: %d caratteri", job.id, len(parse_result.text))
    except Exception as e:
        processing_tracker.fail_stage(run_id, doc_id, StageType.PARSING, str(e))
        _mark_doc_error(str(e))
        activity_log.log(ActivityAction.ERROR, filename, doc_id, detail=str(e)[:80])
        raise

    # =========================================================================
    # FASE 2 — NORMALIZATION
    # =========================================================================
    processing_tracker.start_stage(run_id, doc_id, StageType.NORMALIZATION)
    try:
        logger.info("[%s] Normalizzazione", job.id)
        t_phase = time.time()
        normalized_text = normalizer.normalize(parse_result.text)
        processed_path.write_text(normalized_text, encoding="utf-8")
        metrics_store.record_processing(
            doc_id=doc_id, phase="normalize",
            duration_s=time.time() - t_phase, filename=filename,
        )
        processing_tracker.complete_stage(
            run_id, doc_id, StageType.NORMALIZATION,
            counters={"chars_normalized": len(normalized_text)}
        )
        logger.info("[%s] NORMALIZATION completata: %d caratteri", job.id, len(normalized_text))
    except Exception as e:
        processing_tracker.fail_stage(run_id, doc_id, StageType.NORMALIZATION, str(e))
        _mark_doc_error(str(e))
        activity_log.log(ActivityAction.ERROR, filename, doc_id, detail=str(e)[:80])
        raise

    # =========================================================================
    # Metadati documento (aggiornamento catalogo)
    # =========================================================================
    logger.info("[%s] Metadati", job.id)
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
    for doc in catalog["documents"]:
        if doc["id"] == doc_id:
            doc["metadata_structural"] = struct_meta.model_dump()
            doc["metadata_tech"] = tech_meta.model_dump()
            break
    _save_catalog(catalog)

    # =========================================================================
    # FASE 3 — CHUNKING
    # =========================================================================
    processing_tracker.start_stage(run_id, doc_id, StageType.CHUNKING)
    chunks = []
    chunks_count = 0
    try:
        logger.info("[%s] Chunking", job.id)
        t_phase = time.time()
        chunks = chunk_manager.chunk_text(normalized_text, doc_id)
        chunks_count = len(chunks)
        metrics_store.record_processing(
            doc_id=doc_id, phase="chunk",
            duration_s=time.time() - t_phase, filename=filename,
        )
        processing_tracker.complete_stage(
            run_id, doc_id, StageType.CHUNKING,
            counters={"chunks_created": chunks_count}
        )
        logger.info("[%s] CHUNKING completato: %d chunk", job.id, chunks_count)
    except Exception as e:
        processing_tracker.fail_stage(run_id, doc_id, StageType.CHUNKING, str(e))
        _mark_doc_error(str(e))
        activity_log.log(ActivityAction.ERROR, filename, doc_id, detail=str(e)[:80])
        raise

    # =========================================================================
    # FASE 4 — EMBEDDING
    # =========================================================================
    processing_tracker.start_stage(run_id, doc_id, StageType.EMBEDDING)
    embeddings = []
    try:
        logger.info("[%s] Embedding %d chunk", job.id, len(chunks))
        t_phase = time.time()
        chunk_ids = [f"{c.doc_id}_{c.index}" for c in chunks]
        embeddings = embedding_service.embed_texts([c.text for c in chunks], chunk_ids)
        metrics_store.record_processing(
            doc_id=doc_id, phase="embed",
            duration_s=time.time() - t_phase, filename=filename,
        )
        processing_tracker.complete_stage(
            run_id, doc_id, StageType.EMBEDDING,
            counters={"embeddings_created": len(embeddings)}
        )
        logger.info("[%s] EMBEDDING completato: %d vettori", job.id, len(embeddings))
    except Exception as e:
        processing_tracker.fail_stage(run_id, doc_id, StageType.EMBEDDING, str(e))
        _mark_doc_error(str(e))
        activity_log.log(ActivityAction.ERROR, filename, doc_id, detail=str(e)[:80])
        raise

    # =========================================================================
    # FASE 5 — VECTOR_INDEX
    # =========================================================================
    processing_tracker.start_stage(run_id, doc_id, StageType.VECTOR_INDEX)
    try:
        logger.info("[%s] Indicizzazione vettoriale", job.id)
        t_phase = time.time()
        metadatas = [{
            "doc_id": c.doc_id,
            "chunk_index": c.index,
            "doc_name": filename,
            "title": parse_result.title or filename,
            "start_char": c.start_char,
            "end_char": c.end_char,
        } for c in chunks]
        vector_store.add_chunks(chunks, embeddings, metadatas)
        metrics_store.record_processing(
            doc_id=doc_id, phase="index",
            duration_s=time.time() - t_phase, filename=filename,
        )
        processing_tracker.complete_stage(
            run_id, doc_id, StageType.VECTOR_INDEX,
            counters={"vectors_indexed": len(chunks)}
        )
        logger.info("[%s] VECTOR_INDEX completato: %d vettori", job.id, len(chunks))
    except Exception as e:
        processing_tracker.fail_stage(run_id, doc_id, StageType.VECTOR_INDEX, str(e))
        _mark_doc_error(str(e))
        activity_log.log(ActivityAction.ERROR, filename, doc_id, detail=str(e)[:80])
        raise

    # =========================================================================
    # FASE 6 — BM25
    # =========================================================================
    processing_tracker.start_stage(run_id, doc_id, StageType.BM25)
    try:
        logger.info("[%s] Ricostruzione BM25", job.id)
        t_phase = time.time()
        # Forza il refresh di BM25 per includere i nuovi chunk
        vector_store._maybe_refresh()
        # Conta i documenti unici indicizzati in BM25
        unique_docs = len(set(c.doc_id for c in chunks))
        metrics_store.record_processing(
            doc_id=doc_id, phase="bm25",
            duration_s=time.time() - t_phase, filename=filename,
        )
        processing_tracker.complete_stage(
            run_id, doc_id, StageType.BM25,
            counters={"documents_indexed": unique_docs}
        )
        logger.info("[%s] BM25 completato: %d documenti indicizzati", job.id, unique_docs)
    except Exception as e:
        processing_tracker.fail_stage(run_id, doc_id, StageType.BM25, str(e))
        _mark_doc_error(str(e))
        activity_log.log(ActivityAction.ERROR, filename, doc_id, detail=str(e)[:80])
        raise

    # =========================================================================
    # FASE 7 — WIKI
    # =========================================================================
    processing_tracker.start_stage(run_id, doc_id, StageType.WIKI)
    try:
        logger.info("[%s] Job WIKI (esecuzione sincrona)", job.id)
        t_phase = time.time()

        # Costruisce lista documenti per la wiki: il documento corrente più
        # tutti i documenti già pronti con il file normalizzato.
        docs_for_wiki: list[dict] = []

        # Il documento in elaborazione non è ancora "READY" nel catalogo,
        # ma se il file normalizzato esiste lo includiamo comunque.
        if processed_path.exists():
            meta = None
            for d in catalog["documents"]:
                if d["id"] == doc_id:
                    meta = d.get("metadata_structural")
                    break
            docs_for_wiki.append({
                "id": doc_id,
                "filename": filename,
                "processed_text": processed_path.read_text(encoding="utf-8"),
                "metadata": (meta if isinstance(meta, dict) else {}) or {},
            })

        # Documenti già pronti (escludendo il corrente, già aggiunto sopra).
        for d in catalog["documents"]:
            if d["id"] == doc_id:
                continue
            if d.get("status") != DocumentStatus.READY.value:
                continue
            p = settings.PROCESSED_DIR / f"{d['id']}.md"
            if not p.exists():
                continue
            meta = d.get("metadata_structural")
            docs_for_wiki.append({
                "id": d["id"],
                "filename": d["filename"],
                "processed_text": p.read_text(encoding="utf-8"),
                "metadata": (meta if isinstance(meta, dict) else {}) or {},
            })

        # Conteggio pagine wiki prima della generazione.
        index_before = wiki_generator.get_index()
        pages_before = sum(len(g.get("items", [])) for g in index_before.get("groups", []))

        # Genera wiki (sincrono) — rigenera l'intera wiki con tutti i docs.
        wiki_result = wiki_generator.generate_all_sync(docs_for_wiki)

        # Conteggio pagine wiki dopo.
        index_after = wiki_generator.get_index()
        pages_after = sum(len(g.get("items", [])) for g in index_after.get("groups", []))

        wiki_count = pages_after - pages_before
        if wiki_count < 0:
            wiki_count = pages_after

        metrics_store.record_processing(
            doc_id=doc_id, phase="wiki",
            duration_s=time.time() - t_phase, filename=filename,
        )
        processing_tracker.complete_stage(
            run_id, doc_id, StageType.WIKI,
            counters={"pages_created": wiki_count}
        )
        logger.info("[%s] WIKI completato: %d pagine", job.id, wiki_count)
    except Exception as e:
        processing_tracker.fail_stage(run_id, doc_id, StageType.WIKI, str(e))
        _mark_doc_error(str(e))
        activity_log.log(ActivityAction.ERROR, filename, doc_id, detail=str(e)[:80])
        raise

    # =========================================================================
    # FASE 8 — GRAPH
    # =========================================================================
    processing_tracker.start_stage(run_id, doc_id, StageType.GRAPH)
    try:
        logger.info("[%s] Job GRAPH (esecuzione sincrona)", job.id)
        t_phase = time.time()

        # Conteggio entità/relazioni prima dell'estrazione.
        graph_before = graph_builder.get_graph()
        nodes_before = len(graph_before.get("nodes", []))
        edges_before = len(graph_before.get("edges", []))

        # Legge il testo normalizzato.
        processed_text = ""
        if processed_path.exists():
            processed_text = processed_path.read_text(encoding="utf-8")

        # Ottiene il titolo dai metadati (o dal filename come fallback).
        title = filename
        for d in catalog["documents"]:
            if d["id"] == doc_id:
                meta = d.get("metadata_structural")
                if isinstance(meta, dict) and meta.get("title"):
                    title = meta["title"]
                break

        # Rimuove eventuali triple precedenti del documento (idempotente).
        graph_builder.remove_by_doc(doc_id)

        # Estrae il grafo per il documento.
        triples_added = graph_builder.extract_from_document(doc_id, processed_text, title)

        # Conteggio dopo l'estrazione.
        graph_after = graph_builder.get_graph()
        entities_created = len(graph_after.get("nodes", [])) - nodes_before
        relations_created = len(graph_after.get("edges", [])) - edges_before

        metrics_store.record_processing(
            doc_id=doc_id, phase="graph",
            duration_s=time.time() - t_phase, filename=filename,
        )
        processing_tracker.complete_stage(
            run_id, doc_id, StageType.GRAPH,
            counters={
                "entities_created": entities_created,
                "relations_created": relations_created,
            }
        )
        logger.info(
            "[%s] GRAPH completato: %d entità, %d relazioni",
            job.id, entities_created, relations_created,
        )
    except Exception as e:
        processing_tracker.fail_stage(run_id, doc_id, StageType.GRAPH, str(e))
        _mark_doc_error(str(e))
        activity_log.log(ActivityAction.ERROR, filename, doc_id, detail=str(e)[:80])
        raise

    # =========================================================================
    # COMPLETAMENTO ProcessingRun
    # =========================================================================
    logger.info("[%s] Completamento ProcessingRun %s", job.id, run_id)
    processing_tracker.complete_run(run_id, doc_id)
    logger.info("[%s] ProcessingRun completato con successo", job.id)

    # Aggiornamento catalogo: documento READY
    for doc in catalog["documents"]:
        if doc["id"] == doc_id:
            doc["status"] = DocumentStatus.READY.value
            doc["chunks_count"] = chunks_count
            doc["chunk_strategy"] = settings.CHUNK_STRATEGY
            doc["error_message"] = None
            doc["updated_at"] = datetime.now().isoformat()
            break
    _save_catalog(catalog)

    activity_log.log(
        ActivityAction.READY, filename, doc_id,
        detail=f"{chunks_count} chunk",
    )
    logger.info("[%s] INDICIZZATO: %s -> %d chunk", job.id, filename, chunks_count)

    return {
        "skipped": False,
        "chunks_count": chunks_count,
        "filename": filename,
    }


def generate_graph_job(job):
    """Genera il grafo di conoscenza per UN singolo documento.

    Job indipendente dal processing principale: legge il testo normalizzato
    già salvato su disco, rimuove le triple precedenti del documento e
    ri-estrae tramite LLM. Un errore qui non compromette wiki né RAG.
    """
    import asyncio
    from pathlib import Path

    from app.config import settings
    from app.services.graph_builder import graph_builder
    from app.services.job_queue import job_queue
    from app.services.activity_log import activity_log
    from app.routers.documents import _load_catalog, _save_catalog
    from app.models import ActivityAction, DocumentStatus

    doc_id = job.payload["doc_id"]
    filename = job.payload.get("filename", "documento")

    catalog = _load_catalog()
    doc = next((d for d in catalog["documents"] if d["id"] == doc_id), None)
    if not doc:
        logger.info("[%s] SALTATO: %s eliminato prima della generazione grafo", job.id, filename)
        return {"skipped": True, "filename": filename}

    processed_path = Path(settings.PROCESSED_DIR) / f"{doc_id}.md"
    if not processed_path.exists():
        logger.info("[%s] SALTATO: testo normalizzato assente per %s", job.id, filename)
        return {"skipped": True, "filename": filename, "reason": "testo assente"}

    text = processed_path.read_text(encoding="utf-8")
    if not text.strip():
        return {"skipped": True, "filename": filename, "reason": "testo vuoto"}

    title = (doc.get("metadata_structural") or {}).get("title") or filename

    def _set_graph_ts():
        for d in catalog["documents"]:
            if d["id"] == doc_id:
                d["graph_updated_at"] = datetime.now().isoformat()
                break
        _save_catalog(catalog)

    try:
        logger.info("[%s] Grafo: estrazione triple da %s", job.id, filename)
        # Ricostruzione pulita: prima si rimuovono nodi/archi del documento,
        # poi si estraggono le triple col LLM (Ollama). extract_from_document
        # gestisce internamente gli errori di singolo segmento.
        graph_builder.remove_by_doc(doc_id)
        n_triples = asyncio.run(
            graph_builder.extract_from_document(
                doc_id, text, title,
                progress_cb=lambda done, total: job_queue.update_progress(
                    job.id, 0.1 + 0.85 * done / max(total, 1)
                ),
            )
        )

        _set_graph_ts()
        activity_log.log(
            ActivityAction.GRAPH_EXTRACTED, filename, doc_id,
            detail=f"{n_triples} relazioni",
        )
        logger.info("[%s] GRAFO COMPLETATO: %s -> %d relazioni", job.id, filename, n_triples)
        return {"triples": n_triples, "filename": filename}

    except Exception as e:
        logger.error("[%s] FALLITO (grafo): %s — %s", job.id, filename, e)
        # Il documento non resta "Pronto" se un artefatto derivato è fallito:
        # stato=error e messaggio visibile nella colonna Errore della tabella KB.
        catalog = _load_catalog()
        for d in catalog["documents"]:
            if d["id"] == doc_id:
                d["status"] = DocumentStatus.ERROR.value
                d["error_message"] = f"grafo: {str(e)[:120]}"
                d["updated_at"] = datetime.now().isoformat()
                break
        _save_catalog(catalog)
        activity_log.log(ActivityAction.ERROR, filename, doc_id, detail=f"grafo: {str(e)[:60]}")
        raise


def generate_wiki_job(job):
    """Rigenera la wiki dalla KB (globale), includendo il documento richiesto.

    La wiki è un artefatto aggregato: viene ricostruita da tutti i documenti
    pronti. Se il job arriva dalla pipeline di caricamento (payload
    chain_graph=True) al SUCCESSO accoda il grafo del documento trigger:
    sequenza wiki → grafo. Su errore il grafo NON parte; i job manuali
    (rebuild wiki/grafo) restano indipendenti e non attivano la catena.
    """
    from app.config import settings
    from app.services.wiki_generator import wiki_generator
    from app.services.job_queue import job_queue
    from app.services.activity_log import activity_log
    from app.routers.documents import _load_catalog, _save_catalog
    from app.models import ActivityAction, DocumentStatus

    doc_id = job.payload.get("doc_id")
    filename = job.payload.get("filename", "KB")

    catalog = _load_catalog()

    docs_for_wiki = []
    for entry in catalog["documents"]:
        if entry.get("status") != DocumentStatus.READY.value:
            continue
        processed_path = settings.PROCESSED_DIR / f"{entry['id']}.md"
        if processed_path.exists():
            docs_for_wiki.append({
                "id": entry["id"],
                "filename": entry["filename"],
                "processed_text": processed_path.read_text(encoding="utf-8"),
                "metadata": entry.get("metadata_structural", {}) or {},
            })

    if not docs_for_wiki:
        logger.info("[%s] SALTATO: nessun documento pronto per la wiki", job.id)
        return {"skipped": True, "reason": "nessun documento pronto"}

    try:
        logger.info("[%s] Wiki: rigenerazione da %d documenti", job.id, len(docs_for_wiki))
        wiki_generator.generate_all_sync(docs_for_wiki)

        # Aggiorna il timestamp wiki su tutti i documenti pronti
        # (la ricostruzione è globale, non solo per il documento trigger)
        now = datetime.now().isoformat()
        for entry in catalog["documents"]:
            if entry.get("status") == DocumentStatus.READY.value:
                entry["wiki_updated_at"] = now
        _save_catalog(catalog)

        activity_log.log(
            ActivityAction.WIKI_GENERATED, filename, doc_id,
            detail=f"{len(docs_for_wiki)} documenti",
        )
        logger.info("[%s] WIKI COMPLETATA: %d documenti", job.id, len(docs_for_wiki))

        # Catena wiki → grafo: il grafo del documento trigger viene accodato
        # SOLO dopo il successo della wiki (pipeline: chunk → wiki → grafo).
        # Se la wiki fallisce l'eccezione qui sotto fa terminare il job e il
        # grafo non parte mai. I job manuali non hanno chain_graph.
        graph_job_id = None
        if job.payload.get("chain_graph") and doc_id:
            graph_job = job_queue.enqueue("generate_graph", {
                "doc_id": doc_id,
                "filename": filename,
                "after_wiki": True,
            })
            graph_job_id = graph_job.id
            logger.info(
                "[%s] Wiki completata — accodato grafo %s per %s",
                job.id, graph_job.id, filename,
            )

        return {"documents": len(docs_for_wiki), "filename": filename, "graph_job_id": graph_job_id}

    except Exception as e:
        logger.error("[%s] FALLITO (wiki): %s — %s", job.id, filename, e)
        # Il documento non resta "Pronto" se un artefatto derivato è fallito.
        catalog = _load_catalog()
        for d in catalog["documents"]:
            if d["id"] == doc_id:
                d["status"] = DocumentStatus.ERROR.value
                d["error_message"] = f"wiki: {str(e)[:120]}"
                d["updated_at"] = datetime.now().isoformat()
                break
        _save_catalog(catalog)
        activity_log.log(ActivityAction.ERROR, filename, doc_id, detail=f"wiki: {str(e)[:60]}")
        raise


JOB_HANDLERS = {
    "process_document": process_document_job,
    "generate_graph": generate_graph_job,
    "generate_wiki": generate_wiki_job,
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