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
    
    PIPELINE (5 fasi sequenziali):
    1. Parsing: estrazione testo grezzo dal file (PDF, DOCX, etc.)
    2. Normalizzazione: pulizia e conversione in Markdown uniforme
    3. Chunking: suddivisione in segmenti per l'indicizzazione
    4. Embedding: generazione vettori semantici per ogni chunk
    5. Indicizzazione: salvataggio in ChromaDB per la ricerca
    
    Args:
        job: Oggetto Job con payload {doc_id, filename, raw_path}
        
    Returns:
        Dict con risultato del processing (chunks_count, skipped, etc.)
        
    Note:
        - Il documento può essere stato eliminato mentre era in coda:
          in tal caso salta il processing senza errori
        - Ogni fase viene misurata per le metriche di performance
        - In caso di errore, il documento viene marcato come ERROR
    """
    # Import locali per evitare dipenze circolari
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

    # Numero totale di fasi per il calcolo del progresso
    total_steps = 5

    def update_progress(step, sub=0):
        """Aggiorna il progresso del job (0.0 - 1.0)."""
        job_queue.update_progress(job.id, (step + sub * 0.2) / total_steps)

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
    # FASE 1 — PARSING + NORMALIZZAZIONE + METADATI
    # =========================================================================
    # Queste operazioni sono sequenziali perché ogni fase produce l'input
    # per la successiva. Un errore qui rende impossibile tutto il resto.
    try:
        logger.info("[%s] Parsing: %s", job.id, filename)
        t_phase = time.time()
        file_bytes = raw_path.read_bytes()
        parse_result = parse_document(file_bytes, filename)
        metrics_store.record_processing(
            doc_id=doc_id, phase="parse",
            duration_s=time.time() - t_phase, filename=filename,
        )
        update_progress(1)

        logger.info("[%s] Normalizzazione", job.id)
        t_phase = time.time()
        normalized_text = normalizer.normalize(parse_result.text)
        processed_path.write_text(normalized_text, encoding="utf-8")
        metrics_store.record_processing(
            doc_id=doc_id, phase="normalize",
            duration_s=time.time() - t_phase, filename=filename,
        )
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
        _save_catalog(catalog)
        update_progress(3)

    except Exception as e:
        logger.error("[%s] FALLITO (parsing/normalizzazione): %s — %s", job.id, filename, e)
        _mark_doc_error(str(e))
        activity_log.log(ActivityAction.ERROR, filename, doc_id, detail=str(e)[:80])
        raise

    # ============ FASE 2 — Chunking + Embedding + Indicizzazione ============
    # Isolata dalla fase 1: se fallisce il testo normalizzato esiste comunque,
    # quindi wiki e grafo (che dipendono solo da quello) restano possibili.
    indexing_error = None
    chunks_count = None
    try:
        logger.info("[%s] Chunking", job.id)
        t_phase = time.time()
        chunks = chunk_manager.chunk_text(normalized_text, doc_id)
        chunks_count = len(chunks)
        metrics_store.record_processing(
            doc_id=doc_id, phase="chunk",
            duration_s=time.time() - t_phase, filename=filename,
        )
        update_progress(4)

        logger.info("[%s] Embedding %d chunk", job.id, len(chunks))
        t_phase = time.time()
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
        metrics_store.record_processing(
            doc_id=doc_id, phase="embed_index",
            duration_s=time.time() - t_phase, filename=filename,
        )
        update_progress(5)

        for doc in catalog["documents"]:
            if doc["id"] == doc_id:
                doc["chunks_count"] = len(chunks)
                doc["chunk_strategy"] = settings.CHUNK_STRATEGY
                doc["status"] = DocumentStatus.READY.value
                doc["error_message"] = None
                doc["updated_at"] = datetime.now().isoformat()
                break
        _save_catalog(catalog)

        activity_log.log(
            ActivityAction.READY, filename, doc_id,
            detail=f"{len(chunks)} chunk",
        )
        logger.info("[%s] INDICIZZATO: %s -> %d chunk", job.id, filename, len(chunks))

    except Exception as e:
        indexing_error = str(e)
        logger.error("[%s] FALLITO (indicizzazione): %s — %s", job.id, filename, e)
        _mark_doc_error(indexing_error)
        activity_log.log(ActivityAction.ERROR, filename, doc_id, detail=indexing_error[:80])
        # NON raise: i job downstream vengono comunque accodati qui sotto

    # ==== FASE 3 — Artefatti derivati: WIKI PRIMA, GRAFO DOPO ====
    # Dopo l'indicizzazione viene accodata SOLO la wiki. Il grafo del
    # documento parte solo al COMPLETAMENTO della wiki (catena gestita in
    # generate_wiki_job): la sequenza è deterministicamente wiki → grafo,
    # mai in parallelo. Se la wiki fallisce il grafo non parte (requisito
    # pipeline: carica → chunk → wiki → grafo).
    downstream = 0
    if processed_path.exists():
        # Ripulisce residui pendenti di tentativi precedenti (es. dopo un
        # retry di un job fallito) per evitare esecuzioni doppie.
        job_queue.cancel_pending_for_doc(
            doc_id, reason="Annullato: sostituito dal nuovo processing del documento"
        )
        job_queue.enqueue("generate_wiki", {
            "doc_id": doc_id,
            "filename": filename,
            "chain_graph": True,   # il grafo verrà accodato dopo la wiki
        })
        downstream = 1
        logger.info("[%s] Accodata wiki per %s (il grafo partirà al completamento)", job.id, filename)

    if indexing_error:
        # Il job fallisce per tracciabilità, ma la wiki è già in coda
        raise RuntimeError(indexing_error)

    return {"chunks": chunks_count, "filename": filename, "downstream_jobs": downstream}


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